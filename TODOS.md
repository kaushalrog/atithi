# TODOS

## Telephony

### End phone calls cleanly when the model stream fails; keep the event loop non-blocking

**What:** When the Gemini Live stream errors or ends, play a short apology and hang up. Run tool calls (SQLite write, Sheets mirror) off the async event loop.

**Why:** Today a dropped model stream leaves the caller in silence until they hang up (audit M7), and one booking's Sheets network write stalls every other live call (audit M8).

**Context:** `telephony.py` `twilio_stream` starts `pump_gemini` as a task but only awaits `read_twilio()`, so pump exceptions are never observed. `pump_gemini` calls `agent._execute_tool` synchronously. Start with an `asyncio.wait(..., return_when=FIRST_COMPLETED)` over both tasks and `asyncio.to_thread` for tool execution. Must be done before live calls are enabled for a paying client.

**Effort:** M
**Priority:** P2
**Depends on:** Phase 0.5 hardening branch (`harden/phase-0.5`) landing first.

## Security

### Rate-limit credential endpoints

**What:** Per-IP and per-account attempt limits on `/api/auth/login`, `/api/portal/login`, `/api/auth/reset` and the admin key header.

**Why:** Business codes and reset codes carry only 24 bits of entropy, so they're guessable with enough unthrottled requests once the server is public (audit M9).

**Context:** `server.py` `portal_login` / `auth_reset`; `auth.py` `create_reset` (`RS-` + 3 random bytes). A small in-memory sliding-window limiter is enough for a single-process deploy. Consider also lengthening the codes.

**Effort:** S
**Priority:** P2
**Depends on:** None

### Personal-data retention and redaction

**What:** A retention window for call logs, leads and bookings, a per-business delete path, and phone numbers redacted in console logs.

**Why:** Names, phone numbers and caller IDs are stored indefinitely in plain files and printed to the console (audit M11). Any real pilot needs a defined policy, and obligations under India's DPDP Act still need to be assessed.

**Context:** `storage.py` (call logs, leads, bookings DB), `agent.py` booking/lead `print` lines, `telephony.py` caller-ID line in transcripts. The first step is a policy decision by Sai (how long, who can delete); the code follows from that.

**Effort:** M
**Priority:** P2
**Depends on:** Retention policy decision by the owner.

## Metrics

### Compute call metrics from structured history, not transcript substrings

**What:** Derive conversion from confirmed bookings, and record phone/live tool calls in conversation history.

**Why:** The dashboard shows 100% conversion for a call whose booking failed (audit M1) and 0% for real phone bookings, because phone/live channels drop tool calls from history (audit M2).

**Context:** `server.py` `_stats_from` and admin overview use `"book_appointment" in transcript`. `telephony.py` `pump_gemini` and `live_main.py` execute tools without appending them to `agent.history`. This is the same evidence layer the Phase 3 evaluator needs, so design the persisted conversation format once in Phase 2.

**Effort:** M
**Priority:** P2
**Depends on:** Phase 2 architecture decision on the persisted conversation format.

## Completed
