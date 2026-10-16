# Implementation plan: claim-vs-records checker (first release)

**Produced by:** /plan-eng-review on 2026-10-16. Branch: `phase-1/product`. Repo: local-only.

**Reviewed target (fixed):**
- `docs/designs/claim-vs-records-checker.md` (approved design, 2026-10-14)
- `docs/designs/claim-vs-records-ceo-review.md` (CEO review, SCOPE REDUCTION, 2026-10-16)

**Companion:** `docs/ARCHITECTURE.md` (written at the end of this review).

## Original plan (unchanged copy of the reviewed working plan)

From the CEO review's "Approved first-release scope (after D3–D6)":

- **In:**
  - structured traces for every channel (fixes M2), with timestamps and a timezone
  - the neutral trace format plus the VoxAgent mapping
  - records snapshot and records file
  - exact checks 1, 2a, 3 and 6
  - heuristic check 4
  - task outcome
  - the CLI `check`, with JSON run files and `compare`
  - an escaped static HTML report
  - fixtures with recall and false-positive tests
  - phone masking, local-only processing
- **Deferred to TODOS.md:** check 5 (D3), check 2b (D4), the `redact` command (D6). Checks 7–9, SQLite runs, the side-by-side page, the outside adapter and the LLM judge were already post-validation in the design.
- **Trace location (D7):** `calls/<client>/traces/<call_id>.json`, written by `storage.save_call_log` (`log_call_from_agent`).
- **CEO tasks:**
  - T1: history timestamps and timezone
  - T2: phone/live tool calls in history
  - T3: trace file
  - T4: checker core
  - T5: fixtures
  - T6: report and compare
  - T7: docs
  - T8: bench
- **Open for this review:**
  - P-1: pydantic vs dataclasses
  - P-2: package/CLI name
  - P-3: phone `finish()` off the event loop

## Scope Challenge

### A. Assessment

**What already solves each sub-problem:**
- **Structured events, text channels.** `agent.chat` appends assistant `tool_calls` and `{"role":"tool"}` results (agent.py:209-226).
- **Call logging.** Every channel already routes through one function, `storage.log_call_from_agent` (storage.py:566). It's called from:
  - main.py:77, voice_main.py:93, live_main.py:126, telephony.py:328 (once, at the end)
  - server.py:299, after **every** web-test turn with a stable call_id

  So the trace write needs one change point.
- **Tool execution with error capture.** It's duplicated 3 times: agent.py:217-224, telephony.py:302-306, and live_main.py:41-46 (`run_tool`).
- **Records:** `storage.read_bookings`, `booked_pairs` and `read_leads`, all cached.
- **Test fakes:** `FakeLLM` (tests/conftest.py) and `FakeLive` (tests/test_telephony.py:75) already drive the text and phone paths offline.

**Minimum change:** the checker core plus the trace write. Every remaining feature was already cut to its minimum by the CEO review, so no further cuts are proposed.

**Complexity (estimated):**
- Edited: agent.py, telephony.py, live_main.py, storage.py, bench.py, .gitignore, requirements.txt (if P-1), README.md
- New: the checker package, tests (≈ 4 files) and fixtures
- The original arrangement has 8 checker modules. That's ≥ 8 files and ≥ 2 new modules, so the complexity gate trips.

**Search check:** no new infrastructure or concurrency pattern; it's a stdlib CLI plus JSON validation. [Layer 1] Use `argparse`, `json`, `html.escape`, `zoneinfo` and `csv`. No web search was run; this is in-distribution knowledge.

**TODOS cross-reference:**
- "End phone calls cleanly / non-blocking loop" (M7/M8) overlaps P-3.
- "Compute call metrics from structured history" (M1/M2) is half-delivered here: M2 is in, the M1 dashboard is not.
- The 3 CEO deferrals stay deferred.

**Distribution:** a local `python -m` CLI, no packaging (the design defers PyPI). CI needs a remote (founder action), so it's deferred to "NOT in scope" until the remote exists.

### Reality rows

| Premise | Claim | Receipt | Verdict |
|---|---|---|---|
| E1 | All channels log through one function | storage.py:566; callers main.py:77, voice_main.py:93, live_main.py:126, telephony.py:328, server.py:299 | verified |
| E2 | Web test logs after every turn | server.py:299-300 (`call_id=session["call_id"]`) | verified |
| E3 | Phone/live buffer text until turn_complete, but run tools immediately | telephony.py:300-320; live_main.py:95-106 | verified |
| E4 | Phone inserts a fake caller-id user turn | telephony.py:327 | verified |
| E5 | Tool run + error capture is duplicated 3× | agent.py:217-224, telephony.py:302-306, live_main.py:41-46 | verified |
| E6 | pydantic is installed only via FastAPI | requirements.txt (no entry); pydantic 2.14.1 in venv | verified |
| E7 | Outside builders have exportable traces | none | unverified (carried from CEO P7) |

`unverified=1`

```
REALITY: premise-table finding unverified=1 (E7); E3/E4 change the T2 design telephony.py:300
REALITY: already-done pass no checker/trace code on main since 2026-10-14 (main tip 7333c4b) 7333c4b
REALITY: surface-check finding planned CLI name undecided (P-2); existing CLI surface is storage.py main() only storage.py:721
REALITY: binding-decisions pass CEO D2-D7 bind (REDUCTION, cuts, trace location); none reintroduced docs/designs/claim-vs-records-ceo-review.md:104
REALITY: numbers finding all effort numbers [estimated]; bench 0.09/0.09/0.25 ms and 152 tests [measured: AUDIT.md §0, re-measure before gate] docs/AUDIT.md:31
REALITY: deferred-asks pass master brief Phase 3 cases mapped; 3 deferred with answers D3/D4/D6 TODOS.md:1
REALITY: pr-count pass default one PR per wave; single local branch, no remote eeee3d1
```

### B. Complexity gate

No feature cuts are proposed (the CEO review already cut). The structure question compares only the checker's module arrangement.

### Scope record (B)

- **Feature answers:** none proposed (CEO cuts stand).
- **Structure:** B, "Smaller arrangement" (D2, 2026-10-16).
- **Accepted scope:** the checker as 4 modules: `inputs.py` (trace, mapping and records: loading, validation, matching), `checks.py` (checks 1, 2a, 3, 4, 6 and the task outcome), `outputs.py` (text, JSON run, escaped HTML, compare) and `__main__.py` (argparse CLI, exit codes). Same features and tests as the CEO plan.
- **Pending remedies:** P-1, P-2, P-3, F1, F2.

### C. Findings

1. **F1 [P1] (confidence 9/10) telephony.py:300-320, live_main.py:95-106: tool calls land out of order.** Phone and live calls buffer caller and agent text until `turn_complete`, but tools run immediately. The quoted code shows `elif kind == "tool_calls": ... self.agent._execute_tool(...)` runs mid-turn, while `_flush_turn` appends the user and assistant text only at turn end. If T2 appends tool entries when they run, a booking appears *before* the caller's request in history. That breaks check 4's "at or before the claim's turn" window. Also, telephony.py:327 `self.agent.history.insert(0, {"role": "user", "text": f"[caller id: {self.caller}]"})` shifts every turn index and counts as a customer turn (M2). Reviewer: Claude (this review).
2. **F2 [P2] (confidence 9/10) agent.py:217-224, telephony.py:302-306, live_main.py:41-46: duplicated tool runner.** The same "run `_execute_tool`, catch any exception, return `{"error": ...}`" block exists 3 times. T1/T2 would add timestamp and trace recording to each copy, making it 3 places to keep in sync. Reviewer: Claude.
3. **P-1, P-2, P-3** are carried open from the CEO review.

## Decision ledger

### F1: when phone/live tool entries enter history
Finding: F1, P1, confidence 9/10, telephony.py:300-320 / :327, live_main.py:95-106, reviewer Claude
Plan baseline: CEO T2 "phone/live append tool calls and results to history (fixes M2)"; approved by D2–D7 scope (traces fix M2). Ordering mechanism not specified.
Runtime evidence: text buffered until turn_complete; tools executed immediately; caller id inserted as history[0] user turn.
Comparison grid:
Commitment | Source | Current | A Buffer per turn | B Append now, reorder at trace build
Tool entries recorded for phone/live | CEO T2 approved | not recorded | yes | yes
Order in history | pending | n/a | user text → tool calls/results → agent text, flushed together at turn_complete (and at finish) | tool entries first; trace builder reorders by timestamp
Caller id | M2 fix approved | fake user turn at history[0] | moved to call metadata (`caller` field in call log + trace), not history | same
Dashboard turn count | M2 fix approved | inflated by 1 on phone | correct | correct
Tests | required | — | FakeLive turn with tool call → history order asserted; caller id absent from history; turn count | same + reorder unit test
Question D3:
D3 — F1: How should phone and live calls record tool calls in the right order?
Header: Tool order
Options:
A) Buffer per turn (recommended)
Effort S (human ~3h / CC ~15min), risk low. The bridge collects tool calls and results during a turn and appends caller text, then tools, then agent text at turn_complete (and at hang-up). The caller id moves out of history into call metadata. History is correct as written, for every reader.
B) Append now, reorder later
Effort S (human ~3h / CC ~15min), risk medium. Tool entries are appended immediately, and the trace builder reorders by timestamp. History itself stays out of order, so the portal transcript and any other reader see the booking before the request.

State: approved
Actual answer: A "Buffer per turn (recommended)", D3 2026-10-16
Accepted scope: phone (telephony.py) and live (live_main.py) bridges buffer tool calls+results per turn and append user text → tool entries → agent text at turn_complete and at hang-up; caller id moves from history to call metadata (`caller` in call log and trace); tests: FakeLive turn with a tool call asserts history order, caller id absent from history, correct turn count.
History: none

### F2: one shared tool runner
Finding: F2, P2, confidence 9/10, agent.py:217-224, telephony.py:302-306, live_main.py:41-46, reviewer Claude
Plan baseline: CEO T1/T2 add timestamps and tool recording; no extraction approved.
Runtime evidence: 3 verified copies of try `_execute_tool` / except Exception → `{"error": "<Type>: <msg>"}`. Behaviour is identical in all 3 (same error string format).
Comparison grid:
Commitment | Source | Current | A Extract `agent.run_tool` | B Keep 3 copies
Error capture behaviour | existing contract | identical ×3 | unchanged, one place | unchanged ×3
Timestamped tool entries (T1/T2, F1) | approved | — | built once in `run_tool`'s return value; callers append (text) or buffer (phone/live, per F1) | stamping code added to each copy
Lines (implementation) | estimate | ~18 duplicated | remove ~18, add ~12 → net −6 | add ~9 (3 per copy) → net +9
Tests | required | test_agent tool-error test | one shared-contract test (error string, timestamp, entry shape) + existing caller tests | same assertions repeated per caller
Question D4:
D4 — F2: Merge the three copies of the tool-running code into one?
Header: Tool runner
Options:
A) Extract agent.run_tool (recommended)
Effort S (human ~2h / CC ~10min), risk low. One method on ReceptionistAgent runs the tool, captures errors with today's exact message format, and returns the timestamped tool entries; chat appends them, phone/live buffer them (F1). Net about −6 implementation lines; one shared test.
B) Keep three copies
Effort S (human ~2h / CC ~10min), risk medium. Each copy gains its own timestamp and entry-building code. Net about +9 lines, and a later fix must be made in 3 places.

State: approved
Actual answer: A "Extract agent.run_tool (recommended)", D4 2026-10-16
Accepted scope: `ReceptionistAgent.run_tool(call) -> entries` runs `_execute_tool`, captures exceptions with today's exact `{"error": "<Type>: <msg>"}` format, and returns timestamped assistant-tool_call and tool-result entries; agent.chat appends them, telephony.py and live_main.py buffer them per F1; `live_main.run_tool` and the telephony copy are removed; one shared-contract test (error format, timestamp with offset, entry shape) plus existing caller tests stay green.
History: none

### P-1: how the checker validates trace files
Finding: carried from CEO review (P-1), CLAUDE.md "Nothing else unless justified to the owner first"
Plan baseline: design says "validated with pydantic"; CEO left it pending.
Runtime evidence: pydantic 2.14.1 already installed as a FastAPI dependency; requirements.txt has no direct entry.
Comparison grid:
Commitment | Source | Current | A Pin pydantic | B Stdlib dataclasses
Validation errors name the field | approved (clear error) | — | built in ("turns.4.at: ...") | hand-written per field
New install for users | — | — | none for VoxAgent (already present); `pip install pydantic` for outside builders | none
Code size | estimate | — | ~60 lines of models | ~60 lines of dataclasses + ~80 lines of checks
requirements.txt | — | no entry | `pydantic>=2.0` with a comment | unchanged
Question D5:
D5 — P-1: Use pydantic (already installed) to validate trace files?
Header: Validation
Options:
A) Pin pydantic (recommended)
Effort S (human ~1h / CC ~5min), risk low. Add `pydantic>=2.0  # trace validation (already installed via FastAPI)` to requirements.txt. Models give field-named errors for free. Justification for CLAUDE.md: it is already in the environment, so no new install for VoxAgent.
B) Stdlib dataclasses
Effort M (human ~4h / CC ~20min), risk medium. No dependency change; about 80 more lines of hand-written checks to give the same field-named errors, and more places for a validation gap.

State: approved
Actual answer: A "Pin pydantic (recommended)", D5 2026-10-16
Accepted scope: requirements.txt gains `pydantic>=2.0  # trace validation (already installed via FastAPI)`; trace models in the checker's inputs.py; malformed-trace tests assert field-named errors.
History: none

### P-2: package and CLI name
Finding: carried from CEO review (P-2); surface-check row
Plan baseline: the design doc uses a "`voxcheck`-style CLI module runnable with `python -m …`"; no name approved.
Runtime evidence: no existing module named voxcheck/claimcheck in the repo.
Comparison grid:
Commitment | Source | Current | A voxcheck | B claimcheck
Package dir | pending | — | voxcheck/ | claimcheck/
Command | pending | — | python -m voxcheck check … | python -m claimcheck check …
Everything else | approved (D2 structure etc.) | — | unchanged | unchanged
Question D6:
D6 — P-2: What should the checker package and command be called?
Header: Name
Options:
A) voxcheck (recommended)
Effort S (zero difference in work), risk low. `python -m voxcheck check traces/ --records bookings.csv`. Matches the design doc and ties it to the VoxAgent name.
B) claimcheck
Effort S (zero difference in work), risk low. `python -m claimcheck check …`. Describes what it does and reads as platform-neutral for outside builders.

State: approved
Actual answer: A "voxcheck (recommended)", D6 2026-10-16
Accepted scope: package `voxcheck/` (inputs.py, checks.py, outputs.py, __main__.py); command `python -m voxcheck check …` and `python -m voxcheck compare …`.
History: none

### F3: a failure in finish() leaves the phone socket open
Finding: F3, P1, confidence 9/10, telephony.py:504-510, reviewer Claude. The quoted code shows `if bridge is not None: bridge.finish()` with no try/except in the `finally` block, followed by `if ws.client_state == WebSocketState.CONNECTED: ... await ws.close()`. If `finish()` raises (disk full, the test-mode guard, a trace bug), the socket close is skipped. This plan adds more work to `finish()` (a snapshot read and a trace write), so it adds more ways to raise. The bug is pre-existing; this plan widens it.
Plan baseline: design says "a failure to build or write the trace is caught and logged and never raised into the call"; nothing covers a failure of the call-log write itself.
Runtime evidence: static read only; not reproduced.
Comparison grid:
Commitment | Source | Current | A Guard finish | B Leave as is
finish() exception | pending | propagates, skips ws.close | caught, logged with call_sid + exception class; ws.close always runs | propagates
Trace-write failure | approved (never raised) | — | unchanged (caught inside storage) | unchanged
Test | — | none | FakeLive call whose log write raises → socket closed, error logged | none
Question D7:
D7 — F3: Guard the hang-up step so the phone socket always closes?
Header: Hang-up
Options:
A) Guard finish (recommended)
Effort S (human ~1h / CC ~5min), risk low. Wrap `bridge.finish()` in try/except that logs call_sid and exception class, so `ws.close()` always runs. Adds one telephony test where the call-log write raises.
B) Leave as is
Effort S (zero work), risk medium. A logging failure at hang-up can leave a half-open socket (the failure the existing finally block was written to prevent).

State: approved
Actual answer: A "Guard finish (recommended)", D7 2026-10-16
Accepted scope: telephony.py `finally` wraps `bridge.finish()` in try/except that logs call_sid and exception class; `ws.close()` always runs; one telephony test where the call-log write raises asserts the socket closes and the error is logged.
History: none

### P-3: run the hang-up save off the event loop
Finding: carried from CEO review (P-3); telephony.py:504-505; overlaps TODOS "End phone calls cleanly… keep the event loop non-blocking" (M7/M8)
Plan baseline: CEO left it pending; F3 (D7) guards finish().
Runtime evidence: finish() does a cached-JSON rewrite today; this plan adds one indexed SQLite read (bookings_by_client) and one extra file write. storage uses thread-local connections (storage.py:189, :215) and `_write_lock = threading.Lock()` (storage.py:93), so a worker thread is safe. The pump task has ended before finish() runs, so history is not mutated concurrently.
Comparison grid:
Commitment | Source | Current | A Move now | B Leave to TODOS
finish() execution | pending | on the event loop | `await asyncio.to_thread(bridge.finish)` inside D7's guard | on the event loop
Other calls during a hang-up | — | stall for the write's duration (~ms, unmeasured) | not stalled | stall
TODOS M7/M8 item | existing | open | tool execution part stays open; hang-up part done | unchanged
Test | — | — | existing D7 test still passes via to_thread; concurrency not separately tested | none
Question D8:
D8 — P-3: Move the hang-up save onto a worker thread now?
Header: Hang-up save
Options:
A) Move now (recommended)
Effort S (human ~30min / CC ~5min), risk low. One line, `await asyncio.to_thread(bridge.finish)`, inside the D7 guard. Storage is already thread-safe. Other live calls are never stalled by one call's hang-up write.
B) Leave to TODOS
Effort S (zero work now), risk low. Keep it with the existing M7/M8 item. Live calls are off by default, so nothing stalls until phone calls are enabled.

State: approved
Actual answer: A "Move now (recommended)", D8 2026-10-16
Accepted scope: inside D7's guard, `await asyncio.to_thread(bridge.finish)`; TODOS M7/M8 item updated to say the hang-up save is done and tool execution off the loop remains open.
History: none

**Scope Challenge result:** scope accepted as-is. Structure B keeps every feature; it is not a reduction. Accepted remedies: F1 (D3), F2 (D4), P-1 (D5), P-2 (D6), F3 (D7), P-3 (D8).

## Review sections

### 1. Architecture

```
  CHANNELS                          AGENT CORE (agent.py)                  STORAGE (storage.py)
  main.py ─────────┐                ReceptionistAgent                      log_call_from_agent(agent, channel, started,
  voice_main.py ───┤                  .chat()  ── appends ──┐                                  call_id=None, caller=None)  [caller: D3]
  server.py ───────┤ /api/chat        .run_tool(call) ──────┤ NEW (D4)        ├─ calls/<client>/<id>.json   (unchanged shape)
     (every turn)  │                    -> [tool_call entry,│ entries with    └─ calls/<client>/traces/<id>.json  NEW (D7)
  telephony.py ────┤ TwilioBridge       tool result entry]  │ `at` (aware)        trace_version, call meta, turns,
     buffer/turn ──┘ (D3) ──────────► history ◄─────────────┘                     actions, records_snapshot
  live_main.py ──── buffer/turn (D3)                                          snapshot: confirmed bookings on touched
                                                                              dates + caller's leads (cached reads)
  telephony finally: try { await to_thread(bridge.finish) } except: log  (D7, D8)

  VOXCHECK (new, offline, imports nothing from the receptionist)
  python -m voxcheck check <trace files/dirs> [--records file] [--mapping yaml] [--out runs/]
        __main__.py ─► inputs.py ─► checks.py ─► outputs.py ─► stdout summary, runs/<ts>.json, reports/<ts>.html
  python -m voxcheck compare runs/a.json runs/b.json
```

Findings:
- [P3] (confidence 7/10) server.py:299: the web test call rewrites the call log after **every** chat turn (`storage.log_call_from_agent(agent, "web-test", session["started"], call_id=session["call_id"])`). With D7, each turn also does the snapshot read and the trace write before `/api/chat` returns. The cost is one indexed SQLite query plus cached CSV reads plus one small JSON write. It's unmeasured, so T8's bench must measure `log_call_from_agent` with a trace. No remedy needed unless the bench shows more than 5 ms.
- [P2] (confidence 8/10) Distribution: CI can't run until a git remote exists (a founder action). It's deferred to NOT in scope until the remote is created. Locally, `python -m pytest tests -q` is the gate.
- Security: no new HTTP endpoint and no new secret. Traces sit under the gitignored `calls/`. The checker is local. No issues.
- Production failure per new path:
  - trace write fails: caught in storage, call log kept, checker shows "no trace"
  - hang-up save fails: D7 guard logs it and the socket still closes
  - checker gets a bad file: rejected with a field-named error, exit 2

Dispositions: P3 web-turn cost covered by T8 (no new choice); P2 CI deferred (NOT in scope).

### 2. Code quality

- [P2] (confidence 9/10) agent.py:307-357, :358-368: the VoxAgent mapping must express real success rules.
  - `book_appointment` returns `"status": "confirmed"` or `"failed"`.
  - `save_lead` returns `"status": "saved"` or `"failed"`.
  - `check_availability` has no status field (`{"date": date, "available_slots": slots}`).

  The approved `ok_when` "field equality" rule can't express "always ok" for availability. **Repair within the approved contract:** `ok_when` accepts a field-equality string or the literal `always`, still never evaluated code. VoxAgent mapping: `check_availability: {type: availability, ok_when: always}`, `book_appointment: {type: book, ok_when: "result.status == 'confirmed'"}`, `save_lead: {type: lead, ok_when: "result.status == 'saved'"}`. No question needed.
- [P3] (confidence 8/10) agent.py:345-357: book results carry no booking id. VoxAgent matching therefore uses the approved composite key (last 10 phone digits, date, HH:MM). That's correct under the design's matching rule 2. No change.
- Organisation follows D2. `checks.py` gets one section comment per check, and each check is a pure function `(trace, records) -> list[Finding]`. Flag any check over 5 branches at review time.
- No ASCII diagrams exist in agent.py, storage.py, telephony.py or live_main.py today, so none are stale. Add a short ASCII comment above the D3 per-turn buffer in telephony.py showing the flush order.

Dispositions: mapping `always` repair applied (no choice); others need no change.

### 3. Tests

Framework: pytest (CLAUDE.md "Tests: tests/ — pytest, no network/key needed").

```
CODE PATHS                                                      USER FLOWS
[+] agent.py                                                    [+] Builder runs the checker
  ├── run_tool() (D4)                                             ├── [GAP] check on sample traces → findings + exit 1
  │   ├── [GAP] ok result → 2 entries, `at` has offset            ├── [GAP] check on clean traces → exit 0
  │   ├── [GAP] tool raises → {"error": "<Type>: <msg>"} (same     ├── [GAP] malformed file → field-named error, exit 2
  │   │         text as today: test_agent tool-error test ★★)     ├── [GAP] compare two runs → new/fixed/only-in
  │   └── [★★ TESTED] unknown tool → error (test_agent)            └── [GAP] HTML report of adversarial trace is inert
  └── chat() appends run_tool entries [★★★ TESTED existing, extend]
[+] telephony.py                                                [+] Phone call (FakeLive)
  ├── per-turn buffer (D3)                                        ├── [GAP] booking turn → history: user, tool, agent order
  │   ├── [GAP] tool mid-turn → flushed after user text           ├── [GAP] hang-up mid-turn → buffered tool flushed
  │   └── [GAP] hang-up with pending buffer → flushed             └── [GAP] call-log write raises → socket closed, logged (D7)
  ├── caller id → metadata, not history (D3) [GAP]
  └── finally: guarded to_thread(finish) (D7, D8) [GAP]
[+] live_main.py per-turn buffer (D3) [GAP, unit via the same helper]
[+] storage.log_call_from_agent
  ├── [GAP] writes traces/<id>.json with snapshot + trace_version
  ├── [GAP] trace build raises → call JSON still written, error logged
  ├── [GAP] read_call_logs count unchanged with traces/ present (D7)
  └── [GAP] /api/dashboard payload has no trace keys (test_dashboard)
[+] voxcheck/inputs.py   load, size cap, schema, mapping, records, match   [GAP ×7]
[+] voxcheck/checks.py   checks 1, 2a, 3, 4, 6 + outcome                  [GAP, fixture suite]
[+] voxcheck/outputs.py  text, run JSON, HTML escape+CSP, compare          [GAP ×4]
[+] voxcheck/__main__.py exit codes 0/1/2                                  [GAP]

COVERAGE: 2/30 paths tested today (all new code is untested by definition)
QUALITY: ★★★:1 ★★:2  |  GAPS: 28 (0 E2E, 0 eval: no prompt or LLM change)
```

**Required tests** (approved behavior, so no further question; each gets a value card in the Test Plan Artifact):
- `tests/test_agent.py` (extend):
  - run_tool entry shape and offset
  - error text unchanged (**CRITICAL regression**: the model reads this exact text)
- `tests/test_telephony.py` (extend):
  - FakeLive booking turn order
  - hang-up flush
  - no caller id in history
  - turn count
  - D7 socket closes on a log failure
- `tests/test_storage.py` (extend):
  - trace written with snapshot
  - trace failure is non-fatal
  - `read_call_logs` count unchanged
- `tests/test_dashboard.py` (extend): no trace keys in the payload, ETag behaviour unchanged.
- `tests/test_voxcheck.py` (new):
  - loader rejections (bad JSON, naive time, >1 MB, >500 turns)
  - mapping (`always`, equality, unknown tool → other)
  - records (cp1252 CSV, bad row listed)
  - matching (id, composite, changed-after-call, ambiguous)
  - each check on its fault fixture
  - outcome values
  - compare (new/fixed/only-in, version refusal)
  - HTML adversarial is inert
  - exit codes
- `tests/test_voxcheck_fixtures.py` (new):
  - recall ≥ 90% over ≥ 10 fault traces, each check ≥ 1
  - false positives ≤ 1 over ≥ 20 clean traces

**Regression rule:** the tool error text and `transcript_text()` output are existing contracts that the portal and the model read. The CEO approval for T2 covers the phone/live change, and D3/D4 fix the behavior. Required assertions:
- **error text:** byte-identical for the same exception.
- **transcript_text for text channels:** unchanged.
- **transcript_text for phone:** now includes `[tool call]` lines. That's an intentional difference (M2).

**Flakiness:** no `now()` inside voxcheck. Tests pin timestamps via fixtures, and agent tests assert on offset presence, not values.

**Tests made obsolete:** none.

### 4. Performance

- [P3] (confidence 7/10) Web test turn: covered in Section 1 (T8 measures it).
- Snapshot query: `WHERE client_id=? AND date IN (…) AND status='confirmed'` uses `bookings_by_client`. Scale: dates touched per call ≤ 3, rows per business per day ≤ ~40, so it's bounded.
- Checker memory: one trace ≤ 1 MB at a time; records indexed once in a dict keyed by (phone10, date, time). For 10k rows that's a few MB.
- No queries in loops, no unbounded caches. `read_call_logs` cost is unchanged (D7).

Dispositions: no new choices.

### Outside voice

Codex CLI is not installed (`CODEX_MODE: not_installed`). The native fallback needs a background-task wait tool this session doesn't provide, so it took the unavailable path. **No outside coverage**, recorded as `outside_status: unavailable`.

### TODO choices

No new TODO proposals. The existing M7/M8 item was annotated per D8 (the hang-up save is planned in E7; in-call tool execution stays open there).

## Approval readiness

Checked:
- **Scope:** structure B (D2).
- **Remedies:** F1 (D3), F2 (D4), P-1 (D5), P-2 (D6), F3 (D7), P-3 (D8).
- **Repairs of approved contracts, no new behavior:**
  - mapping `ok_when: always`
  - snapshot includes the caller's leads (design R3-1 fix)
  - ASCII comment on the per-turn buffer

Approval readiness: PASS (D2, D3, D4, D5, D6, D7, D8)

## NOT in scope

- **GitHub Actions CI:** needs a git remote, which is a founder action. `python -m pytest tests -q` is the local gate until then.
- **Check 5, check 2b, `redact`:** deferred by the CEO review (D3, D4, D6 there).
- **Checks 7–9, SQLite runs, the side-by-side compare page, the outside adapter, the LLM judge:** after demand validation, per the design.
- **In-call tool execution off the event loop:** stays in TODOS (M7/M8). Only the hang-up save moves (D8).
- **The M1 dashboard conversion fix:** this release produces the structured outcomes it needs; the dashboard change is a separate task (TODOS "Compute call metrics…").

## What already exists

- `storage.log_call_from_agent` (storage.py:566): the single call-logging point for all 6 channels. Reused as the only trace-write site.
- `agent.chat` structured history (agent.py:209-226): reused. `run_tool` replaces its inline tool block (D4).
- Thread-local SQLite connections and `_write_lock` (storage.py:93, :189, :215): what makes D8 safe.
- `storage.read_bookings` / `read_leads` with mtime caching: reused for the snapshot.
- `FakeLLM` (tests/conftest.py) and `FakeLive` (tests/test_telephony.py:75): reused for every new receptionist test. No new fakes.

## Failure modes

| New path | Realistic failure | Test | Handling | User sees |
|---|---|---|---|---|
| run_tool | tool raises | yes (E1) | error dict, unchanged text | model apologises |
| per-turn buffer | hang-up mid-turn | yes (E2) | flushed at finish | nothing |
| trace write | db locked / disk full | yes (E3) | logged, call log kept | checker "skipped: no trace" |
| hang-up save | exception | yes (E7) | logged, socket closes | nothing |
| voxcheck load | malformed file | yes (E4) | field-named error, exit 2 | builder message |
| voxcheck records | bad row | yes (E4) | listed as skipped | builder message |
| voxcheck report | script in transcript | yes (E6) | escaped + CSP | inert text |

**0 critical gaps** (every row has a test and explicit handling).

## Worktree parallelization strategy

| Step | Modules touched | Depends on |
|---|---|---|
| E1 run_tool + timestamps | agent | — |
| E2 phone/live buffer + caller meta | telephony, live_main | E1 |
| E3 trace write + snapshot | storage | E1 |
| E7 hang-up guard + to_thread | telephony | E2 |
| E4 inputs + pydantic pin | voxcheck/, requirements | — |
| E5 checks | voxcheck/ | E4 |
| E6 outputs + CLI | voxcheck/ | E5 |
| E8 fixtures + recall/FP | tests/fixtures, voxcheck tests | E6 |
| E9 bench, README, end-to-end | bench, README | E3, E8 |

- **Lane A** (receptionist): E1 → E2 → E7, and E1 → E3. These are shared modules, so run them sequentially.
- **Lane B** (voxcheck): E4 → E5 → E6 → E8. Independent of Lane A.
- **Execution order:** launch A and B in parallel. Merge both, then E9.
- **Conflict flags:** none across lanes. E2 and E7 both touch telephony.py, so they are sequential in Lane A.

## Implementation Tasks

Synthesized from this review's findings. Each task derives from a specific finding above. Run with Claude Code or Codex; checkbox as you ship. Ratios: features ~30x, tests ~50x.

- [ ] **E1 (P1, human: ~4h / CC: ~15min)**: agent. Add `run_tool` with timestamped entries and the timezone default.
  - Surfaced by: F2 (D4); CEO T1; premise P8
  - Files: agent.py, tests/test_agent.py
  - Verify: `python -m pytest tests/test_agent.py -q`; the error text is byte-identical
- [ ] **E2 (P1, human: ~4h / CC: ~15min)**: telephony/live. Buffer tool entries per turn; move the caller id into metadata.
  - Surfaced by: F1 (D3)
  - Files: telephony.py, live_main.py, storage.py (caller param), tests/test_telephony.py
  - Verify: FakeLive booking turn order; no caller id in history; turn count
- [ ] **E3 (P1, human: ~6h / CC: ~20min)**: storage. Write `calls/<client>/traces/<id>.json` with snapshot (bookings on touched dates plus the caller's leads); failure is non-fatal.
  - Surfaced by: D7 (CEO); Section 1
  - Files: storage.py, tests/test_storage.py, tests/test_dashboard.py
  - Verify: trace written; dashboard has no trace keys; call count unchanged; failure test
- [ ] **E4 (P1, human: ~1d / CC: ~30min)**: voxcheck. `inputs.py` (models, size cap, mapping with `always`, records, matching); pin pydantic.
  - Surfaced by: P-1 (D5), P-2 (D6), Section 2 mapping repair
  - Files: voxcheck/__init__.py, voxcheck/inputs.py, requirements.txt, tests/test_voxcheck.py
  - Verify: loader, mapping and matching tests
- [ ] **E5 (P1, human: ~1d / CC: ~30min)**: voxcheck. `checks.py`: checks 1, 2a, 3, 4, 6 and the task outcome; no clock reads.
  - Surfaced by: approved scope
  - Files: voxcheck/checks.py, tests/test_voxcheck.py
  - Verify: one fault fixture per check is caught; clean fixture silent
- [ ] **E6 (P2, human: ~6h / CC: ~25min)**: voxcheck. `outputs.py` and `__main__.py`: text, run JSON, escaped HTML with CSP, compare, exit codes, phone masking; gitignore `runs/` and `reports/`.
  - Surfaced by: CEO D5; Section 3 (security)
  - Files: voxcheck/outputs.py, voxcheck/__main__.py, .gitignore, tests/test_voxcheck.py
  - Verify: adversarial HTML inert; compare and exit-code tests
- [ ] **E7 (P1, human: ~1h / CC: ~10min)**: telephony. Guard `finish()` and run it via `asyncio.to_thread`.
  - Surfaced by: F3 (D7), P-3 (D8)
  - Files: telephony.py, tests/test_telephony.py
  - Verify: call-log write raises, then the socket closes and the error is logged
- [ ] **E8 (P1, human: ~1d / CC: ~45min)**: fixtures. At least 10 single-fault traces and at least 20 clean ones; recall and false-positive suite.
  - Surfaced by: Success Criteria; Section 3
  - Files: tests/fixtures/voxcheck/, tests/test_voxcheck_fixtures.py
  - Verify: recall ≥ 90%, each check ≥ 1, FP ≤ 1
- [ ] **E9 (P2, human: ~3h / CC: ~15min)**: bench and docs. bench.py measures `run_tool` and `log_call_from_agent` with a trace; README quick start; end-to-end portal test call to trace to voxcheck.
  - Surfaced by: Section 1/4 P3 (web turn cost); CEO T7, T8
  - Files: bench.py, README.md
  - Verify: `python bench.py` (web-turn log under 5 ms); a fresh clone reaches a report in ≤ 10 min

## Unresolved decisions

None in this review.

## Completion summary

- **Step 0, Scope Challenge:** scope accepted as-is (structure B, D2).
- **Reality rows:** 7/7 applicable rows emitted (`PLAN_REALITY: phase=eng rows=7/7 missing=none unverified=1 verdict=complete`), 1 unverified premise (E7).
- **Architecture Review:** 2 issues found.
- **Code Quality Review:** 2 issues found.
- **Test Review:** diagram produced, 28 gaps identified (all new code; required tests listed).
- **Performance Review:** 0 new issues (1 cross-reference to Architecture).
- **NOT in scope:** written. **What already exists:** written.
- **TODOS.md updates:** 0 new items proposed (1 existing item annotated per D8).
- **Failure modes:** 0 critical gaps flagged.
- **Unresolved decisions:** 0 in this review.
- **Outside voice:** codex, unavailable (CLI not installed; native fallback unavailable in this session).
- **Parallelization:** 2 lanes, 2 parallel / 1 sequential merge step (E9).
- **Lake Score:** 2/2 (D7 and D8 were coverage-scored; both picked the 10/10 option).

## CEO re-review (2026-10-17)

/plan-ceo-review, run again at the founder's request (eng-review D9). The working plan is this file, and the reviewed inputs are unchanged since the eng review (`4970b4a`). Depth: strategy and scope. The eng review already settled the implementation design.

### Pre-review audit

- Since the first CEO review (`860f438`), only docs have changed: the routing rules in CLAUDE.md (`5e74e56`) and the eng-review docs (`4970b4a`). No code changed, there are no stashes, and `AGENTS.md` is still untracked (not ours).
- **Active decisions honoured, none reopened:**
  - CEO REDUCTION (check 5, 2b and redact deferred; compare kept; traces subfolder)
  - eng D2–D8 (4 modules, run_tool, per-turn buffer, guarded off-loop finish, pydantic, voxcheck)
- **Landscape:** reused the 2026-10-14 searches (3 days old, `docs/COMPETITIVE_ANALYSIS.md`). No new search was run; nothing in scope depends on fresher market data.

### 0A. Premise challenge (what changed since the first CEO review)

- **The plan now costs about 5 human-days / about 4 CC-hours (E1–E9).** That's ~19 changed files, including 6 test files and a fixture folder.
- **The demand clock has no real dates.**
  - The design says "Day 1: send the Assignment messages before writing checker code" (design doc, Sequencing step 1). Day 3 means 10 builders contacted; day 10 is the checkpoint.
  - None of these days is anchored to a calendar date.
  - The design was approved on 2026-10-14. If that was day 1, day 3 (2026-10-16) has already passed.
  - Nothing in the repo shows whether any message was sent. That is the founder's action, and I can't see it.
- **The two lanes have different value:**
  - **Lane A** (E1, E2, E3, E7: receptionist traces, the M2 fix, the hang-up guard) pays off whether or not demand exists.
  - **Lane B** (E4, E5, E6, E8: the voxcheck checker) is the speculative bet. The design gates it behind the outreach.
- **Do-nothing cost:** building Lane B before any builder has been asked risks exactly the "solution in search of a problem" pattern that office hours warned about. Waiting to build Lane A only delays the M2 fix.

### 0B. Existing code leverage

No change from the eng review's "What already exists" (storage.py:566 single logging point, agent.py:209-226 history, FakeLLM/FakeLive). Reality rows:

| Premise | Claim | Receipt | Verdict |
|---|---|---|---|
| C1 | Sequencing requires outreach before checker code | docs/designs/claim-vs-records-checker.md "Sequencing" step 1 | verified |
| C2 | Day 1 is not anchored to a date | same section; design header "Generated … on 2026-10-14" | verified |
| C3 | Outreach has been sent | none in repo | unverified (founder action) |
| C4 | Lane A pays off independent of demand | audit M2 (docs/AUDIT.md:178); TODOS "Compute call metrics…" | verified |

`unverified=1`

```
REALITY: premise-table finding unverified=1 (C3 outreach sent?); demand clock not dated docs/designs/claim-vs-records-checker.md:164
REALITY: already-done pass no code since 7333c4b; only docs commits 5e74e56 4970b4a 4970b4a
REALITY: surface-check pass voxcheck CLI is planned, not existing; storage.py main() unchanged storage.py:721
REALITY: binding-decisions pass CEO D2-D7 and eng D2-D8 honoured; none reintroduced docs/IMPLEMENTATION_PLAN.md:114
REALITY: numbers finding E1-E9 effort ~5 human-days / ~4 CC-hours [estimated]; 19 files [estimated] docs/IMPLEMENTATION_PLAN.md:420
REALITY: deferred-asks pass deferrals unchanged (TODOS) TODOS.md:1
REALITY: pr-count pass one local branch, no remote 4970b4a
```

### 0C. Dream state

Unchanged from the first CEO review. This plan moves toward it **if** Lane B is built against real builder answers rather than in a vacuum.

### 0D. Approach

The approach is settled (office-hours D3, CEO D2–D7, eng D2–D8). No new approach decision is needed.

### Decision ledger (re-review)

| ID and owner | Contract and evidence | Current | Proposed | Status | Exact approval and scope |
|---|---|---|---|---|---|
| MODE2 (Sai) | 0E | none | SCOPE REDUCTION | approved | D1 answer 2026-10-17: "SCOPE REDUCTION (recommended)"; mode only |
| CUT-B Lane B timing (Sai) | design Sequencing step 1 (outreach before checker code); C3 unverified | Lane B gated on outreach (TODOS.md) | — | deferred | D2 answer 2026-10-17: "Defer to TODOS.md (recommended)"; Lane B (E4, E5, E6, E8) starts when the founder confirms the Assignment messages were sent; Lane A and its approvals unchanged; E9 splits (bench with Lane A, README/end-to-end after Lane B) |

#### Answered: CUT-B (D2)
Commitment comparison:
Commitment | Source/approval or pending | Current | A Defer | B Keep
Lane A (E1, E2, E3, E7) | eng D3, D4, D7, D8 | build now | build now (unchanged) | build now
Lane B (E4, E5, E6, E8) | eng D2, D5, D6 | build now | starts once the founder confirms the Assignment messages went out; TODOS entry with that trigger | build now
E9 (bench, README, end-to-end) | eng plan | after both lanes | bench part with Lane A; README/end-to-end after Lane B | after both lanes
Design approvals for Lane B | eng D2–D6 | approved | still approved, only timing changes | approved

Question: D2 — CUT-B: Should the checker lane wait until the builder messages are sent?
Header: Checker timing
A) Defer to TODOS.md (recommended)
Effort S (zero implementation now), risk low. Build Lane A now. Lane B (voxcheck: E4, E5, E6, E8) starts the day you confirm the 10 Assignment messages went out, as your own design's Sequencing step 1 says. Its design stays approved; only the start is gated.
B) Keep it in scope
Effort L, risk medium. Build both lanes now. Pros: the checker exists sooner and can be shown to the first builder who replies. Con: about 3 days of human-equivalent work before anyone has answered the one question.

### Review sections (re-review)

**Current scope:**
- Mode: SCOPE REDUCTION (D1).
- Lane A approved and built now: E1, E2, E3, E7, plus E9's bench part.
- Lane B deferred until outreach (D2): E4, E5, E6, E8, plus E9's README/end-to-end part.
- Prior approvals unchanged: CEO D2–D7, eng D2–D8.

#### Section 1: Architecture

Unchanged from the eng review (see Review sections §1 above). Gating Lane B creates no coupling problem, because Lane A has no dependency on voxcheck: traces are just files until Lane B reads them.

- **[P2] (confidence 9/10) Strategy: the demand clock has no dates** (design Sequencing; PRODUCT.md "Demand test and kill rule"). The kill rule can't fire on "day 10" if day 1 is undefined.

#### Answered: CLOCK (D3)
Commitment comparison:
Commitment | Source/approval or pending | Current | A Clock starts at send | B Clock started at approval
Day 1 | design Sequencing (undated) | undefined | the date the founder confirms the 10 messages were sent (same event that unlocks Lane B, D2) | 2026-10-14 (design approval)
Day 3 / 10 / 14 / 17 / 21 / 28 | design Success Criteria | relative, undated | relative to that send date; written into PRODUCT.md and the design when it happens | 2026-10-16 / -23 / -27 / -30 / 11-03 / 11-10
Outreach before checker code | design Sequencing step 1; D2 | gated | unchanged | unchanged
Kill-rule branches | approved | unchanged | unchanged | unchanged

Question: D3 — CLOCK: When does day 1 of the demand test start?
Header: Day 1
A) The day messages are sent (recommended)
Effort S (doc edit only), risk low. Day 1 = the date you confirm the 10 Assignment messages went out; I write the real dates for day 3, 10, 14 and the extensions into PRODUCT.md and the design that day. Matches D2: one event starts both the clock and Lane B.
B) Already started on 2026-10-14
Effort S (doc edit only), risk medium. Day 1 = design approval date: day 3 was 2026-10-16 (already missed), day 10 is 2026-10-23. Keeps pressure high, but the first deadline is already blown.


CLOCK answer: D3 2026-10-17, "The day messages are sent (recommended)". Day 1 is the date the founder confirms the 10 Assignment messages were sent. That same event unlocks Lane B (D2). Real dates for days 3, 10 and 14 and the extension windows are written into PRODUCT.md and the design doc on that day. PRODUCT.md is amended now to state the rule.

#### Sections 2–10 (re-review)

- **2. Error & rescue:** unchanged from the eng review's Failure modes table. Lane A's rows (run_tool, per-turn buffer, trace write, hang-up save) all have tests and handling. Lane B's rows move with Lane B. No new gaps.
- **3. Security:** no new surface. Lane A adds trace files under the gitignored `calls/`, and phones in traces are the business's own data (the existing M11 retention TODO applies). No issues found.
- **4. Data flow & edge cases:** a new edge from D2. Lane A ships traces before any reader exists, so **trace_version 1 is frozen before voxcheck is written**. A field voxcheck later needs would force a version bump. Mitigation: the trace schema is already fully specified in docs/ARCHITECTURE.md §3, and Lane B must read v1 as written. No new choice is needed.
- **5. Code quality:** no change (eng D2–D4 govern).
- **6. Tests:** Lane A's required tests are unchanged (eng §3: test_agent, test_telephony, test_storage, test_dashboard). Without voxcheck, the end-to-end proof for Lane A becomes "a FakeLive phone booking writes a trace whose actions and snapshot match the booking". That's already a listed critical path in the test plan artifact. No gap.
- **7. Performance:** E9's bench part ships with Lane A (`run_tool`, `log_call_from_agent` with a trace, under 5 ms). No change.
- **8. Observability:** Lane A logs trace-write and hang-up failures with call id and exception class. **Observable success:** the count of trace files equals the call count for new calls. Spot-check it during Lane A QA. No new gaps.
- **9. Deployment:** local only. Lane A lands as its own commit series on a branch from `phase-1/product`, and Lane B later on another. Rollback is a revert. No change.
- **10. Long-term trajectory:** reversibility 5/5. The new debt item is the schema freeze above (documented). D3 ties the product timeline to a real event.
- **11. Design:** SKIPPED (no UI scope).

**Outside voice:** Codex not installed; native fallback unavailable in this session. Coverage unavailable.

**Remaining TODO choices:** none. The D2 Lane B gate is already in TODOS.md.

Approval readiness: PASS (re-review: MODE2 D1, CUT-B D2, CLOCK D3; prior: CEO D2–D7, eng D2–D8)

#### Re-review completion summary

```
  +====================================================================+
  |            MEGA PLAN REVIEW — COMPLETION SUMMARY (re-review)       |
  +====================================================================+
  | Mode selected        | SCOPE REDUCTION                             |
  | System Audit         | docs-only changes since first CEO review;   |
  |                      | demand clock undated; outreach unverified   |
  | Step 0               | Lane B gated on outreach (D2)               |
  | Section 1  (Arch)    | 1 issue found (CLOCK, decided D3)           |
  | Section 2  (Errors)  | 0 new paths, 0 GAPS                         |
  | Section 3  (Security)| 0 issues found                              |
  | Section 4  (Data/UX) | 1 edge mapped (schema freeze), 0 unhandled  |
  | Section 5  (Quality) | 0 issues found                              |
  | Section 6  (Tests)   | Lane A diagram reused, 0 gaps               |
  | Section 7  (Perf)    | 0 issues found                              |
  | Section 8  (Observ)  | 0 gaps found                                |
  | Section 9  (Deploy)  | 0 risks flagged                             |
  | Section 10 (Future)  | Reversibility: 5/5, debt items: 1           |
  | Section 11 (Design)  | SKIPPED (no UI scope)                       |
  +--------------------------------------------------------------------+
  | NOT in scope         | Lane B until outreach (D2)                  |
  | What already exists  | unchanged (eng review)                      |
  | Dream state delta    | unchanged; Lane B now tied to builder input |
  | Error/rescue registry| Lane A: 4 rows, 0 CRITICAL GAPS             |
  | Failure modes        | 7 total (eng), 0 CRITICAL GAPS              |
  | TODOS.md updates     | 1 item (Lane B gate)                        |
  | Scope proposals      | 0 proposed, 0 accepted (REDUCTION)          |
  | CEO plan             | skipped by mode                             |
  | Outside voice        | codex: unavailable (not installed)          |
  | Lake Score           | N/A (no coverage-scored questions)          |
  | Diagrams produced    | 0 new (eng diagrams still accurate)         |
  | Stale diagrams found | 0                                           |
  | Unresolved decisions | 0                                           |
  | Reality rows         | 7/7 rows, 1 unverified (C3)                 |
  +====================================================================+
```

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 2 | ISSUES OPEN | mode: SCOPE_REDUCTION, 0 critical gaps (re-review: Lane B gated on outreach, demand clock dated) |
| Outside Review | codex (auto, plan-review) | Independent 2nd opinion | 3 | unavailable | Codex not installed; no completed external review |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 1 | ISSUES OPEN | 32 issues, 0 critical gaps |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | — | — |
| DX Review | `/plan-devex-review` | Developer experience gaps | 0 | — | — |

- **OUTSIDE COVERAGE:** codex, plan-review (CEO ×2, Eng ×1), unavailable every time (CLI not installed; native fallback unavailable). No findings.
- **VERDICT:** no review CLEAR. The CEO re-review has 0 unresolved decisions and 0 critical gaps. Its status is ISSUES OPEN only because of mapped work: Lane B is deferred until outreach, and the clock is dated on send. Eng status ISSUES OPEN is the mapped E1–E9 work (28 test gaps for unwritten code) with 0 unresolved decisions. The first CEO review's 3 logged open items were decided in the eng review (D5, D6, D8). Lane A (E1, E2, E3, E7, plus the E9 bench part) is ready to implement. Lane B waits for outreach. Eng review required.

NO UNRESOLVED DECISIONS
