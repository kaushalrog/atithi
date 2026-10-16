# TODOS

## Telephony

### End phone calls cleanly when the model stream fails; keep the event loop non-blocking

**What:** When the Gemini Live stream errors or ends, play a short apology and hang up. Run tool calls (SQLite write, Sheets mirror) off the async event loop.

**Why:** Today a dropped model stream leaves the caller in silence until they hang up (audit M7), and one booking's Sheets network write stalls every other live call (audit M8).

**Context:** `telephony.py` `twilio_stream` starts `pump_gemini` as a task but only awaits `read_twilio()`, so pump exceptions are never observed. `pump_gemini` calls `agent._execute_tool` synchronously. (Update 2026-10-16, eng review D8: the hang-up save is planned to move to `asyncio.to_thread` inside a guard, task E7 in docs/IMPLEMENTATION_PLAN.md, not yet built. Tool execution during the call stays on the loop and stays open here.) Start with an `asyncio.wait(..., return_when=FIRST_COMPLETED)` over both tasks and `asyncio.to_thread` for tool execution. Must be done before live calls are enabled for a paying client.

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

## Claim-vs-records checker (deferred by /plan-ceo-review, 2026-10-15)

### Check 5: spoken time differs from the booking

**What:** A heuristic check that normalises spoken dates and times ("4 PM", "tomorrow", "next Monday") against the call's `started_at` and timezone, and flags a confirmed booking whose spoken time differs from the `book` action's args.

**Why:** It catches "booked you at 4" when the record says 14:00. It was deferred because it's the noisiest check and there are no real logs to tune it on (CEO review D3).

**Context:** `docs/designs/claim-vs-records-checker.md` (Checks §5). Build it after the day-10 demand checkpoint. Use real builder or VoxAgent traces as tuning fixtures. Its recall fixture returns with it.

**Effort:** M
**Priority:** P2
**Depends on:** The first checker release; real traces to tune on.

### Check 2b: spoken slot offer never returned by availability

**What:** A heuristic sub-check that flags a spoken offer of a date/time no `availability` result contained, even when nothing was booked.

**Why:** It catches hallucinated availability the caller declined. Deferred with check 5 because it needs the same normaliser (CEO review D4). Check 2a still catches bookings on unavailable slots.

**Context:** design doc Checks §2b. Build it right after check 5 and reuse its normaliser.

**Effort:** S
**Priority:** P3
**Depends on:** Check 5's normaliser.

### `redact` command for shared logs

**What:** Replace caller names with tokens and phones with a keyed hash. Normalise phones to the last 10 digits before hashing, use one key across the trace and records files, and scrub names and phones inside turn text.

**Why:** It's needed only if builders want to send logs instead of running the checker locally (CEO review D6). It could later serve VoxAgent's own retention work (Security: personal-data retention).

**Context:** design doc "Input safety and personal data" plus review concern R3-11. Build it only when a builder asks to share data.

**Effort:** M
**Priority:** P3
**Depends on:** A builder request.

## voxcheck build gate (CEO re-review D2, 2026-10-17)

### Build voxcheck (Lane B: E4, E5, E6, E8) once outreach is sent

**What:** Implement the voxcheck checker exactly as approved in `docs/IMPLEMENTATION_PLAN.md` (eng review D2, D5, D6): `inputs.py`, `checks.py`, `outputs.py`, `__main__.py`, the fixtures, and the recall and false-positive suite.

**Why:** The design's Sequencing step 1 puts outreach before checker code. The checker is the speculative half of the bet, and builder answers should shape it. Lane A (receptionist traces, M2) is built regardless.

**Context:** The design is fully approved; only the start is gated. **Trigger:** the founder confirms the 10 Assignment messages were sent. Then E9's README and end-to-end parts follow.

**Effort:** L (human ~3 days / CC ~2.5 hrs)
**Priority:** P1 once triggered
**Depends on:** Founder sends the Assignment messages; Lane A landed (E1, E3 provide real traces).
