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
