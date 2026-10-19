# Performance, latency and scale audit

**Date:** 2026-10-19. **Branch:** `perf/audit` (from `main` @ `e181c9c`). **Baseline commit for all "before" numbers:** `ceba04f` (benchmark only, no application change). **After:** `bad773e`; see §6 for what changed and the before/after numbers.

**Rule:** a finding is **Measured** only if `bench_load.py` or a probe observed it on this code. **Static** means it comes from reading the code (the evidence is a file and line). **Unverified** means it needs a real provider (Gemini, Twilio, Google Sheets, Microsoft TTS) that wasn't used.

---

## 1. What was measured, and what wasn't

**Environment:**
- macOS 27.0 on arm64 (10 CPUs, 16 GB)
- Python 3.13.13 (the suite also passes on 3.11.15)
- google-genai 2.31.0, gspread 6.2.1, FastAPI 0.146.0, Starlette 1.9.0, anyio 4.15.1

**Method:** `bench_load.py` (new) drives the **real** VoxAgent code: `ReceptionistAgent`, `TurnRecorder`, `TwilioBridge`, `server.chat`, `storage` and `scheduling`. The **providers are fake**:

| Fake | Stands in for | Behaviour |
|---|---|---|
| `SleepyLLM` | Gemini chat (web channel) | Scripted replies, a fixed 150 ms per model call. The harness subtracts the *actual* time spent inside the fake (macOS `sleep` overshoots about 4.3 ms) |
| `SimLive` | Gemini Live (phone) | Caller speaks 300 ms, optional tool call (waits for our result), fixed 250 ms "think", then 15 audio chunks paced at 20 ms |
| 20 ms media feeder | Twilio Media Streams | One inbound 20 ms μ-law frame every 20 ms, like `twilio_stream`'s `read_twilio` |
| `FakeWorksheet` | Google Sheets | `append_row` takes a configurable time or raises |
| Lock-holder thread | Another writer | Holds the SQLite write lock 450 ms out of every 500 ms |

**Isolation:**
- All storage runs in a temp folder, in test mode.
- The harness refuses to run if any data path points into the repo.
- Each scenario runs in its own subprocess.
- After every run, no `bookings.db`, `calls/` or `leads.csv` existed in the repo.

**What these numbers are:** VoxAgent's own overhead, and the stalls it causes, around providers whose latency is fixed and known.

**What they are not:** real call latency. Real Gemini first-token time, real Live audio latency, Twilio jitter and Google API latency were **not** measured. Nothing here supports a claim that VoxAgent handles N real concurrent calls.

**Reproduce:** `python bench_load.py --suite full --out results.json` takes about 2 minutes. Raw baseline: [docs/perf/baseline.json](perf/baseline.json).

---

## 2. Baseline results (fake providers)

**Phone calls**, 4 turns each. TTFA = time from the caller's last words to our first audio frame to Twilio. The fake model's think time is 250 ms, so TTFA − 250 ms is our overhead.

| Scenario | Calls | TTFA p50 / p99 (ms) | Event-loop lag p99 / max (ms) | Inbound audio lateness p99 / max (ms) | Calls OK | Silent hang-ups |
|---|---|---|---|---|---|---|
| availability turns | 10 | 250.3 / 250.8 | 1.2 / 5.9 | 1.6 / 8.1 | 10/10 | 0 |
| booking on last turn | 10 | 250.4 / 251.6 | 1.3 / 2.2 | 1.4 / 6.7 | 10/10 | 0 |
| barge-in mid-reply | 10 | 250.5 / 251.1 | 1.2 / 2.0 | 1.5 / 5.3 | 10/10 | 0 |
| booking, **Sheets 1 s** | 1 | 250.3 / **1,255.7** | 1.3 / **1,002** | 948 / 988 | 1/1 | 0 |
| booking, **Sheets 1 s** | 5 | 250.6 / **5,030.9** | 1.2 / **5,021** | 4,934 / 5,014 | 5/5 | 0 |
| booking, **Sheets stalls 8 s** | 2 | 250.4 / **16,008.9** | 1.2 / **16,000** | 15,812 / 15,991 | 2/2 | 0 |
| booking, Sheets down (raises) | 5 | normal | normal | normal | 5/5 | 0 |
| booking, **DB write lock held** | 5 | 250.6 / **389.7** | 1.2 / **134** | 104 / 124 | 5/5 | 0 |
| **Live session drops** at turn 2 | 5 | n/a | 1.2 / 5.7 | 1.3 / 7.2 | **0/5** | **5/5** |

At 1, 2, 5 and 10 calls, the healthy scenarios stayed at TTFA p99 ≤ 252.6 ms, event-loop lag p99 ≤ 1.3 ms and peak RSS ≤ 89 MB. CPU was 0.05–0.16 s per scenario.

**Portal test call (web)**, 4 turns per session, 150 ms per fake model call:

| Scenario | Sessions | Turn p50 / p99 (ms) | VoxAgent's own time p50 / p95 / p99 (ms) | Notes |
|---|---|---|---|---|
| availability | 1 | 312 / 314 | 4.7 / 4.7 / 4.7 | 2 model calls per turn |
| availability | 10 | 322 / 331 | 15.1 / 20.9 / 21.1 | 30.8 turns/s |
| booking | 10 | 172 / 333 | 16.1 / 23.3 / 28.2 | 47.4 turns/s |
| booking, **Sheets 1 s** | 5 | 164 / **1,322** | 8.8 / **1,015** / 1,016 | The reply waits for the Sheets copy |
| model times out (every 3rd call) | 5 | 315 / 322 | 7.4 / 12.4 / 12.4 | 10 degraded replies, 0 errors |

**Focused checks:**

| Check | Result |
|---|---|
| 10 and 50 callers book the **same** slot at once | Exactly **1** confirmed reply and **1** confirmed row both times. The booking invariant holds |
| Two requests on **one** portal session at once (20 runs) | **20/20** interleaved two exchanges; **18/20** separated a tool call from its result |
| Web turn with 20 / 200 / 800 prior turns | Request sent to the model: **13.7k / 84.8k / 324k characters**. Trace size: 9 / 92 / 369 KB. Record + trace rewrite: 0.7 / 1.7 / 5.1 ms per turn |
| Dashboard with 100 / 1,000 / 5,000 calls | Cold 5.6 / 24.6 / 113 ms; warm 0.4 / 3.7 / 22 ms; ETag check 0.01 ms |
| Profile of one web turn with a zero-latency model | 1.3–2.5 ms, almost all `json.dump` + atomic rename of the call record and trace |

---

## 3. Findings (current code, verified)

Ordered by impact on a caller. **P0** means it can freeze or silence calls; **P1** means reliability or capacity under failure; **P2** means growth and efficiency; **P3** means fine for now.

### F1. P0, Measured: the Google Sheets copy runs inside the booking, on the phone event loop
- **Code:** `storage.reserve_booking` (storage.py:408-430) commits to SQLite, then calls `_mirror_to_google_sheet(row)` (storage.py:484-502) **before returning**. On a phone call that runs inside `TwilioBridge.pump_gemini` → `TurnRecorder.tool_calls` → `agent.run_tool` (telephony.py:307), i.e. on the asyncio event loop that carries **every** live call's audio.
- **Measured:**
  - A 1 s Sheets write stalled the loop for 1,002 ms.
  - With 5 concurrent bookings the stalls serialised: TTFA p99 was **5.03 s**, and inbound audio was up to **5.0 s** late for every call.
  - An 8 s stall froze 2 calls for **16 s**.
  - On the web channel, the customer's reply waited about 1 s more per booking.
- **Worse in reality:** gspread 6.2.1 has **no default timeout** (`gspread/http_client.py:84`, `timeout = None`). The first booking also signs in and opens the sheet inline (storage.py:529-541). A stalled Google request blocks with no upper bound.
- **Scope:** only when `SHEET_ID` is configured. It's latent in the default setup.

### F2. P0, Measured: phone and live tool calls run on the event loop
- **Code:** telephony.py:307 (`await self.live.send_tool_results(self.turn.tool_calls(...))`) and live_main.py:88 (the same call). The tool runs synchronously, including the SQLite booking write, whose busy timeout is 10 s (storage.py:217).
- **Measured:** with another writer holding the lock, one booking stalled the loop by **116–134 ms** and made inbound audio **99–124 ms** late for all calls. The worst case is SQLite's 10 s busy timeout.
- Also on the loop: `ReceptionistAgent(client_id)` at call start (telephony.py:471; a SQLite read) and `billing.client_active` / `resolve_client` in the webhook. These are cached or indexed reads of about a millisecond (bench.py), so they're low priority but the same class of issue.

### F3. P0 reliability, Measured: a dropped Live session leaves the caller on a silent line
- **Code:** `GeminiLive.events()` (llm.py:373-398). When the socket closes, google-genai's `_receive` raises `APIError` (google-genai `live.py:555`), which ends `pump_gemini`. `twilio_stream` only awaits `read_twilio()` (telephony.py:484-498), which keeps reading the caller's audio until **they** hang up.
- **Measured:** **5/5** calls ended with the simulated caller hanging up after 3 s of silence. A real caller waits longer, and the business looks broken. This is audit M7, still open.
- **TwiML today** (telephony.py:379-385) is `<Connect><Stream/></Connect>` with nothing after it, so even closing the socket would just hang up. Twilio documents that TwiML after `<Connect>` runs when the stream ends. That's **unverified** here.

### F4. P1, Static: no timeout on opening the Live session
- `await live.connect(...)` (telephony.py:479; llm.py:319-335) has no `wait_for`.
- A hung handshake keeps the caller in silence and holds a concurrent-call slot.
- Whether google-genai's `HttpOptions(timeout=…)` covers the websocket handshake is **unverified**.

### F5. P1, Static: one slow model call holds one of 40 shared worker threads for up to ~75 s
- Every portal endpoint is a sync `def` (server.py), so FastAPI runs it in anyio's worker pool: **40 threads** for all endpoints (anyio 4.15.1 default).
- `GeminiLLM._call_with_retry` (llm.py:246-267) sleeps with `time.sleep` for up to 25 s per retry, three times.
- About 40 slow or rate-limited test calls would make the dashboard, logins and session creation queue behind them.
- Real 429 behaviour is **unverified**.

### F6. P1, Static: speech synthesis has no timeout
- `TTS.synthesize_bytes` (tts.py:59-72) streams from Microsoft's edge-tts service with no deadline.
- A stalled request holds a worker thread indefinitely.

### F7. P1 correctness, Measured: two requests on one portal session corrupt its history
- `run_turn` (server.py:288-300) has no per-session lock. A double-click, a retry or two tabs run `agent.chat` on the same `history` list from two threads.
- **Measured over 20 runs:** 20/20 interleaved, 18/20 broke tool-call/result pairing.
- The broken history is replayed to Gemini on every later turn of that session, and the trace records it.

### F8. P2, Measured: web sessions grow without bounds
- **Per-session growth:**
  - Each turn re-sends the whole history to the model: 324k characters at 800 turns, so cost and latency grow every turn.
  - The record and trace are rewritten after every turn (369 KB at 800 turns).
- **No caps:** there's no limit on turns per session, sessions per business or total sessions.
- **Late cleanup:** idle sessions (2 h) are purged only when a *new* session is created (server.py:281-286, 583).
- Memory per session is small in this test (peak RSS stayed under 104 MB), but nothing bounds it.

### F9. P2, Static: no instrumentation
There are no timings for model requests, tools, database or Sheets, no event-loop lag, no counters for timeouts, cancellations or errors, and no correlation id. Failures are `print()` lines. The problems in F1–F3 would be invisible in production.

### F10. P3, Measured: dashboard and storage scale linearly and are fine at pilot size
- At 5,000 calls a full dashboard refresh costs 22 ms warm and 113 ms cold, and the 20-second ETag poll costs 0.01 ms.
- The booking guard and the cached reads behave as designed.
- **No change proposed.** The plan just monitors it.

### Not a problem (checked)
- **No unnecessary model round trips** in the scripted workload. An availability answer takes 2 calls (tool + reply), a booking 2, small talk 1. Real-model behaviour may differ (**unverified**).
- **Phone overhead without failures is under 3 ms TTFA** at 10 calls. Audio conversion and the bridge are not a bottleneck.
- **The hang-up save** already runs off the loop and can't skip the socket close (review D7/D8).
- **Barge-in** at 10 calls added no stall.

---

## 4. Security and product correctness (Phase 5 review, current code)

| Item | State | Evidence |
|---|---|---|
| Tenant isolation | OK | `authorize_client` (server.py:259-269) checks the user, admin or business code per request; traces have no cross-tenant rows (tests/test_storage.py) |
| Login / code throttling | **Missing** | No limiter anywhere in server.py or auth.py (audit M9) |
| Demo access codes | **Committed** | `clients/*.yaml` `access_key:` (audit M10); rotate before any public repo or server |
| Privacy / retention | **Open** | No retention or delete path for calls, traces, leads or bookings (TODOS) |
| Session resource limits | **Fixed** (bad773e line) | 60 turns, 20 sessions per business, 500 total, idle purge per request, 409 per-session lock (§6) |
| Cost caps | **Partial** | Per session: 60 turns, at most 60 sessions' worth per business, 25 s retry budget. No per-day or per-business model-call budget yet |
| Conversion metric | **Fixed** (7d57cbe) | Call records store `outcome` from the tools' results; `docs/audit_repro.py` R3 now NOT REPRODUCED |
| Single process | Required | Stream tickets use a per-process secret (telephony.py:162); the call counter is in-process |
| Live calls | **Off** | `ENABLE_LIVE_CALLS` gate (telephony.py:93); stays off |

---

## 5. Not verified with real providers

- Real Gemini chat latency, first-token time, rate limits and retry behaviour.
- Gemini Live first-audio latency, session time limits, what happens on a network drop, and whether `HttpOptions.timeout` bounds the websocket handshake.
- Twilio media timing, jitter and buffering, and whether TwiML after `<Connect>` plays when our stream closes. The apology `<Say>` (§6, F3) depends on that; SAFE_TESTING §5 has the check.
- Google Sheets latency and failure modes. Only gspread's lack of a timeout is verified, by reading its code.
- Microsoft edge-tts latency.
- Behaviour on Windows (the `os.replace` retry path) and on a Linux VM.

These are the first things to measure once a real phone pilot runs. The instrumentation for it is now in the code (§6): `/api/admin/perf` and `VOXAGENT_PERF_LOG`.

---

## 6. After the fixes (2026-10-19)

Same machine, same Python (3.13.13), same harness and fake providers as §2. Raw results: [docs/perf/after.json](perf/after.json), from `python bench_load.py --suite full --out docs/perf/after.json` at `bad773e`. Both suites pass: 217 tests on Python 3.11.15 and 3.13.13. `docs/audit_repro.py` shows NOT REPRODUCED for R1–R9.

**These are still fake-provider numbers.** They show that VoxAgent's own stalls are gone. They say nothing about real Gemini, Twilio or Google latency, and they don't establish any real concurrent-call capacity.

### What changed

| Finding | Change | Commit |
|---|---|---|
| F9 no instrumentation | `perf.py` spans, events and gauges; `/api/admin/perf`; opt-in JSONL via `VOXAGENT_PERF_LOG`. One span costs 0.8 µs (bench.py) | 8492dda |
| F1 Sheets inside the booking | Copy queued after COMMIT on a bounded worker (1,000 items; gspread timeout 5/10 s; 3 retries; drop+count+log) | 836cdb7 |
| F2 tools on the loop | Phone tools, agent setup, business checks and the record save run on a dedicated call-I/O pool; hang-up waits ≤15 s for a running booking | 922027a |
| F3, F4 silent line, no connect timeout | The stream ends when either side does; Live connect bounded at 10 s; TwiML apology after `</Connect>` (**unverified**) | 6f0fcb2 |
| F7, F8 double submit, unbounded sessions | Per-session lock (409), caps 60/20/500, idle purge per request | b4574b9 |
| F5, F6 retry and TTS waits | 25 s retry-wait budget per model request; TTS 15 s timeout → 504 | a7c338d |
| Phase 5: conversion | `outcome` stored per call; used for conversion, admin flags and the portal badge | 7d57cbe |
| Regression found and fixed | In-process lock around the booking INSERT (see "Regressions") | bad773e |
| Benchmark safety | `bench.py` now uses temporary storage. It had created an empty `bookings.db` in the repo when none existed | 92b2589 |

### Before and after: the failures

| Scenario | Metric | Before | After |
|---|---|---|---|
| Phone booking, Sheets 1 s, 5 calls | TTFA p99 | 5,030.9 ms | **256.7 ms** |
| | Event-loop lag max | 5,020.9 ms | **2.6 ms** |
| Phone booking, Sheets stalls 8 s, 2 calls | TTFA p99 | 16,008.9 ms | **256.6 ms** |
| | Event-loop lag max | 15,999.5 ms | **1.2 ms** |
| Phone booking, DB write lock held, 5 calls | Event-loop lag max | 134.0 ms | **1.2 ms** |
| | Other calls' inbound audio lateness max | 123.8 ms | **2.2 ms** (from the run in 922027a) |
| | TTFA p99 (this caller waits for the lock) | 389.7 ms | 381.1 ms |
| Live session drops, 5 calls | Callers left on a silent line | **5 / 5** | **0 / 5** (our side hangs up; 5 server hang-ups) |
| Web booking, Sheets 1 s, 5 sessions | VoxAgent's own time p99 | 1,016.1 ms | **11.0 ms** |
| Two requests on one session, 1,000 runs | Runs with a broken history | 18 of 20 (§2 probe) | **0 of 1,000** (1,000 × 200, 1,000 × 409) |
| Web turn with 200 / 800 prior turns | Request sent to the model | 84.8k / 324k chars | Refused politely at the 60-turn cap, no model call. The largest possible request is now turn 60: **28.9k chars** |

The baseline JSON's `web_double_submit` row is a single run that happened to show 0 broken pairs. The 18/20 figure comes from the 20-run probe in §2; the scenario now runs 1,000 times itself.

### Before and after: the healthy paths (regression check)

Target from the plan: within ±10% of baseline.

| Scenario | Metric | Before | After | Change |
|---|---|---|---|---|
| Phone availability, 10 calls | TTFA p99 | 250.8 ms | 260.2 ms | +3.7% |
| Phone booking, 5 calls | TTFA p99 | 251.4 ms | 257.4 ms | +2.4% |
| Phone booking, 10 calls | TTFA p99 | 251.6 ms | 258.4 ms | +2.7% |
| Phone barge-in, 10 calls | TTFA p99 | 251.1 ms | 259.0 ms | +3.1% |
| Web availability, 10 sessions | Own time p99 | 21.1 ms | 22.5 ms | +1.4 ms |
| Web booking, 10 sessions | Own time p99 | 28.2 ms | 19.7 ms | −8.5 ms |
| Booking race, 10 / 50 callers | Confirmed rows for one slot | 1 / 1 | 1 / 1 | invariant holds |
| Dashboard, 5,000 calls | Warm p50 | 22.0 ms | 21.9 ms | — |
| Peak RSS (largest scenario) | | 103.1 MB | 104.0 MB | — |

### Regressions, explained

**Phone TTFA p99 is 0.3–9.4 ms higher on healthy and Sheets-down calls** (+0.1% to +3.7%; the largest is 10 simultaneous availability calls).

*Cause, measured:* tools now run on worker threads instead of the event loop. In the scripted workload, every call books or checks availability at the same instant, so 5–10 tools run at once on 5–10 threads. Their Python work shares one GIL, so each tool's wall time stretches toward the batch's total. In the bench, a booking tool takes 4–6 ms instead of 0.4 ms on the loop. A micro-probe (one tool at a time on a pool thread, with the loop busy with audio) costs 0.1–1.4 ms, so the cost comes from the coincidence of many tools at once, not from the thread itself.

*A second cause, fixed:* simultaneous INSERTs on separate SQLite connections made SQLite's busy handler sleep in millisecond steps (insert max 4–12 ms, TTFA p99 up to 284 ms). A dedicated in-process lock around the single INSERT (bad773e) brought insert max to 1.4–1.7 ms. The UNIQUE index still decides every race, and the booking-race scenario still gives exactly one confirmed row.

*Why it's accepted:* the cost lands only on the callers whose tools are running, and it's a few milliseconds. Before, one slow database or Sheets call froze **every** call's audio for 0.1–16 s. With a real model in the loop (hundreds of milliseconds per reply) a few milliseconds is not expected to be audible, but that's **unverified** until a pilot.

**Nothing else regressed beyond noise.** Web own time moved by −8.5 to +2.9 ms across rows. Dashboard and memory are unchanged.

### Still open

- **Real-provider behaviour (§5).** Nothing here measures it. The pilot should run with `VOXAGENT_PERF_LOG` set and read `call.first_audio`, `call.model_connect`, `model.request` and `loop.lag`.
- **The TwiML apology** plays only if Twilio continues after a stream we close. It's documented by Twilio but unverified (SAFE_TESTING §5).
- **Deferred by decision:** login and code throttling (D1), access-code rotation (D2, by hand), and a retention policy (needs the owner's policy).
- **Capacity claim:** none. One process (SETUP.md "Capacity"). The fake-provider runs went up to 10 calls and 10 sessions without stalls. That's all they show.
