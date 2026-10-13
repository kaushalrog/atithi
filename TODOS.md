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

## Cost control

### Per-session budgets for test calls

**What:** Cap each portal test-call session: number/characters of `/api/tts` syntheses, number of chat turns, and enforce the 2-hour idle limit inside `get_session` (today it's only purged when a new session is created).

**Why:** Found in the Phase 0.5 review (Red Team + adversarial): a session holder can make unlimited 1000-char TTS calls, and each chat turn re-sends the whole history, so one session's model cost keeps growing. Anyone can sign up and get a session.

**Context:** `server.py` `create_session`, `get_session`, `/api/tts`, `/api/chat`. Needs a product decision on the limits (what a fair demo costs). Pair with the credential rate limits above.

**Effort:** S
**Priority:** P2
**Depends on:** Decision on per-session limits.

## Dashboard

### Change detection that doesn't rely on file timestamps

**What:** Replace the dashboard ETag's file stamps for bookings (`bookings.db` / `-wal` mtime+size) with a database-side change counter (e.g. a `meta` row bumped on every write, or `PRAGMA data_version`).

**Why:** Found in the Phase 0.5 adversarial review: when another process (e.g. `main.py`) books, the server only notices via the WAL file's timestamp. On a filesystem with coarse timestamps, the WAL's size can stay the same and the dashboard could return a stale 304 until the next change. The server's own writes are unaffected.

**Context:** `storage.py` `data_version`. Low urgency for a single laptop/VM (APFS/ext4 have fine timestamps).

**Effort:** S
**Priority:** P3
**Depends on:** None

## Metrics

### Compute call metrics from structured history, not transcript substrings

**What:** Derive conversion from confirmed bookings, and record phone/live tool calls in conversation history.

**Why:** The dashboard shows 100% conversion for a call whose booking failed (audit M1) and 0% for real phone bookings, because phone/live channels drop tool calls from history (audit M2).

**Context:** `server.py` `_stats_from` and admin overview use `"book_appointment" in transcript`. `telephony.py` `pump_gemini` and `live_main.py` execute tools without appending them to `agent.history`. This is the same evidence layer the Phase 3 evaluator needs, so design the persisted conversation format once in Phase 2.

**Effort:** M
**Priority:** P2
**Depends on:** Phase 2 architecture decision on the persisted conversation format.

## Completed
