# Architecture: receptionist plus claim-vs-records checker

**Status:** planned. Nothing in the "new" boxes exists yet.
**Decided in:**
- `/plan-eng-review` on 2026-10-16 (decisions D2–D8 in `docs/IMPLEMENTATION_PLAN.md`)
- the CEO review (`docs/designs/claim-vs-records-ceo-review.md`)
- the approved design (`docs/designs/claim-vs-records-checker.md`)

## 1. The two halves

VoxAgent is now two programs that share one file format:

1. **The receptionist** (existing). It talks to callers and books appointments. New in this release: it writes one **trace** per call, a structured record of what was said, which tools ran and what they returned, plus the relevant booking rows at the moment the call ended.
2. **voxcheck** (new). It's an offline command that reads traces and a business's records, and lists every claim the records don't back up, each with its evidence.

**The dependency goes one way.** voxcheck reads JSON files and imports nothing from the receptionist. *Why:* the same checker must work on another platform's exported calls, and CLAUDE.md principle 6 keeps provider code out of everything except `llm.py`.

```
  CHANNELS                          AGENT CORE (agent.py)                  STORAGE (storage.py)
  main.py ─────────┐                ReceptionistAgent                      log_call_from_agent(...)
  voice_main.py ───┤                  .chat()  ── appends ──┐                ├─ calls/<client>/<id>.json         (unchanged)
  server.py ───────┤ /api/chat        .run_tool(call) ──────┤ timestamped    └─ calls/<client>/traces/<id>.json  NEW
  telephony.py ────┤ phone (buffers   -> [tool_call entry,  │ entries
  live_main.py ────┘  per turn)          tool result entry] ┘ ► history

  VOXCHECK (new, offline)
  python -m voxcheck check <traces> [--records FILE] [--mapping YAML] [--out runs/]
      __main__.py ─► inputs.py ─► checks.py ─► outputs.py ─► summary, runs/<ts>.json, reports/<ts>.html
  python -m voxcheck compare runs/a.json runs/b.json
```

## 2. Receptionist changes

| Change | Where | Why |
|---|---|---|
| `ReceptionistAgent.run_tool(call)` runs a tool, catches any exception with today's exact error text, and returns two timestamped history entries (tool call, tool result) | agent.py | The same 6 lines existed in 3 places (agent.py, telephony.py, live_main.py). Timestamps must be identical on every channel (D4). |
| Phone and live calls collect tool entries during a turn and append them **between** the caller's words and the agent's reply, at the end of the turn and at hang-up | telephony.py, live_main.py | Speech is buffered until the turn ends, but tools run mid-turn. Appending immediately would put the booking before the request (D3). |
| The caller's number moves from a fake `[caller id: …]` customer line into call metadata | telephony.py, storage.py | It was counted as a customer turn and shifted every turn index (audit M2). |
| Every timestamp in a trace is timezone-aware. The default is `Asia/Kolkata`; a client YAML may set `timezone:` | agent.py, client YAML | "Tomorrow at 4" can't be checked without knowing whose tomorrow. VoxAgent had no timezone at all. |
| `log_call_from_agent` also writes `calls/<client>/traces/<call_id>.json` | storage.py | The dashboard sends whole call files to the browser, and `read_call_logs` counts every `*.json` in the folder as a call, so traces live in a subfolder (D7). |
| The phone hang-up save runs in a worker thread, inside a try/except that always lets the socket close | telephony.py | A save failure used to skip `ws.close()`, and the save blocked every other live call (D7, D8). Storage is already thread-safe. |
| `pydantic>=2.0` is pinned in requirements.txt | requirements.txt | It's already installed via FastAPI and gives field-named validation errors for free (D5). |

**Trace failures never hurt a call.** Building or writing the trace is wrapped so that an error is logged with the call id and the normal call log is still written. The checker then reports that call as `skipped: no trace`, never as clean.

## 3. The trace format (version 1)

```json
{
  "trace_version": 1,
  "call_id": "20261016_101500_phone",
  "client_id": "sunrise_dental",
  "channel": "phone",
  "caller": "+9198xxxx1234",
  "started_at": "2026-10-16T10:15:00+05:30",
  "ended_at":   "2026-10-16T10:18:42+05:30",
  "timezone": "Asia/Kolkata",
  "turns":   [{"index": 0, "speaker": "caller", "text": "...", "at": "..."}],
  "actions": [{"turn_index": 1, "at": "...", "type": "book", "name": "book_appointment",
               "args": {...}, "ok": true, "result": {...}}],
  "records_as_of": "2026-10-16T10:18:42+05:30",
  "records_snapshot": [{"phone": "...", "name": "...", "date": "...", "time": "...",
                        "service": "...", "status": "confirmed"}]
}
```

- `type` is one of `availability`, `book`, `lead` or `other`. Checks reason only about types, never tool names.
- **Mapping** (YAML, per source): tool name → type, plus `ok_when`. `ok_when` is either the word `always` or a field-equality string like `result.status == 'confirmed'`. It is parsed, never evaluated as code.

  VoxAgent's built-in mapping:

  ```yaml
  check_availability: {type: availability, ok_when: always}
  book_appointment:   {type: book, ok_when: "result.status == 'confirmed'"}
  save_lead:          {type: lead, ok_when: "result.status == 'saved'"}
  ```
- **Snapshot:** every confirmed booking for that business on each date the call touched, plus the caller's leads, as of call end.
- **Limits:** ≤ 1 MB per file and ≤ 500 turns, checked before parsing.

## 4. voxcheck modules (D2: four files)

| File | Job |
|---|---|
| `voxcheck/inputs.py` | Load and validate traces (pydantic models), load the mapping (`yaml.safe_load`), load records (CSV or JSON, utf-8-sig or cp1252), normalise phones/dates/times, match an action to a record (booking id, else last-10-digits + date + HH:MM, else `unverifiable: changed after call`, else `record missing`; more than one match is `ambiguous`). |
| `voxcheck/checks.py` | Five pure functions, `(trace, records) -> list[Finding]`, plus `task_outcome(trace, records)`. They never read the clock: all time comes from the trace. |
| `voxcheck/outputs.py` | Text summary, run JSON (with checker version), HTML report (every string via `html.escape`, no external assets, restrictive CSP), and `compare` (new / fixed / unchanged / only-in-A / only-in-B; it refuses runs from different checker versions). |
| `voxcheck/__main__.py` | argparse CLI. Exit codes: 0 = ran with no findings, 1 = findings, 2 = some input was rejected. Phones are masked to the last 4 digits in every output. |

**First-release checks:**

| # | Check | Kind | Catches |
|---|---|---|---|
| 1 | Record mismatch: a successful book/lead whose record is missing or differs | exact | silent write failures |
| 2a | Booked a slot no availability result contained, or one already confirmed for someone else | exact | audit R2 |
| 3 | Two confirmed rows for one slot (whole records file) | exact | audit R1 (regression guard; the database now prevents it) |
| 4 | Agent says "you're booked" with no successful book action at or before that turn | heuristic (English phrases) | audit R4 |
| 6 | Intent shown but no successful booking or lead, or a required field missing | exact | incomplete calls |

Deferred (TODOS.md): check 5 (spoken time differs), check 2b (spoken slot offer) and `redact`. Checks 7–9, the adapter and the LLM judge come after demand is validated.

## 5. Failure handling

| Where | What goes wrong | What happens | Who sees it |
|---|---|---|---|
| Trace write at call end | Snapshot query, serialisation or disk error | Logged with call id and class; call log still written | Caller: nothing. Owner: call shown. Checker: "skipped: no trace" |
| Phone hang-up save | Any exception | Logged with call_sid and class; socket always closes | Nothing visible to the caller |
| Tool during a call | Any exception | `{"error": "<Type>: <msg>"}` back to the model (unchanged text) | The model apologises and offers a callback |
| voxcheck input | Bad JSON, schema, size, naive timestamp | That file is rejected with a field-named error; exit 2 | Builder |
| voxcheck records | Bad row | Row skipped and listed in the summary | Builder |
| voxcheck compare | Different checker versions or call sets | Refuses, or lists "only in A/B" | Builder |

## 6. What stays the same

- Booking safety: SQLite with the one-confirmed-booking-per-slot index; the Sheets copy is unchanged.
- The dashboard payload, ETag behaviour and call counts.
- The receptionist's prompt and tools. There's no LLM change, so no eval re-run is needed.
- Live phone calls stay off unless `ENABLE_LIVE_CALLS=true`.
