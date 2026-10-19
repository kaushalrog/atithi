# Performance plan

**Date:** 2026-10-19. **Branch:** `perf/audit`. **Evidence:** [PERFORMANCE_AUDIT.md](PERFORMANCE_AUDIT.md) (findings F1–F10) and [perf/baseline.json](perf/baseline.json).

**Status:** proposed. Every change below targets a measured or statically verified finding. Nothing here is implemented until `/plan-eng-review` settles the open decisions (§5).

## Ground rules

- **The booking stays authoritative.** A booking is reported as confirmed only after its SQLite insert commits, which happens inside `reserve_booking` before the tool returns. Nothing below may report a booking before that commit, or turn a failed or ambiguous booking into a success. The Sheets copy stays a non-authoritative copy.
- **No new infrastructure.**
  - No new services: no PostgreSQL, Redis or task queue. The fake-provider measurements show no need: storage and the dashboard are milliseconds at pilot scale (F10).
  - Background work uses one bounded in-process queue and worker thread.
  - Timeouts use the standard library.
- **Architecture rules stay:**
  - Provider code stays in its file: Gemini in `llm.py`, Twilio in `telephony.py`, edge-tts in `tts.py`, all disk and Sheets I/O in `storage.py`.
  - No frameworks.
  - Tenant isolation is unchanged.
- **Every change ships with:**
  - a regression test that fails without it
  - the full offline suite passing on 3.11 and 3.13
  - a `bench_load.py` re-run compared against `baseline.json`

## 1. Instrumentation (do first: it's how the fixes and a real pilot get measured)

**New `perf.py`** (stdlib only, about 100 lines):
- `span(name, call=None, **labels)`: a context manager timing a block with `time.perf_counter()` (monotonic).
- `event(name, call=None, **labels)`: a counter, for errors, timeouts and cancellations.
- Results go to a bounded in-memory store: per span name, the count, error count and the last 512 durations (`collections.deque(maxlen=512)`), giving p50, p95 and p99.
- `snapshot()` returns those numbers. The store's memory is fixed.
- If `VOXAGENT_PERF_LOG=<path>` is set, it also appends one JSON line per span: `{ts (timezone-aware ISO), name, ms, ok, call, labels}`.

**Labels:** only from an allowlist: `tool`, `channel`, `round`, `outcome`, `status`. Never message text, names, phone numbers or keys. `call` is a random 12-character id per conversation (`ReceptionistAgent.perf_id`), not the phone number or the Twilio SID.

**Where:**

| Span / metric | Location | Measures |
|---|---|---|
| `turn` (+ `rounds` label) | `agent.chat` | Whole text turn; number of model round trips |
| `model.request` | `agent.chat`, around `llm.send` | Each model round trip (provider-neutral) |
| `tool.<name>` | `agent.run_tool` | Tool time by type |
| `db.booking_insert` | `storage.reserve_booking` | The authoritative transaction |
| `sheets.copy` | The Sheets worker (§2) | Secondary copy, off the call path |
| `call_log.write`, `trace.write` | `storage.log_call_from_agent` | Record and trace persistence |
| `call.model_connect` | `twilio_stream` | Opening the Live session |
| `call.first_audio` | `TwilioBridge` | Caller's last words to our first audio frame |
| `call.reply_audio` | `TwilioBridge` | First to last audio frame of a reply (time to completed output) |
| `turn.finalize` | `TurnRecorder.flush` | Caller's last words to the turn being written |
| `loop.lag` | One monitor task per process, started with the first call | Event-loop lag, sampled every 250 ms |
| Gauges | `perf.gauge` | Active calls, active web sessions, Sheets queue depth |
| Events | Where they happen | `timeout.*`, `cancelled.*`, `error.*`, `sheets.dropped` |

**Exposure:** `GET /api/admin/perf` (admin only) returns `perf.snapshot()`.

**Tests:**
- Spans record durations and the allowlisted labels only.
- A forbidden label key raises in test mode.
- The store's memory stays bounded at 10,000 spans.
- The JSONL line has a timezone offset.
- The endpoint needs admin.

**Bench:** `bench.py` measures the cost of `perf.span` itself. Target: under 10 µs.

## 2. Fixes, in the required priority order

### 2.1 Blocking I/O on the event loop (F2, F1's phone half)

**Change:**
- `TwilioBridge.pump_gemini` runs tools with `await asyncio.to_thread(self.turn.tool_calls, calls)`; `live_main.py` does the same.
- Call start builds the agent with `await asyncio.to_thread(ReceptionistAgent, client_id)`.
- `twilio_voice` runs `resolve_client` + `billing.client_active` in `asyncio.to_thread`.

**Why it's safe:**
- `pump_gemini` handles one event at a time and `await`s the tool. No other code touches *this* call's `TurnRecorder` while the thread runs.
- Other calls keep their event loop.
- `storage` already uses thread-local SQLite connections and a write lock (storage.py:93, :189, :215).

**Tests:**
- A FakeLive call whose booking tool sleeps 300 ms, run alongside a second call's 20 ms media feeder: the second call's frame lateness must stay under 50 ms. **Baseline:** 99–124 ms with a held lock; 1,000+ ms with slow Sheets.
- The booking still returns `confirmed` only after the row exists.

**Expected bench change:** `phone_book_slow_db` event-loop lag max goes from 134 ms to under 10 ms. `phone_book_sheets_*` loop lag goes to under 10 ms (with §2.5).

### 2.2 Unnecessary model, tool or audio round trips

**No change.** The scripted workload showed none (1–2 model calls per turn). The plan adds the `rounds` label so the real-model pilot can show whether Gemini makes extra calls.

### 2.3 Unbounded queues, history and task creation (F8, F7)

**(a) Per-session lock (F7).** `run_turn` takes a non-blocking per-session `threading.Lock`. A second request while one is in flight gets **409** ("still answering your last message"). It doesn't wait, which would hold a worker thread.
- **Test:** two simultaneous `/api/chat` requests on one session give one 200 and one 409, and the history is intact (1,000 repetitions, 0 broken pairs).

**(b) Caps** (values pending decision §5-D2):
- turns per web session, for example 60 customer turns; after that, a polite closing reply and no model call
- active web sessions per business, for example 20, giving 429 at session creation
- total sessions, for example 500

Idle sessions (2 h) are purged on every request (O(sessions), about microseconds), not only when a session is created.
- **Tests:** each cap; idle purge on chat.

**(c) Bounded background work:** the Sheets queue (§2.5) is bounded. No unbounded `create_task`: the loop monitor is a single task, and the pump is one task per call (already true).

### 2.4 Slow database queries or dashboard scans (F10)

**No change.** Measured at 22 ms warm / 113 ms cold for 5,000 calls. Revisit when a business passes about 20,000 calls; the `dashboard` span (§1) will show it.

### 2.5 Slow non-authoritative work on the call path (F1)

**Change:** `reserve_booking` commits to SQLite, then **enqueues** the Sheets copy and returns at once.
- **The queue:** `queue.Queue(maxsize=1000)`, consumed by one daemon worker thread started on first use.
- **The worker:**
  - calls `append_row` with a gspread client timeout of `(5 s connect, 10 s read)`
  - on failure retries 3 times with backoff (2 s, 8 s, 30 s)
  - after the last failure logs the booking id plus the error, and counts `sheets.dropped`
- **A full queue** drops the copy with the same log and counter. The booking itself is never affected.
- **Exit:** `atexit` drains for up to 5 s, then reports how many copies remain.
- **Restore path:** the existing `python storage.py export-csv` + `import-sheet`. Bookings are never lost, because SQLite is the source of truth.

**What the agent reads:** the tool result's `saved_to` becomes `"bookings.db"`, with the Sheet copy noted as queued in the log. The model's wording doesn't depend on it.

**Tests:**
- With a 2 s fake worksheet, the booking tool returns in under 100 ms and the copy lands afterwards.
- A raising worksheet retries, then counts it as dropped.
- A full queue drops the copy without blocking.
- The booking is confirmed before any copy runs.
- Test mode never copies (unchanged).

**Expected bench change:** `phone_book_sheets_slow` (5 calls) TTFA p99 goes from 5,031 ms to about 252 ms, and loop lag max from 5,021 ms to under 10 ms. `web_book_sheets_slow` p99 overhead goes from 1,016 ms to under 30 ms.

### 2.6 Missing timeouts, cancellation and cleanup (F3, F4, F5, F6)

**(a) The model stream dies, so end the call cleanly (F3).** `twilio_stream` waits on both `read_twilio` and the pump with `asyncio.wait(..., FIRST_COMPLETED)`:
- If the pump ends first (an error, or the Live session closing), log `error.model_stream`, close the Twilio socket, and cancel the reader.
- The TwiML gains `<Say>` after `</Connect>`: "Sorry, we're having trouble right now. Please call back in a few minutes." Twilio's documentation says it plays when the stream ends. That's **unverified** until a real call (SAFE_TESTING §5).
- **Test:** a FakeLive that raises mid-call closes the websocket within 1 s, and the call record is still saved. **Baseline:** 5/5 silent.

**(b) Live connect timeout (F4).** `await asyncio.wait_for(live.connect(...), timeout=LIVE_CONNECT_TIMEOUT_S)` with a default of 10 s. On timeout: log, release the slot, close the socket, and the TwiML apology plays.
- **Test:** a connect that never returns closes within the timeout and frees the slot.

**(c) Web model retry budget (F5).** `_call_with_retry` gets a total sleep budget per request, for example 8 s (decision §5-D3). Today it can sleep up to about 75 s. When the budget runs out it raises, and `/api/chat` already returns the degraded front-desk reply.
- **Test:** with three fake 429s carrying a 20 s retry delay, the request gives up within the budget.

**(d) TTS timeout (F6).** `asyncio.wait_for(self._collect(...), 15 s)` inside `tts.py`. On timeout `/api/tts` returns 504, and the portal already shows the text reply.
- **Test:** a stalled fake stream raises within the timeout.

**(e) Sheets timeout:** covered by §2.5.

### 2.7 Resource contention and deployment constraints

- **Document** in SETUP.md and SAFE_TESTING.md:
  - one process
  - anyio's 40 worker threads serve all portal requests
  - `asyncio.to_thread` uses the default executor (`min(32, CPUs + 4)` threads)
  - `MAX_CONCURRENT_CALLS` must match the Gemini tier
- **Startup log:** print these numbers once.
- **No code change** beyond that, unless the pilot's `loop.lag` and gauges show contention.

## 3. Phase 5 items (security and product correctness)

| Item | Proposal | Decision |
|---|---|---|
| Login/code throttling (M9) | In-memory sliding window per IP + per account on `/api/auth/login`, `/api/portal/login`, `/api/auth/reset`, admin key: 10 attempts / 10 min, then 429 | §5-D4 |
| Demo access-code rotation (M10) | A script `python storage.py rotate-codes demo_clinic lakshmi_beauty_salon` writing new random codes; the old ones stay in git history, so rotate before any public repo or exposed server | §5-D5 |
| Conversion metric (M1) | Count calls whose trace has a `book` action with `ok: true` (fall back to the current substring for old calls without a trace) | §5-D6 |
| Cost caps | Covered by the turn and session caps (§2.3b) and the retry budget (§2.6c) | via D2/D3 |
| Retention (M11) | Out of scope (needs the owner's policy); TODOS | none |
| Single process | Documented (§2.7) | none |
| Live calls | **Stay off.** Nothing here turns them on | none |

## 4. Order of work and how each step is proven

1. `perf.py` + instrumentation + `/api/admin/perf` (§1) → tests; bench overhead check.
2. Sheets worker (§2.5) → tests; bench `phone_book_sheets_*`, `web_book_sheets_slow`.
3. Tools and agent construction off the loop (§2.1) → tests; bench `phone_book_slow_db`.
4. Model-stream death + connect timeout + TwiML apology (§2.6a,b) → tests; bench `phone_model_drop` (target: 0 silent hang-ups).
5. Session lock + caps + idle purge (§2.3) → tests; bench `web_double_submit` (target: 0/1000 broken).
6. Retry budget + TTS timeout (§2.6c,d) → tests.
7. Phase 5 items as decided.
8. `bench_load.py --suite full --out docs/perf/after.json` plus a before/after table in PERFORMANCE_AUDIT.md §6. Then `/review` and QA.

## 5. Decisions needed (for `/plan-eng-review`)

- **D1:** add `perf.py` and `/api/admin/perf` (a new module; CLAUDE.md asks for owner approval).
- **D2:** the cap values: turns per session, sessions per business, total sessions.
- **D3:** the web retry budget (8 s proposed). A lower budget means more "front desk will call you back" replies on the free tier's 5 requests per minute.
- **D4:** login throttling now, or keep it in TODOS.
- **D5:** add the code-rotation command now, or rotate by hand.
- **D6:** fix the conversion metric in this branch, or later.
- **D7:** the TwiML apology `<Say>` after `</Connect>` (unverified Twilio behaviour; with no apology, closing just hangs up).

## 6. Not claimed

No real-provider latency. No "supports N concurrent calls": the fake-provider runs at 10 calls only show that VoxAgent's *own* code adds under 3 ms and doesn't stall when nothing fails. Real capacity depends on Gemini Live session limits (free tier about 3), network, and Twilio, none of which were measured.

---

# Engineering review (2026-10-19)

**Produced by:** /plan-eng-review. **Target (fixed):** this file, `docs/PERFORMANCE_PLAN.md` §1–§6 above, which is unchanged as the original plan. **Evidence:** `docs/PERFORMANCE_AUDIT.md`, `docs/perf/baseline.json` (`ceba04f`).

## Scope Challenge

### A. Assessment

**What already solves each sub-problem:**
- **Thread-safe storage.**
  - thread-local SQLite connections (storage.py:189, :215)
  - one write lock (storage.py:93)
  - `asyncio.to_thread` already used for the hang-up save (telephony.py:509)

  This is what makes §2.1 a small change.
- **Bounded waits:** `asyncio.wait_for` is already used for the stream's start message (telephony.py:436), the pattern for §2.6b.
- **The degraded reply** already exists for any `/api/chat` failure (server.py:604-616), so §2.6c needs no new user-facing path.
- **Single entry points:**
  - All Sheets writes go through `_mirror_to_google_sheet`, which `reserve_booking` calls. That's the only change point for §2.5.
  - Both text channels (`/api/chat` and `/api/voice`) go through `run_turn` (server.py:634), the one place for the §2.3a session lock.
- **The portal already blocks a double-click:** a `busy` flag and a disabled Send button (web/index.html:938-943). F7 needs two tabs, the voice path or a direct API call, so it's less likely; the impact is unchanged.

**Minimum change for the goal (latency and no frozen or silent calls):** §2.1, §2.5 and §2.6a/b. §1 instrumentation is how the goal is proven later. §2.3 and §2.6c/d are capacity and reliability. The §3 Phase 5 items are not performance work.

**Complexity (estimated):**
- About 18 files: perf.py (new), agent.py, storage.py, telephony.py, live_main.py, server.py, llm.py, tts.py, bench.py, bench_load.py, about 6 test files, SETUP.md, SAFE_TESTING.md and PERFORMANCE_AUDIT.md.
- 2 new classes or services: the perf store and the Sheets copy worker.
- **The complexity gate trips.**

**Search check:** [Layer 1], standard library only: `asyncio.to_thread`, `asyncio.wait_for`, `queue.Queue`, `threading.Thread`, `collections.deque`. gspread's own `HTTPClient.set_timeout` (gspread 6.2.1, `http_client.py:93`) exists for the Sheets timeout. No web search was run; these are stable standard-library and installed-package APIs, read from the installed source.

**TODOS cross-reference:**
- "End phone calls cleanly / non-blocking loop" (M7/M8) is fully covered by §2.1 + §2.6a.
- "Rate-limit credential endpoints" (M9), "Per-session budgets" and "Compute call metrics…" (M1) overlap the §3 items.

**Distribution:** none. The benchmark and module ship in the repo.

### Reality rows

| Premise | Claim | Receipt | Verdict |
|---|---|---|---|
| P1 | The Sheets copy runs inside `reserve_booking` | storage.py:408-430 | verified |
| P2 | Phone tools run on the event loop | telephony.py:307, live_main.py:88 | verified |
| P3 | gspread has no default timeout | gspread http_client.py:84 (`timeout = None`) | verified |
| P4 | A Live socket close raises out of `events()` | google-genai live.py:555 | verified |
| P5 | Portal endpoints run in a 40-thread pool | anyio 4.15.1 `current_default_thread_limiter().total_tokens == 40` | verified (probe) |
| P6 | TwiML has nothing after `<Connect>` | telephony.py:379-385 | verified |
| P7 | Twilio plays TwiML after `<Connect>` when our stream closes | Twilio docs; no real call | **unverified** |
| P8 | `HttpOptions.timeout` bounds the Live websocket handshake | none | **unverified** |

`unverified=2`

```
REALITY: premise-table finding unverified=2 (P7 TwiML-after-Connect, P8 Live handshake timeout) telephony.py:379
REALITY: already-done pass origin/main == local main e181c9c; no perf work there (git log) e181c9c
REALITY: surface-check finding planned GET /api/admin/perf and VOXAGENT_PERF_LOG do not exist yet; existing routes checked in server.py server.py:345
REALITY: binding-decisions pass no logged decisions for perf/audit; Lane A decisions (D3 TurnRecorder, D7/D8 guarded off-loop finish) are kept docs/IMPLEMENTATION_PLAN.md:116
REALITY: numbers finding all targets [estimated]; baselines [measured: docs/perf/baseline.json @ ceba04f, re-measure before gate] docs/perf/baseline.json:1
REALITY: deferred-asks pass brief items mapped in §1-§6; Phase 5 fixes put to the user, not dropped docs/PERFORMANCE_PLAN.md:1
REALITY: pr-count pass one branch perf/audit, local; no ship policy 8bb7d6c
```

### B. Complexity gate

The proposed feature deferrals are the three Phase 5 fixes (§3: throttling, code rotation, conversion metric). They're asked one at a time. Then comes the structure question.

### Scope record (B)

- **Feature answers:**
  - Login/code throttling (§3, plan D4): **deferred** (D1).
  - Code-rotation command (§3, plan D5): **deferred**, rotate by hand (D2).
  - Conversion-metric fix (§3, plan D6): **kept in this branch** (D3).
- **Structure:** A, "Original arrangement" (D4).
- **Accepted scope:**
  - **New `perf.py`:** in-memory spans, events, gauges and snapshot; no disk I/O.
  - **`storage.py`:** gains the optional perf JSONL writer and the bounded Sheets copy worker.
  - **Fixes:** §2.1, §2.3, §2.5, §2.6 and §2.7, plus the conversion metric.
  - **Instrumentation call sites:** agent.py, storage.py, telephony.py, live_main.py and server.py.
- **Pending remedies:** plan D1 (instrumentation and `/api/admin/perf`), plan D2 (cap values), plan D3 (retry budget), plan D7 (TwiML apology), and review finding R1.

### C. Findings

1. **R1 [P1] (confidence 9/10). Plan §2.1 lets a booking escape the call record.**
   - **Where:** telephony.py:484-498 (teardown) with the proposed `await asyncio.to_thread(self.turn.tool_calls, calls)`.
   - **How:** on hang-up, `pump.cancel()` cancels the *await*, but a worker thread already running `reserve_booking` keeps going. `asyncio.to_thread` can't stop it.
   - **What's lost:** the booking commits to SQLite, but its `TurnRecorder` entries can be appended after `bridge.finish()` has flushed and saved the trace. That gives a confirmed booking with no action in the call's trace: the exact "did Y, record says nothing" gap the checker exists for. Two threads would also touch the same `TurnRecorder`.
   - **Reviewer:** Claude (this review).
2. **R2 [P2] (confidence 9/10). Plan §1's optional JSONL perf log is disk I/O outside storage.py, and it has no size bound.** Resolved structurally by D4: the writer moves to storage.py. The size bound is part of plan D1's remedy below.
3. **Plan D1, D2, D3 and D7** are carried open from the plan.

## Decision ledger

### PD1: instrumentation, and how much of it ships
Finding: plan D1 + R2; audit F9 (no timings, no correlation id, failures are print lines). Reviewer: Claude
Plan baseline: plan §1 (perf.py, spans at 12 sites, /api/admin/perf, opt-in JSONL), proposed only; brief Phase 2 asks to "add or propose" measurements.
Runtime evidence: no timing or metric code exists (static read); every number so far came from bench_load.py.
Comparison grid:
Commitment | Source | Current | A Full | B Spans only | C Propose only
perf.py in-memory spans/events/gauges | plan §1 | none | yes | yes | no
Spans at the plan §1 sites | plan §1 | none | yes | yes | no
/api/admin/perf (admin only) | plan §1 | none | yes | no | no
Opt-in JSONL log (VOXAGENT_PERF_LOG) | plan §1 | none | yes, written by storage.py, rolls over at 20 MB to one .1 backup | no | no
Event-loop lag monitor (one task) | plan §1 | none | yes | yes | no
Label allowlist, no PII, random call id | plan §1 | — | yes | yes | n/a
Tests | required | — | spans, allowlist, bounded store, aware ts, endpoint auth, log rollover | spans, allowlist, bounded store | none
Question D5:
D5 — PD1: Which instrumentation ships in this branch?
Header: Instrumentation
Options:
A) Full: spans + admin endpoint + log (recommended)
Effort M (human ~1 day / CC ~40min), risk low. perf.py spans at the plan's 12 sites, an event-loop lag monitor, GET /api/admin/perf for live numbers, and an opt-in JSONL log written by storage.py that rolls over at 20 MB. You can see a real pilot's latency without a debugger.
B) Spans only, no endpoint or log
Effort S (human ~5h / CC ~25min), risk low. The same spans, readable only from tests and the benchmark. Less surface, but a real pilot's numbers stay invisible unless someone attaches a debugger.
C) Propose only, no code
Effort S (zero implementation now), risk medium. The fixes ship without instrumentation; the before/after story rests on bench_load.py only, and production problems stay invisible (audit F9).

State: approved
Actual answer: A "Full: spans + admin endpoint + log (recommended)", D5 2026-10-19
Accepted scope: perf.py (in-memory spans/events/gauges/snapshot, label allowlist, random per-conversation call id, bounded 512-sample store per name); spans at the plan §1 sites; one event-loop lag monitor task; GET /api/admin/perf (admin only); opt-in VOXAGENT_PERF_LOG JSONL written by storage.py, rolling over at 20 MB to one .1 backup; tests: spans, allowlist, bounded store, aware timestamps, endpoint auth, log rollover.
History: none

### R1: a booking must not escape the call record when tools move off the loop
Finding: R1, P1, confidence 9/10, telephony.py:484-498 with plan §2.1. Reviewer: Claude
Plan baseline: plan §2.1 "run tools with await asyncio.to_thread(self.turn.tool_calls, calls)" (pending implementation); Lane A approved invariant: every booking appears in its call's record and trace (eng D3/D7).
Runtime evidence: asyncio.to_thread cannot stop a running thread on cancel (Python docs; static). Not reproduced, because the code doesn't exist yet.
Comparison grid:
Commitment | Source | Current | A Await in-flight tool | B Never cancel during a tool | C Keep tools on loop
Tools run off the event loop | plan §2.1 | no | yes | yes | no (stalls stay, F2)
Booking always in the record/trace | Lane A invariant | yes (on-loop) | yes: teardown awaits the in-flight tool future (up to 15 s, then logs `timeout.tool_teardown`) before finish() | yes: pump cancel deferred until the tool returns | yes
One thread touches TurnRecorder at a time | required | yes | yes (finish waits) | yes | yes
Hang-up teardown time | — | immediate | + remaining tool time (≤15 s) | + remaining tool time (unbounded) | immediate
Tests | required | — | hang-up mid-booking: booking in trace; teardown bound | same | none
Question D6:
D6 — R1: How should a hang-up during a running tool keep the booking in the record?
Header: Tool on hang-up
Options:
A) Await the in-flight tool (recommended)
Effort S (human ~2h / CC ~10min), risk low. The bridge keeps the running tool's future; on hang-up, teardown waits for it (at most 15 s, then logs a timeout) before saving the call. The booking and its trace entry always land together.
B) Defer cancelling the pump until the tool returns
Effort S (human ~3h / CC ~15min), risk medium. Same outcome, but the wait is unbounded and the logic sits in the cancel path, which is harder to read.
C) Keep tools on the event loop (drop plan §2.1)
Effort S (zero implementation), risk high. No race, but a slow database or Sheets call keeps freezing every live call (audit F2: up to 134 ms measured, 10 s possible).

State: approved
Actual answer: A "Await the in-flight tool (recommended)", D6 2026-10-19
Accepted scope: TwilioBridge (and live_main) keep the running tool's future; tools run via asyncio.to_thread; on teardown, before finish(), await the in-flight tool future up to 15 s (then log `timeout.tool_teardown` and continue); only one thread touches TurnRecorder at a time; test: hang-up mid-booking leaves the booking in the trace, and a teardown wait bound test.
History: none

### PD2: cap values for web test-call sessions
Finding: audit F8 (unbounded history and sessions); plan §2.3b. Reviewer: Claude
Plan baseline: §2.3b caps with example values (60 / 20 / 500), values pending; scope record accepts §2.3 (lock, caps, idle purge on every request).
Runtime evidence: an 800-turn session sends 324k characters per model request; nothing limits sessions (server.py:126, 281-286, 575-600).
Comparison grid:
Commitment | Source | Current | A Generous | B Tight | C Only idle purge
Customer turns per session | pending | unlimited | 60, then a polite closing reply with no model call | 30 | unlimited
Active sessions per business | pending | unlimited | 20 → 429 at /api/session | 10 | unlimited
Total active sessions | pending | unlimited | 500 → 429 | 200 | unlimited
Idle purge on every request | scope record | only at creation | yes | yes | yes
Per-session lock (409) | scope record | none | yes | yes | yes
Tests | required | — | each cap + purge | each cap + purge | purge only
Question D7:
D7 — PD2: What limits should web test-call sessions have?
Header: Session caps
Options:
A) 60 turns / 20 per business / 500 total (recommended)
Effort S (human ~3h / CC ~15min), risk low. Far above a real test call (about 5-15 turns) but stops runaway sessions: a session ends politely at 60 customer turns, and a business can't hold more than 20 open sessions.
B) 30 turns / 10 per business / 200 total
Effort S (human ~3h / CC ~15min), risk low. Tighter cost control; a long, thorough demo could hit 30 turns and see the closing reply.
C) No caps, idle purge only
Effort S (human ~1h / CC ~5min), risk medium. Sessions and history stay unbounded (F8); a stuck script or abuse grows memory and model cost without limit.

State: approved
Actual answer: A "60 turns / 20 per business / 500 total (recommended)", D7 2026-10-19
Accepted scope: web test-call sessions: at 60 customer turns, a polite closing reply with no model call; at most 20 active sessions per business and 500 in total (429 at /api/session); idle (2 h) purge on every request; per-session non-blocking lock → 409 while a turn is in flight (chat and voice, via run_turn); tests for each cap, the purge, and the lock (1,000 repetitions, 0 broken pairs).
History: none

### PD3: total retry wait for one text/voice model request
Finding: audit F5 (a request can sleep about 75 s across 3 retries while holding one of 40 shared worker threads). Reviewer: Claude
Plan baseline: plan §2.6c proposed an 8 s budget; value pending.
Runtime evidence: `_retry_wait` honours Google's retryDelay, capped at 25 s per retry, 3 retries (llm.py:134-146, 246-267). Real free-tier 429 delays are unverified; Google's error body often asks for tens of seconds.
Comparison grid:
Commitment | Source | Current | A 25 s | B 8 s | C Keep
Total retry sleep per request | pending | up to ~75 s | ≤ 25 s (about one honoured retry) | ≤ 8 s | ~75 s
Worker thread held by one stuck chat | — | ~75 s + timeouts | ~25 s + timeouts | ~8 s + timeouts | ~75 s
When the budget runs out | existing degraded path | n/a | raise → front-desk reply | same | n/a
Applies to | — | chat + speech-to-text | both | both | both
Daily-quota fast fail | existing | yes | unchanged | unchanged | unchanged
Test | required | — | fake 429s with a 20 s delay → gives up within budget | same | none
Question D8:
D8 — PD3: How long may one model request keep retrying before the customer gets the fallback reply?
Header: Retry budget
Options:
A) 25 s total (recommended)
Effort S (human ~1h / CC ~5min), risk low. Enough for one retry that honours Google's requested delay, so a brief rate limit recovers. A stuck request frees its worker thread after ~25 s instead of ~75 s.
B) 8 s total
Effort S (human ~1h / CC ~5min), risk medium. Threads free fastest, but on the free tier most rate limits ask for longer than 8 s, so more test calls see "the front desk will call you back".
C) Keep today's ~75 s
Effort S (zero implementation), risk medium. Rate limits usually recover, but a customer can wait over a minute in silence and 40 such requests block the whole portal.

State: approved
Actual answer: A "25 s total (recommended)", D8 2026-10-19
Accepted scope: GeminiLLM._call_with_retry gets a total retry-sleep budget of 25 s per request (chat and transcribe); a retry whose wait would exceed the remaining budget raises instead; the daily-quota fast fail is unchanged; /api/chat's existing degraded reply covers it; test: fake 429s asking for 20 s give up within the budget.
History: none

### PD7: what the caller hears when we end a failed phone call
History note: a draft listed a third option identical to B; it was removed before asking.
Finding: audit F3/F4 (silent line after the model drops; no connect timeout); plan §2.6a/b. Reviewer: Claude
Plan baseline: the scope record accepts §2.6: close the Twilio socket when the pump dies, and a 10 s Live connect timeout. Pending: whether TwiML gets a spoken apology after </Connect>.
Runtime evidence: the TwiML is `<Connect><Stream/></Connect>` only (telephony.py:379-385). Twilio documents that TwiML after <Connect> runs when the stream ends, but that's unverified here (P7).
Comparison grid:
Commitment | Source | Current | A Close + apology | B Close only
Socket closed when the model stream dies or connect times out | scope record §2.6 | no (silent until caller hangs up) | yes | yes
Spoken apology after </Connect> | pending | none | `<Say>Sorry, we're having trouble right now. Please call back in a few minutes.</Say>` | none: the call just ends
Normal hang-up by caller | — | unchanged | unchanged (stream "stop" ends the call; TwiML after Connect may still run but the caller is gone) | unchanged
SAFE_TESTING §5 step | docs | — | add "kill the model mid-call, hear the apology" | add "call drops"
Test | required | — | TwiML contains the Say after Connect, escaped | TwiML unchanged
Question D9:
D9 — PD7: When a phone call fails mid-way, should the caller hear an apology before it ends?
Header: Failure apology
Options:
A) Close the stream and play an apology (recommended)
Effort S (human ~1h / CC ~5min), risk low. TwiML gets a <Say> after </Connect>, so when we close a failed stream Twilio speaks a short apology, then hangs up. If Twilio doesn't play it (unverified until a real call), the call still ends cleanly.
B) Close the stream only
Effort S (zero extra), risk low. The call simply drops when the model fails: better than silence, but the caller doesn't know why.

State: approved
Actual answer: A "Close the stream and play an apology (recommended)", D9 2026-10-19
Accepted scope: TwiML gets `<Say>Sorry, we're having trouble right now. Please call back in a few minutes.</Say>` after </Connect> (escaped like the rest); twilio_stream closes the Twilio socket when the pump ends first or the 10 s Live connect times out; SAFE_TESTING §5 gains "end the model session mid-call and hear the apology"; tests: TwiML shape, close-on-pump-death within 1 s, connect-timeout close and slot release.
History: none

## Review sections

### 1. Architecture

**Data flow after the accepted changes (phone):**

```
 Twilio media ──► read_twilio (loop) ──► live.send_audio
 Gemini Live ──► pump_gemini (loop) ──┬─ audio ──► ws.send_json(media)          [perf: call.first_audio / reply_audio]
                                      ├─ text ──► TurnRecorder buffer
                                      └─ tool_calls ──► tool_future = to_thread(TurnRecorder.tool_calls)   (R1/D6)
                                                          └─ run_tool ─► reserve_booking ─► SQLite COMMIT ─► return "confirmed"
                                                                                           └─► SheetsQueue.put (non-blocking; drop+count if full)
 SheetsWorker thread ◄── SheetsQueue (max 1000) ─► gspread append_row (timeout 5 s / 10 s, 3 retries 2/8/30 s)
 twilio_stream: wait(FIRST_COMPLETED: reader, pump)
   pump ends first ──► close Twilio socket ──► Twilio plays <Say> after </Connect> (D9, unverified) ──► hang-up
   teardown ──► await tool_future (≤15 s, D6) ──► to_thread(finish) ──► call record + trace (atomic)
```

Findings:
- [P2] (confidence 8/10) **The default thread pool is small on a small VM.** `asyncio.to_thread` uses the loop's default executor, `min(32, CPUs + 4)` threads. That's 14 on this machine, but **5 on a 1-vCPU VM** (README suggests "a small cloud VM"). With §2.1, every phone tool and every hang-up save shares it, so 5+ simultaneous bookings would queue.
  - **Repair within the approved §2.1/§2.7:** a dedicated `ThreadPoolExecutor(max_workers=max(8, 2 × MAX_CONCURRENT_CALLS))` for call I/O, used through `loop.run_in_executor`, with its size printed at startup. It's the necessary sizing of an approved change, not a new behaviour.
- [P2] (confidence 9/10) **The conversion fix (D3) must cover three places:** `_stats_from` (server.py:657), the admin console's recent calls (server.py:388-389), and the portal badge (web/index.html:731). The mechanism is decision CV1 below.
- **Security:** `/api/admin/perf` reuses `require_admin`. Perf labels are allowlisted with no text or phone numbers, and the call id is random. No other new attack surface.
- **One production failure per new path:**

  | Path | Failure | Handling |
  |---|---|---|
  | Sheets worker | Google down for an hour | 3 retries, then `sheets.dropped` + log; the queue caps memory; `export-csv`/`import-sheet` restore the copy |
  | Tool thread | DB locked 10 s | Only that call waits; others keep their audio (§2.1) |
  | Live connect | Hangs | 10 s timeout, apology, slot released |
  | Perf log | Disk full | The write error is caught and counted, never raised into a call |

Dispositions: executor sizing is applied as necessary implementation of §2.1/§2.7. Conversion goes to CV1.

### CV1: where the conversion fix gets each call's real outcome
Finding: D3 (keep the conversion fix) + Section 1 finding; audit M1. Reviewer: Claude
Plan baseline: plan §3 "count calls whose trace has a book action with ok: true (fall back to the substring for old calls)"; scope record keeps the fix in this branch (D3).
Runtime evidence: the dashboard reads one JSON per call (read_call_logs) and is 22 ms warm at 5,000 calls (baseline). Traces live in a separate folder (D7 of Lane A).
Comparison grid:
Commitment | Source | Current | A Outcome in call record | B Read traces at dashboard time
Conversion counts only successful bookings | D3 | substring (counts failures) | yes | yes
Admin recent-calls booked/lead flags | D3 + S1 | substring | yes | yes
Portal call-history badge | D3 + S1 | substring in index.html | uses the record's outcome fields | needs the trace per call in the browser payload
Dashboard file reads per refresh | baseline 22 ms @ 5k | 1 per call | 1 per call (unchanged) | 2 per call
Old calls without the new field | — | — | fall back to today's substring rule | fall back to the substring
Tests | required | — | failed booking → not counted; old record fallback; badge fields | same + trace read
Question D10:
D10 — CV1: Where should the dashboard get each call's real booking outcome?
Header: Outcome source
Options:
A) Store it in the call record (recommended)
Effort S (human ~3h / CC ~15min), risk low. When a call is saved, write `"outcome": {"booked": …, "lead": …}` from its successful actions. The dashboard, admin console and portal badge read that field; old calls fall back to today's rule. No extra file reads.
B) Read each call's trace when the dashboard loads
Effort M (human ~5h / CC ~25min), risk medium. No change to the call record, but every refresh reads twice as many files and the dashboard depends on the trace format.

State: approved
Actual answer: A "Store it in the call record (recommended)", D10 2026-10-19
Accepted scope: log_call_from_agent writes `"outcome": {"booked": bool, "lead": bool}` from successful book/lead actions; _stats_from, the admin recent-calls flags and the portal call-history badge read it, falling back to the substring rule for records without the field; tests: a failed booking isn't counted, old-record fallback, badge fields in the payload.
History: none

### 2. Code quality

- **Shared code:** none needed.
  - The Sheets worker replaces the inline mirror, so there's one path.
  - `TurnRecorder` stays the one streaming recorder for phone and live; both channels get the same `run_in_executor` change.
  - Bounded waits use stdlib `asyncio.wait_for`, no helper.
- **perf.py contract:** spans must never raise into a call. A label outside the allowlist is dropped and counted in production, and raises in test mode (`VOXAGENT_ENV=test`), so tests catch leaks.
- **Error handling:**
  - Every new except clause names its class or is the one documented "never break a call" guard, logged with the call id and class.
  - The Sheets worker catches `Exception` per item: a background worker must survive any gspread error. It's documented in a comment and counted.
- **ASCII diagrams:**
  - The Section 1 flow goes into telephony.py's module docstring, replacing the stream diagram (lines 1-40) where it changes.
  - The `TurnRecorder` docstring stays accurate.

Dispositions: no new choices.

### 3. Tests

**Framework:** pytest (CLAUDE.md).

**Coverage of planned behaviour.** Every row is new behaviour; no tests exist yet, so all are gaps to fill.

```
CODE PATHS                                                   USER FLOWS
[+] perf.py                                                  [+] Phone caller books while Sheets is slow
  ├── span/event/gauge record, bounded store   [GAP] unit      ├── [GAP] other calls' audio not delayed (>50 ms) [→E2E bench]
  ├── label allowlist (raise in test mode)     [GAP] unit      └── [GAP] booking confirmed before any Sheets copy
  └── snapshot p50/p95/p99                     [GAP] unit    [+] Model session drops mid-call
[+] storage: Sheets queue + worker                             ├── [GAP] socket closed ≤1 s; record + trace saved
  ├── enqueue never blocks; full → drop+count  [GAP] unit      └── [GAP] TwiML has the apology after </Connect>
  ├── timeout/retry/backoff, then drop+count   [GAP] unit    [+] Hang-up while a booking runs (R1)
  ├── test mode never copies                   [★★ existing]   └── [GAP] booking present in trace; teardown ≤15 s
  └── perf JSONL writer + 20 MB rollover       [GAP] unit    [+] Portal: two tabs send at once
[+] telephony                                                  └── [GAP] one 200 + one 409; history intact ×1000
  ├── tools via call-I/O executor              [GAP] integ   [+] Portal: runaway session
  ├── wait(FIRST_COMPLETED) close on pump end  [GAP] integ     ├── [GAP] 61st turn → closing reply, no model call
  ├── Live connect timeout → close + release   [GAP] integ     └── [GAP] 21st session/business → 429
  ├── await in-flight tool before finish (R1)  [GAP] integ   [+] Owner dashboard
  └── TwiML apology                            [GAP] unit      └── [GAP] failed booking not counted; old records fall back
[+] server: lock, caps, idle purge, /api/admin/perf [GAP] integ
[+] llm: 25 s retry budget                     [GAP] unit (fake client raising 429)
[+] tts: 15 s timeout → 504                    [GAP] unit (fake stalled stream)
[+] storage: call-record outcome field         [GAP] unit
COVERAGE: 1/24 paths tested today (all the rest are new code)
```

**Regression rule (existing behaviour at risk):**
- **(a) Booking replies.** Still `confirmed` only after the row exists; `saved_to` changes from "bookings.db + Google Sheet copy" to "bookings.db". This is an intended difference; the model doesn't depend on it.
- **(b) The tool error text** stays byte-identical. The existing test is kept.
- **(c) A normal call end** still saves the record and trace, the 409 lock never blocks a single-tab user, and the existing 177 tests stay green.

These carry the approved contracts. No extra decision is needed.

**Flakiness:** timing tests use bounds 5–10× the expected value, for example "under 50 ms when the stall is 300 ms", and fake clocks where possible. The benchmark, not pytest, carries the latency numbers.

**Test Plan artifact:** written to `~/.gstack/projects/kaush/` (see Required outputs).

### 4. Performance

Measured targets for the after-run, compared with `docs/perf/baseline.json`:

| Scenario | Baseline | Target |
|---|---|---|
| `phone_book_sheets_slow` ×5: TTFA p99 / loop lag max | 5,031 / 5,021 ms | ≤ 260 / ≤ 10 ms |
| `phone_book_sheets_stall` ×2: TTFA p99 | 16,009 ms | ≤ 260 ms |
| `phone_book_slow_db` ×5: loop lag max | 134 ms | ≤ 10 ms |
| `phone_model_drop` ×5: silent hang-ups | 5/5 | 0/5 (socket closed ≤ 1 s) |
| `web_double_submit` ×1000: broken pairs | 18/20 | 0/1000 |
| `web_book_sheets_slow` ×5: overhead p99 | 1,016 ms | ≤ 40 ms |
| Healthy phone/web rows | see baseline | within ±10% (a regression check) |
| `perf.span` cost (bench.py) | n/a | < 10 µs |

**Scale:**
- The bounded Sheets queue holds at most 1,000 rows, each under 200 bytes.
- The perf store holds 512 samples × about 20 span names.
- The JSONL log is capped at 20 MB + one backup.

Dispositions: no new choices.

### Outside voice

Codex CLI is not installed (`CODEX_MODE: not_installed`). The native fallback needs a background-task wait tool this session doesn't provide, so it took the unavailable path. No outside coverage, recorded as `outside_status: unavailable`.

### TODO choices

No new TODO proposals. TODOS.md is updated mechanically to mark M7/M8 and "Compute call metrics…" as covered by this plan once implemented. M9 throttling stays (D1). Code rotation stays manual (D2).

## Approval readiness

Checked:
- **Scope:** D1 defer, D2 defer, D3 keep, D4 original arrangement.
- **Remedies:** PD1 (D5), R1 (D6), PD2 (D7), PD3 (D8), PD7 (D9), CV1 (D10).
- **Repairs of approved contracts:**
  - the call-I/O executor sizing (§2.1/§2.7)
  - the perf JSONL writer in storage.py (D4)
  - the conversion fix covering the portal badge (D3)

Approval readiness: PASS (D1, D2, D3, D4, D5, D6, D7, D8, D9, D10)

## NOT in scope

- **Login/code throttling (M9):** deferred (D1); TODOS keeps it.
- **Code-rotation command (M10):** deferred (D2); rotate by hand before any public repo or exposed server.
- **Retention/delete policy (M11):** needs the owner's policy; TODOS.
- **Dashboard scan optimisation:** 22 ms warm at 5,000 calls; revisit beyond about 20,000 (F10).
- **Real-provider latency measurement:** needs a live pilot; the instrumentation (D5) is how it gets measured.
- **Any change that enables live calls:** none; `ENABLE_LIVE_CALLS` stays off.

## What already exists

- **Thread-local SQLite connections and the write lock** (storage.py:93, :189, :215) make worker-thread tools safe.
- **`asyncio.to_thread(bridge.finish)` and the guarded teardown** (Lane A D7/D8) are the pattern reused for tools.
- **`asyncio.wait_for`** in `twilio_stream` (telephony.py:436) is the pattern for the connect timeout.
- **The degraded front-desk reply** in `/api/chat` (server.py:604-616) is the user-facing path when the retry budget runs out.
- **`bench_load.py`** is the before/after measurement for every change.

## Failure modes

| New path | Realistic failure | Test | Handling | User sees |
|---|---|---|---|---|
| Sheets worker | Google down for an hour | yes | retry ×3, drop+count+log; queue bounded | Nothing (booking confirmed); the owner's Sheet catches up via import |
| Tool executor | DB locked 10 s | yes | only that call waits | That caller waits; others don't |
| Live connect | Handshake hangs | yes | 10 s timeout, close, release slot | Apology (unverified), then the call ends |
| Pump death | Live session dropped | yes | close socket ≤1 s, record saved | Apology (unverified), then the call ends |
| Hang-up mid-tool | Booking still running | yes | await ≤15 s, then log a timeout | Nothing; the record includes the booking |
| Session lock | Two tabs | yes | 409 | "still answering" note |
| Caps | Runaway session | yes | closing reply / 429 | A polite end / a clear error |
| Retry budget | Long 429 | yes | raise after 25 s | Front-desk reply |
| TTS | Stalled stream | yes | 15 s → 504 | Text reply only |
| Perf log | Disk full | yes | caught, counted | Nothing |

**0 critical gaps.**

## Worktree parallelization strategy

| Step | Modules touched | Depends on |
|---|---|---|
| P1 perf.py + JSONL writer + /api/admin/perf | perf, storage, server | none |
| P2 Sheets worker | storage | P1 (spans) |
| P3 tools/agent off loop + executor + R1 | telephony, live_main | P1 |
| P4 pump-death close + connect timeout + TwiML | telephony | P3 |
| P5 session lock, caps, purge | server | P1 |
| P6 retry budget, TTS timeout | llm, tts | P1 |
| P7 conversion outcome field | storage, server, web | P1 |
| P8 after-bench + docs | bench_load, docs | all |

- **Lane A:** P1, then P2 and P7 (storage shared, so sequential).
- **Lane B:** P3, then P4 (telephony).
- **Lane C:** P5 (server).
- **Lane D:** P6 (llm, tts).
- **Order:** P1 first. Then Lanes A, B, C and D. Then P8.
- **Conflict flags:**
  - P1, P5 and P7 all touch server.py: keep their edits in separate functions.
  - P2 and P7 both touch storage.py, so they run sequentially in Lane A.

## Implementation Tasks

Synthesized from this review's findings. Run with Claude Code or Codex; checkbox as you ship. Ratios: features ~30x, tests ~50x.

- [ ] **P1 (P1, human: ~1 day / CC: ~40min)**: perf. Add `perf.py`, spans at the plan sites, the loop monitor, `/api/admin/perf`, and the JSONL writer in storage with 20 MB rollover.
  - Surfaced by: PD1 (D5), D4, audit F9
  - Files: perf.py, storage.py, agent.py, telephony.py, live_main.py, server.py, bench.py, tests/test_perf.py
  - Verify: `python -m pytest tests -q`; `python bench.py` shows span cost under 10 µs
- [ ] **P2 (P1, human: ~5h / CC: ~25min)**: storage. Add the bounded Sheets copy queue and worker (timeout, retry 2/8/30 s, drop+count, atexit drain); the booking returns after COMMIT.
  - Surfaced by: F1, plan §2.5
  - Files: storage.py, tests/test_storage.py
  - Verify: tests; bench `phone_book_sheets_*`, `web_book_sheets_slow`
- [ ] **P3 (P1, human: ~4h / CC: ~20min)**: telephony and live. Run tools and agent construction on the call-I/O executor; await the in-flight tool before finish (≤15 s).
  - Surfaced by: F2, R1 (D6), Section 1 executor sizing
  - Files: telephony.py, live_main.py, tests/test_telephony.py
  - Verify: tests; bench `phone_book_slow_db`
- [ ] **P4 (P1, human: ~3h / CC: ~15min)**: telephony. Close on pump death (FIRST_COMPLETED), add a 10 s Live connect timeout, and the TwiML apology.
  - Surfaced by: F3, F4, PD7 (D9)
  - Files: telephony.py, tests/test_telephony.py, docs/SAFE_TESTING.md
  - Verify: tests; bench `phone_model_drop` gives 0 silent
- [ ] **P5 (P1, human: ~3h / CC: ~15min)**: server. Add the per-session lock (409), caps 60/20/500, and idle purge per request.
  - Surfaced by: F7, F8, PD2 (D7)
  - Files: server.py, tests/test_access.py
  - Verify: tests; bench `web_double_submit` ×1000 gives 0 broken
- [ ] **P6 (P2, human: ~2h / CC: ~10min)**: llm and tts. Add the 25 s retry budget and the 15 s TTS timeout returning 504.
  - Surfaced by: F5 (D8), F6
  - Files: llm.py, tts.py, server.py, tests/test_agent.py, tests/test_tts.py
  - Verify: tests
- [ ] **P7 (P2, human: ~3h / CC: ~15min)**: dashboard. Add the `outcome` field in call records and use it for conversion, the admin flags and the portal badge.
  - Surfaced by: D3, CV1 (D10)
  - Files: storage.py, server.py, web/index.html, tests/test_dashboard.py
  - Verify: tests; a failed booking is not counted
- [ ] **P8 (P2, human: ~2h / CC: ~10min)**: measurement. Run the full bench into `docs/perf/after.json`, add a before/after table in PERFORMANCE_AUDIT.md §6, and update the docs (SETUP/SAFE_TESTING single-process and pool sizes, TODOS).
  - Surfaced by: brief Phase 6
  - Files: docs/
  - Verify: the table matches the JSON

## Unresolved decisions

None in this review.

## Completion summary

- **Step 0, Scope Challenge:** scope reduced per recommendation (throttling and the rotation command deferred); structure A.
- **Reality rows:** 7/7 applicable rows emitted (`PLAN_REALITY: phase=eng rows=7/7 missing=none unverified=2 verdict=complete`); 2 unverified premises (P7, P8).
- **Architecture Review:** 2 issues found (executor sizing; conversion fix scope).
- **Code Quality Review:** 0 new issues.
- **Test Review:** diagram produced, 23 gaps identified (all new behaviour).
- **Performance Review:** 0 new issues (targets set).
- **NOT in scope:** written. **What already exists:** written.
- **TODOS.md updates:** 0 new items proposed.
- **Failure modes:** 0 critical gaps flagged.
- **Unresolved decisions:** 0 in this review.
- **Outside voice:** codex, unavailable (not installed; native fallback unavailable).
- **Parallelization:** 4 lanes after P1; P8 last.
- **Lake Score:** 5/5 (D5, D6, D7, D8, D9 were coverage-scored; all picked the 10/10 or highest-scored option).

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 0 | — | not run for this plan |
| Codex Review | `/codex review` | Independent 2nd opinion | 0 | unavailable | Codex CLI not installed |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 1 | CLEAR | 4 issues (R1, R2, executor sizing, conversion scope), 0 critical gaps |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | — | UI change is a badge + 409 note only |

**VERDICT:** ENG CLEARED. Ready to implement P1–P8.

NO UNRESOLVED DECISIONS
