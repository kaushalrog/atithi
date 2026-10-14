# Phase 0.5 — Security and correctness hardening plan

Branch: `harden/phase-0.5` · Baseline: `ab8abbc` (58 tests pass; R1–R9 reproduce, see `docs/AUDIT.md`)
Scope: fix audit findings **H1, H2, H3**, then the high-confidence exposure items. **No new product features.**

## Fix 1 — H1: authorise phone media connections

Call lifecycle today: Twilio → `POST /twilio/voice` (signature checked **only if** a token is set) → TwiML `<Stream>` → `wss /twilio/stream` (**no check at all**) → trusts `customParameters.client_id` → builds agent + Gemini Live session.

Design (defence in depth, everything checked **before** an agent or a Gemini session is allocated):

1. **Live calling is off unless explicitly enabled.** New `ENABLE_LIVE_CALLS=true` in `.env`. Without it, `/twilio/voice` returns 503, `/twilio/stream` closes with 1008, outbound calls refuse, and `go_live.py` refuses to start. Fail closed.
2. **Webhook signature is mandatory.** `_validate_signature` no longer returns `True` when the token is missing; it returns 503 (not configured). The "local mode" branch is removed.
3. **One-time stream token.** `/twilio/voice` mints `token = HMAC-SHA256(secret, call_sid|client_id|caller|expires)` (secret derived from `TWILIO_AUTH_TOKEN`) and passes it, with those fields, as `<Parameter>`s. The websocket verifies: the HMAC matches (constant-time), it hasn't expired (TTL 120 s from TwiML to stream start), `start.callSid` equals the signed `call_sid`, and it hasn't been used before (in-process used-set with expiry). Then `client_id` comes **from the signed token**, never from unsigned input.
4. **Handshake signature.** Verify `x-twilio-signature` on the websocket upgrade against the exact `wss://` URL we put in TwiML. *Twilio's public docs say to validate this header but don't specify the signed parameter set for websocket upgrades, so this check is unverified against real traffic. The first real test call is the verification step (documented in `docs/SAFE_TESTING.md`).*
5. **Resource checks before allocation.** The client must exist and `billing.client_active` must pass (re-checked; the plan may have lapsed). A global concurrent-call limit `MAX_CONCURRENT_CALLS` (default 3, the Gemini Live free-tier ceiling noted in the README) is enforced with a counter released in `finally`.
6. TwiML attribute values are XML-escaped (fixes L2).

Negative tests: missing token, bad HMAC, wrong callSid, expired, replayed, unknown business, inactive plan, connection limit, live calls disabled, missing auth token, bad handshake signature. One positive test drives the full start→stop path with a fake Live session.

## Fix 2 — H2: atomic booking

The canonical store becomes **SQLite** (stdlib, already used by `auth.py`), owned by `storage.py` (`bookings.db`, WAL). It has a partial unique index on `(client_id, date, time) WHERE status='confirmed'`, and `reserve_booking()` does a single `INSERT` inside a transaction. An `IntegrityError` becomes `{"status": "conflict"}`. The agent turns a conflict into a model-readable "just taken, here are the current alternatives" error. `check_availability` re-reads booked pairs on every call (indexed query) so conversations don't offer stale slots.
Migration: on first open, existing `bookings.csv` rows are imported once; the CSV is left in place untouched.
`read_bookings` / `booked_pairs` keep their signatures and dict shape, so the dashboard, evals, and bench stay unchanged.
Test: 20 threads × separate agents racing for one slot → exactly 1 confirmed, 19 conflicts, 1 row.

## Fix 3 — H3: single source of truth, Sheets as a mirror

SQLite is the only source of truth. Google Sheets becomes a **best-effort, one-way mirror**, appended after the commit succeeds. A Sheets failure never loses or blocks a booking, and Sheets is never read. *Trade-off, documented:* edits an owner makes directly in the Sheet aren't seen by VoxAgent.
**Explicit test mode:** `VOXAGENT_ENV=test` (set by `tests/conftest.py` and by `evals/run_evals.py`). In test mode:
- The Sheets mirror only uses `TEST_SHEET_ID`; `SHEET_ID` (real business data) is ignored.
- `storage` refuses to write (raises) if any data path still points at the repo's real data files. Fail closed when no safe destination is configured.
Tests use a fake worksheet to prove the mirror is called, that reads stay consistent when it fails, and that a real `SHEET_ID` is never used in test mode.

## Exposure items (high confidence, in scope)

| Item | Change |
|---|---|
| Placeholder/weak admin password (M3) | `ADMIN_PASSWORD` equal to the `.env.example` placeholder, or shorter than 12 chars, is treated as unset (admin disabled, 503 with a clear message); `ADMIN_EMAIL=you@example.com` is never seeded |
| `/api/admin/login` 500 (L1) | pass `authorization=None` explicitly |
| `/api/tts` (M4) | requires a live test-call `session_id`; text ≤ 1,000 chars (portal JS updated to send the session id) |
| Chat/voice limits (M5) | `message` ≤ 2,000 chars (422); voice upload ≤ 5 MB (413) |
| Gemini timeout (M6) | `HttpOptions(timeout=…)` on the shared client (default 30 s, `GEMINI_TIMEOUT_S`) |
| Secret comparisons (M9 part) | `hmac.compare_digest` for admin password / business codes |

## Recorded, not done here (out of scope → follow-ups in AUDIT.md)

M1/M2 metric correctness, M7 dead-air on stream failure, M8 blocking I/O in the async loop, the rate-limiting part of M9, M10 committed demo codes, M11 PII retention/redaction, L3–L12. Each needs a design decision or is product work for later phases.

## Verification

Before and after: `pytest tests -q`, `python docs/audit_repro.py` (R1, R2, R5, R6a, R6b, R7, R8b, R9 must flip to NOT REPRODUCED; R3/R4 remain, being out of scope), `ruff`, `bench.py`. No real calls, no real Sheets, no API key.

---

# Eng review record (`/plan-eng-review`, 2026-10-13)

Target: `docs/HARDENING_PLAN.md` (user-named). Branch `harden/phase-0.5` @ `ab8abbc`. Report file: this file.

## Scope record

feature answers: none proposed (every item maps to the Phase 0.5 brief); structure: B Smaller arrangement (answer D2, 2026-10-13); accepted scope: code changes in existing modules only (`telephony.py`, `server.py`, `storage.py`, `agent.py`, `llm.py`, `auth.py`, `go_live.py`, `evals/run_evals.py`, `web/index.html`, `.env.example`); regression tests extend `tests/test_telephony.py` (H1), `tests/test_agent.py` + `tests/test_storage.py` (H2, H3), `tests/test_access.py` / `tests/test_dashboard.py` (exposure items); new `docs/SAFE_TESTING.md` linked from `SETUP.md`; pending remedies: R1, R2, R3, R4.

## Scope Challenge findings

1. [P1] (confidence: 9/10) telephony.py:243-247 — stream identity comes from unsigned client input: `params = start_msg["start"].get("customParameters", {})` / `client_id = params.get("client_id", ...)`. The token design needs a secret source → **R1**.
2. [P1] (confidence: 7/10) telephony.py:229-231 — `async def twilio_stream(ws)` / `await ws.accept()` with no handshake check. Twilio docs say to validate `x-twilio-signature` on Media Streams but don't publish the websocket signed-parameter set → **R2**.
3. [P2] (confidence: 8/10) evals/run_evals.py:76-79 + storage.py:157-160 — evals redirect CSV paths only, while `sheet_id = os.getenv("SHEET_ID", "")` still selects the real Sheet → **R3**.
4. [P2] (confidence: 8/10) .env.example:6 `ADMIN_PASSWORD=choose_a_strong_password`; server.py:251 `admin_password = os.getenv("ADMIN_PASSWORD", "")`. Rejecting weak values could lock out an existing install → **R4**.
5. Necessary implementation of the approved H2 contract (brief: "Make reserving a slot atomic"), no question: the one-time CSV import uses `INSERT OR IGNORE` and reports skipped duplicates. Reason: the R1 reproduction wrote two confirmed rows for one slot, so real `bookings.csv` files may already hold duplicates that would otherwise abort the import.
6. Necessary implementation of the approved H1 contract (brief: "Check plan and connection limits before allocating expensive resources"), no question: the concurrent-call limit is checked at `/twilio/voice` (answering with a polite busy `<Say>`) and again at stream start (authoritative).

## Decision ledger

### R1: Stream-token signing secret
Finding: #1, P1, confidence 9/10, telephony.py:243-247, reviewer: Claude (plan-eng-review)
Plan baseline: HARDENING_PLAN.md Fix 1 item 3 proposes "secret derived from `TWILIO_AUTH_TOKEN`" (original proposal, not yet approved)
Runtime evidence: no token exists today; server runs one uvicorn process (`server.py:703` `uvicorn.run(app, host=..., port=...)`, no `workers=`), and `go_live.py:202` likewise
Comparison grid:
| Choice | Current | A | B |
|---|---|---|---|
| R1 token secret | none (no token) | random 32 bytes per process, generated at import | HMAC key derived from TWILIO_AUTH_TOKEN |
| Token TTL | n/a | 120 s (from plan, common) | 120 s (from plan, common) |
| Survives restart | n/a | no (in-flight setups fail; TTL makes window tiny) | yes |
| Multi-worker deploy | n/a | breaks unless sticky/single worker | works |
| R2 handshake check | pending | pending | pending |
| R3, R4 | pending | pending | pending |
Question D3:
D3 — Which secret signs the one-time phone stream token?
Project/branch/task: VoxAgent harden/phase-0.5, Fix 1 (H1) phone stream authorisation.
ELI10: When Twilio asks how to handle a call, we hand back a short-lived signed ticket. Twilio presents that ticket when it opens the audio connection, and only a valid, unused, unexpired ticket gets a paid Gemini session. The question is what key signs the ticket: a random key the server invents at startup, or one derived from your Twilio auth token.
Stakes if we pick wrong: A leaked or reused signing key lets attackers forge tickets and open paid sessions; a key that differs between server processes rejects real calls.
Recommendation: A because the same single process both issues and checks the ticket, so a key that never leaves memory has nothing to leak and needs no config.
Completeness: A=9/10, B=8/10
Pros / cons:
A) Per-process random secret (recommended)
  ✅ Never stored or derivable from .env, so leaking .env cannot forge stream tickets
  ✅ Zero configuration; a restart automatically invalidates every outstanding ticket
  ❌ Breaks if the app is ever run with several uvicorn workers; needs sticky routing or option B then
B) Derived from TWILIO_AUTH_TOKEN
  ✅ Works across restarts and across multiple worker processes without extra setup
  ✅ Rotating the Twilio token in their console also rotates ticket signing
  ❌ Couples ticket forgery to the auth token, which also lives in .env and signs webhooks
Net: Single-process today favours an in-memory key; B is the upgrade path if you scale out.
Header: Token key
Options:
A) Per-process random (recommended)
secrets.token_bytes(32) at import in telephony.py; tokens invalid after restart; document "single worker" constraint in SAFE_TESTING.md. Human ~1h / CC ~5 min. Low maintenance.
B) Derived from Twilio token
HMAC key = HMAC-SHA256(TWILIO_AUTH_TOKEN, "voxagent-stream-v1"); survives restarts and multiple workers. Human ~1h / CC ~5 min. Rotation follows the Twilio token.

State: approved
Actual answer: A) Per-process random (recommended), answer to D3, 2026-10-13
Accepted scope: telephony.py signs stream tokens with `secrets.token_bytes(32)` generated at import; tokens are invalid after restart; SAFE_TESTING.md documents the single-worker constraint and option B as the scale-out path. TTL 120 s unchanged.
History: none

### R2: Websocket handshake signature check
Finding: #2, P1, confidence 7/10, telephony.py:229-231, reviewer: Claude (plan-eng-review)
Plan baseline: HARDENING_PLAN.md Fix 1 item 4 proposes verifying `x-twilio-signature` on the upgrade against the exact `wss://` URL (original proposal, not yet approved)
Runtime evidence: Twilio docs (media-streams-configuration; webhooks-security) say to validate `x-twilio-signature` on Media Streams and that the header is lowercase for websockets; neither page states the signed parameter set for the upgrade. Unverified against real traffic; no Twilio account is available in this session.
Comparison grid:
| Choice | Current | A | B |
|---|---|---|---|
| R2 handshake signature | not checked | checked; mismatch → close 1008 before any allocation (fail closed) | checked; mismatch → structured warning log only, the stream token alone decides |
| R1 token secret | approved: per-process random (D3) | unchanged | unchanged |
| Stream token (TTL/single-use/callSid) | approved via brief | enforced | enforced |
| ENABLE_LIVE_CALLS gate | approved via brief | off by default | off by default |
| R3, R4 | pending | pending | pending |
Question D4:
D4 — Should a bad Twilio handshake signature reject the phone stream, or only log?
Project/branch/task: VoxAgent harden/phase-0.5, Fix 1 (H1), second layer behind the approved one-time ticket.
ELI10: Twilio also signs the moment it opens the audio connection. We can refuse any connection whose signature doesn't check out, or just log it. Twilio's docs say to check it but don't spell out exactly what they sign for this kind of connection, and we can't test it without a real Twilio call. If we enforce and our guess about the signed data is wrong, every real call is refused until we fix it. If we only log, a mismatch never blocks calls, and the one-time ticket remains the actual lock.
Stakes if we pick wrong: Enforcing a wrongly-understood check refuses every real call on the first test; logging-only leaves one defence layer advisory until verified.
Recommendation: A because your brief asks to validate the provider's signature and fail closed, and live calls stay switched off until the documented first-call verification, so a wrong guess shows up in a controlled test, not with a customer.
Completeness: A=9/10, B=7/10
Pros / cons:
A) Enforce, fail closed (recommended)
  ✅ Matches Twilio's stated requirement and your brief's fail-closed rule from the first enabled call
  ✅ Two independent locks: an attacker needs both a valid ticket and a valid Twilio signature
  ❌ If Twilio signs the upgrade differently than assumed, the first verification call fails and needs a code fix
B) Log only until verified
  ✅ A wrong assumption about Twilio's signing can never block a real call
  ✅ Logs collect real signatures, so the check can be switched to enforce with evidence later
  ❌ Leaves the second layer advisory; protection rests on the ticket alone until someone flips it
Net: A is stricter now and surfaces any mismatch in the planned verification call; B trades strictness for zero risk of refusing calls.
Header: WS signature
Options:
A) Enforce, fail closed (recommended)
Verify with twilio RequestValidator against the exact wss:// URL from the TwiML and empty params; mismatch or missing header closes 1008 before agent/Gemini allocation. Negative tests cover missing and bad signatures. SAFE_TESTING.md makes the first real call the verification step. Human ~2h / CC ~10 min.
B) Log only until verified
Same verification, but a mismatch writes a structured warning and the call proceeds on the ticket alone; SAFE_TESTING.md tells you to switch to enforce after a verified call. Human ~2h / CC ~10 min. One more config switch to maintain.

State: approved
Actual answer: A) Enforce, fail closed (recommended), answer to D4, 2026-10-13
Accepted scope: `/twilio/stream` verifies `x-twilio-signature` with twilio `RequestValidator` against the exact `wss://` URL emitted in TwiML and empty params; a missing or bad signature closes 1008 before any agent or Gemini allocation; negative tests for missing and bad signatures; SAFE_TESTING.md makes the first real call the verification step and states the check is unverified against real Twilio traffic until then.
History: none

### R3: Google Sheets in test mode
Finding: #3, P2, confidence 8/10, evals/run_evals.py:76-79 and storage.py:157-160, reviewer: Claude (plan-eng-review)
Plan baseline: HARDENING_PLAN.md Fix 3 proposes `VOXAGENT_ENV=test`, under which the mirror uses only `TEST_SHEET_ID` and ignores `SHEET_ID`, plus a fail-closed guard on real data paths (original proposal, not yet approved)
Runtime evidence: tests force the CSV fallback via `monkeypatch.setenv("SHEET_ID", "")` (tests/conftest.py:27); evals do not (evals/run_evals.py:76-79), so with SHEET_ID set an eval booking reaches `_save_to_google_sheet` (storage.py:127) and the real Sheet. Static; not executed (no Sheet credentials here).
Comparison grid:
| Choice | Current | A | B |
|---|---|---|---|
| R3 Sheets in test mode | real SHEET_ID used by evals | mirror fully disabled; any Sheets credentials ignored | mirror allowed only to TEST_SHEET_ID; SHEET_ID ignored |
| Fail-closed path guard in test mode | none | yes (common, from brief) | yes (common, from brief) |
| Mock destination for tests | none | fake worksheet injected by monkeypatching storage._sheet_handle | same fake for unit tests, plus optional real throwaway sheet |
| Single source of truth = SQLite, Sheets one-way mirror | proposed in plan Fix 3 (H3 contract) | unchanged | unchanged |
| R1, R2 | approved (D3, D4) | unchanged | unchanged |
| R4 | pending | pending | pending |
Question D5:
D5 — In test mode, should the Google Sheets mirror be off completely, or allowed to a separate test sheet?
Project/branch/task: VoxAgent harden/phase-0.5, Fix 3 (H3); tests and evals must never touch real business data.
ELI10: Bookings will live in a local database, and Google Sheets just gets a copy. When tests or evals run, we can switch the copy off entirely and prove the copying logic with a fake sheet. Or we can let it copy to a throwaway sheet you name with TEST_SHEET_ID. The second option tests the real Google connection, but it's one more place where a typo (pasting the real sheet ID) leaks test bookings into a client's sheet.
Stakes if we pick wrong: Allowing any real sheet in test mode keeps a path for fake bookings to land in a clinic's real booking sheet; turning it off means the real Google connection is only exercised manually.
Recommendation: A because the brief says regression tests and evals must never write to real business data and must fail closed, and a fake sheet already proves our mirror logic.
Completeness: A=9/10, B=8/10
Pros / cons:
A) Mirror off in test mode (recommended)
  ✅ No configuration can send test bookings to any Google Sheet while VOXAGENT_ENV=test
  ✅ Fake worksheet tests still prove mirroring, failure fallback and read consistency offline
  ❌ The real gspread connection is only checked by a manual step documented in SAFE_TESTING.md
B) Allow TEST_SHEET_ID
  ✅ Lets you run an end-to-end check against a real throwaway Google Sheet when wanted
  ✅ SHEET_ID is still ignored, so the default path stays safe
  ❌ A mistaken TEST_SHEET_ID (e.g. the client's real ID) writes test data into business records
Net: A makes "never real data in tests" structural; B keeps an optional live check with a human-error risk.
Header: Test Sheets
Options:
A) Mirror off in test mode (recommended)
VOXAGENT_ENV=test disables the Sheets mirror regardless of SHEET_ID/credentials; tests inject a fake worksheet; storage raises if a test-mode write targets the repo's real data files; evals set test mode. Human ~3h / CC ~15 min.
B) Allow TEST_SHEET_ID
Same guard, but the mirror may write to TEST_SHEET_ID in test mode (never SHEET_ID); fake worksheet for unit tests. Human ~3h / CC ~15 min. One more env var to keep correct.

State: approved
Actual answer: A) Mirror off in test mode (recommended), answer to D5, 2026-10-13
Accepted scope: with `VOXAGENT_ENV=test` the Sheets mirror is disabled regardless of `SHEET_ID`/credentials; mirror tests inject a fake worksheet object (never a network handle); storage raises if a test-mode write targets the repo's real data files; `tests/conftest.py` and `evals/run_evals.py` set test mode; SAFE_TESTING.md documents a manual check of the real gspread connection. `TEST_SHEET_ID` is not introduced.
History: none

### R4: Admin password policy
Finding: #4, P2, confidence 8/10, .env.example:6 and server.py:251, reviewer: Claude (plan-eng-review)
Plan baseline: HARDENING_PLAN.md exposure table proposes treating the placeholder OR any password shorter than 12 chars as unset (original proposal, not yet approved); never seeding ADMIN_EMAIL=you@example.com is part of the same row
Runtime evidence: R6b reproduced: `X-Admin-Key: choose_a_strong_password` → `/api/admin/overview` 200 including every access_key. Existing test fixtures use 13- and 12-character passwords (tests/test_access.py:13 `test-admin-pw`, tests/test_dashboard.py:17 `admin-pw-123`). The real `.env` admin password length is unknown (no `.env` in this checkout).
Comparison grid:
| Choice | Current | A | B |
|---|---|---|---|
| R4 weak admin password | any non-empty value accepted | placeholder or < 12 chars → admin disabled (503 + startup warning) | only the exact placeholder → admin disabled |
| Placeholder ADMIN_EMAIL seeding | seeded as admin | never seeded (common) | never seeded (common) |
| Comparison method | `==` | `hmac.compare_digest` (approved via brief exposure scope) | same |
| R1, R2, R3 | approved (D3, D4, D5) | unchanged | unchanged |
Question D6:
D6 — How strict should VoxAgent be about the admin password?
Project/branch/task: VoxAgent harden/phase-0.5, exposure item M3 (admin console opens with the .env.example placeholder).
ELI10: The admin password unlocks every business's data and their login codes. Right now even the sample text from .env.example works as a password. We can refuse only that sample text, or also refuse anything shorter than 12 characters. The stricter rule could lock you out on the next restart if your real password is short, but the error message will say exactly what to change.
Stakes if we pick wrong: Too lax means a short guessable password protects every client's data once the server is public; too strict means one restart where /admin says "set a longer password".
Recommendation: A because the admin key is checked with no rate limit (audit M9), so length is the only thing standing between a public server and guessing.
Completeness: A=9/10, B=6/10
Pros / cons:
A) Placeholder + min 12 chars (recommended)
  ✅ Blocks the sample value and short guessable passwords on an endpoint with no attempt limit
  ✅ Clear 503 message and a startup warning say exactly which variable to fix
  ❌ An existing install with a short password loses /admin access until .env is edited
B) Placeholder only
  ✅ Never disrupts an existing install whose password is short but not the sample value
  ✅ Still closes the reproduced R6b hole exactly
  ❌ Leaves a 6-character admin password acceptable on a public, unthrottled endpoint
Net: A trades a one-time .env edit for real protection; B closes only the exact reproduced case.
Header: Admin pw
Options:
A) Placeholder + min 12 chars (recommended)
Admin access (header key and admin account seeding) disabled when ADMIN_PASSWORD equals the .env.example placeholder or is shorter than 12 chars; 503 says why; server prints a startup warning; .env.example documents the rule. Tests for placeholder, short and valid. Human ~1h / CC ~5 min.
B) Placeholder only
Admin access disabled only when ADMIN_PASSWORD equals the .env.example placeholder; same 503 and warning. Tests for placeholder and valid. Human ~45 min / CC ~5 min.

State: approved
Actual answer: A) Placeholder + min 12 chars (recommended), answer to D6, 2026-10-13
Accepted scope: admin access (X-Admin-Key header and admin-account seeding) is disabled when ADMIN_PASSWORD equals the `.env.example` placeholder or is shorter than 12 chars; the 503 says why; the server prints a startup warning; `ADMIN_EMAIL=you@example.com` is never seeded; `.env.example` documents the rule; tests cover placeholder, short and valid passwords; comparisons use `hmac.compare_digest`.
History: none

Scope Challenge result: scope accepted as-is (D2 chose a smaller file arrangement with the same scope; no feature cut). MODE: FULL_REVIEW.

## Section 1: Architecture review

1. [P2] (confidence: 8/10) storage.py:100-112 `def data_version(...)` / `for path in (BOOKINGS_CSV, LEADS_CSV): parts.append(str(_stamp(path)))` — the dashboard ETag is keyed on the CSV stamp. Once bookings move to SQLite, a booking would not change the ETag, and the dashboard would answer 304 with stale data. Necessary implementation of the approved H3 contract ("read consistently by availability checks and the dashboard"): every booking write bumps `_version`, and the DB file stamp joins the ETag parts. A test asserts that the ETag changes after a booking. No question.
2. [P2] (confidence: 9/10) telephony.py:1-27 (module docstring diagram `caller's phone ──► Twilio ──► POST /twilio/voice ...`) — the lifecycle diagram will be stale once tokens, signature, billing and limit gates exist. Necessary per diagram rule: update it in the same commit (diagram below). No question.
3. [P3] (confidence: 8/10) telephony.py:158 `result = self.agent._execute_tool(call["name"], call["args"])` in `async def pump_gemini` — a booking (SQLite write + Sheets mirror network call) runs synchronously inside the event loop. This is pre-existing (audit M8); the Sheets call already ran synchronously before this plan. No change proposed: the plan's out-of-scope list defers M8. The SQLite write adds roughly milliseconds [estimated].
4. [P2] (confidence: 8/10) server.py:330-339 `def admin_outbound_call` and go_live.py:176 `telephony.set_voice_webhook(url)` — both must honour `ENABLE_LIVE_CALLS`, or the gate can be bypassed from /admin. Already in the plan (Fix 1 item 1 "outbound calls refuse, go_live.py refuses"); recorded as a required test. No question.

Planned phone lifecycle (replaces the telephony.py docstring diagram):

```
Twilio ──POST /twilio/voice──► [ENABLE_LIVE_CALLS?]──no──► 503
                                   │yes
                               [X-Twilio-Signature valid?]──no──► 403
                                   │yes
                               [client active? under call limit?]──no──► <Say> unavailable/busy
                                   │yes
                               TwiML <Stream url=wss://…> + <Parameter token, call_sid, client_id, caller, exp>
Twilio ──WSS /twilio/stream──► [ENABLE_LIVE_CALLS?]──no──► close 1008
                                   │yes
                               [x-twilio-signature on upgrade valid?] (R2: enforce)──no──► close 1008
                                   │yes  accept, read "start"
                               [token HMAC ok · not expired · callSid matches · unused]──no──► close 1008
                                   │yes
                               [client exists & billing active · slot under MAX_CONCURRENT_CALLS]──no──► close 1008
                                   │yes  (only now)
                               ReceptionistAgent + GeminiLive ──► bridge ──finally──► release slot, log call
```

Dispositions: #1 accepted (necessary H3 implementation), #2 accepted (diagram rule), #3 no change (pre-existing, deferred M8), #4 accepted (already in plan; test required).

## Section 2: Code quality review

1. [P2] (confidence: 9/10) telephony.py:215-223 `twiml = f"""...<Parameter name="caller" value="{caller}"/>` — f-string XML (L2, reproduced R8b). The plan's Fix 1 item 6 already covers it; the token parameters added by Fix 1 must go through the same `xml.sax.saxutils.quoteattr` path. No question.
2. [P3] (confidence: 9/10) server.py:186,254,426 — `admin_key == admin_password`, `x_admin_key != admin_password`, `cfg["access_key"] == code` are non-constant-time. Covered by the exposure table (`hmac.compare_digest`). No question.
3. Shared code: the per-thread SQLite connection pattern exists in auth.py:74-92 (`_db()` with `threading.local`) and is about to be needed in storage.py. Rubric: two verified callers (auth.py:74 existing; storage bookings store proposed, labeled assumption). Extraction would couple auth and storage across a module boundary that CLAUDE.md keeps separate ("storage.py: ALL disk I/O"; auth owns its DB). The estimated saving is ~15 lines against a new shared module and a cross-module failure blast radius. **Rejected:** storage.py gets its own ~15-line connection helper mirroring auth.py's pattern. No question (no extraction proposed).

Dispositions: #1 accepted (already in plan), #2 accepted (already in plan), #3 extraction rejected by rubric.

## Section 3: Test review

Framework: pytest (CLAUDE.md "Tests: tests/ — pytest"; `python -m pytest tests -q`), 58 tests, FakeLLM + FakeLive seams.

```
CODE PATHS                                                   USER FLOWS
[+] telephony.py                                             [+] Real inbound call (Twilio)
  ├── twilio_voice()                                           ├── [GAP] [→E2E] first real call = manual verification (SAFE_TESTING.md)
  │   ├── [★★ TESTED] signed → TwiML  test_telephony.py:154    └── [GAP] caller hears busy/unavailable message
  │   ├── [★★ TESTED] bad signature 403 :167                 [+] Attacker opens /twilio/stream
  │   ├── [GAP] live calls disabled → 503                      ├── [GAP] no token / bad HMAC / wrong callSid
  │   ├── [GAP] token unset → 503 (was: allowed)               ├── [GAP] expired / replayed token
  │   ├── [GAP] inactive client → <Say>; at limit → busy       └── [GAP] no/bad x-twilio-signature (R2)
  │   └── [GAP] TwiML attrs escaped (R8b)                    [+] Two callers want the same slot
  ├── twilio_stream()                                          └── [GAP] concurrent booking → 1 confirmed, rest conflict
  │   ├── [GAP] every rejection closes BEFORE agent/Gemini   [+] Owner dashboard after a booking
  │   ├── [GAP] limit reached → reject; slot released finally  └── [GAP] ETag changes, booking listed (Sheets on or off)
  │   └── [GAP] happy path start→stop with FakeLive
  └── start_outbound_call() [GAP] refuses when live calls disabled
[+] storage.py
  ├── reserve_booking()  [GAP] insert ok / conflict / concurrent race (20 threads)
  ├── read_bookings()/booked_pairs()  [★★ TESTED via CSV] test_storage.py:8, test_agent.py:104 → must pass on SQLite
  ├── CSV import  [GAP] imports once, skips duplicates, leaves CSV untouched
  ├── Sheets mirror  [GAP] called after commit; failure keeps booking; never read; off in test mode
  └── test-mode guard  [GAP] write to repo data path raises
[+] agent.py _book_appointment  [GAP] conflict → failed + fresh alternatives; check_availability sees other agents' bookings
[+] server.py  [GAP] /api/tts needs session + ≤1000 chars; chat ≤2000 → 422; voice >5MB → 413;
               admin placeholder/short → 503; /api/admin/login no 500
[+] llm.py  [GAP] shared client built with HttpOptions(timeout) (unit, no network)
LLM integration: no prompt/tool-schema change → no [→EVAL] required; evals must still run in test mode.

COVERAGE: 4/30 paths tested (13%)  |  Code paths: 4/24  |  User flows: 0/6
QUALITY: ★★★:0 ★★:4 ★:0  |  GAPS: 26 (1 E2E manual, 0 eval)
```

Regression risk (IRON RULE): moving bookings from CSV to SQLite and rejecting unsigned webhooks changes behaviour that existing tests and docs rely on (tests/test_storage.py:12 `assert "bookings.csv" in where`; tests/test_telephony.py:156 `monkeypatch.setenv("TWILIO_AUTH_TOKEN", "")  # no signature check in local mode`; SETUP.md:4,99 and README.md:168 tell owners bookings land in `bookings.csv`) → **R5**.

### R5: Regression contract for the storage and webhook changes
Finding: Section 3 regression risk, P1, confidence 9/10, tests/test_storage.py:12, tests/test_telephony.py:156, SETUP.md:99, reviewer: Claude (plan-eng-review)
Plan baseline: Fix 2/3 make SQLite the only source of truth and leave `bookings.csv` "in place untouched" after a one-time import; Fix 1 removes the unsigned local-mode webhook (original proposal; regression contract not yet approved)
Runtime evidence: 58 tests pass today; owners are told (SETUP.md:99) bookings go to `bookings.csv` when Sheets is not configured. Whether any owner opens that file directly is unknown.
Comparison grid:
| Choice | Current | A | B |
|---|---|---|---|
| R5 owner-visible bookings.csv | appended on every booking (when no Sheet) | frozen after import; SQLite only; dashboard is the view; docs updated | still appended after each commit as a write-only export (never read) |
| Preserved API: read_bookings/booked_pairs shape, tool result schemas, dashboard JSON | n/a | preserved + asserted | preserved + asserted |
| Intentional changes: save_booking return text, unsigned webhook rejected, /api/tts needs session, size limits | n/a | listed; tests updated | listed; tests updated |
| Acceptance | 58 pass | all 58 pass except the 2 intentionally changed asserts, rewritten to the new contract; new gap tests pass | same |
| R1–R4 | approved (D3–D6) | unchanged | unchanged |
Question D7:
D7 — After bookings move to the database, should VoxAgent keep writing bookings.csv?
Project/branch/task: VoxAgent harden/phase-0.5; regression contract for Fix 2/3 (SQLite becomes the single source of truth).
ELI10: Today, without Google Sheets, every booking is added to a bookings.csv file, and SETUP.md tells owners that's where bookings go. After the fix, bookings live in a small database that blocks double-booking. We can stop touching the CSV (the dashboard shows bookings), or keep appending each booking to it as a read-only export for anyone who opens it in Excel. Either way, the rest of the contract is fixed: functions and dashboard keep the same shape, existing bookings are imported, and only two old test assertions change on purpose.
Stakes if we pick wrong: Freezing the CSV surprises anyone who opens it to see new bookings; keeping it means two files claiming to hold bookings, one of which nobody reads.
Recommendation: A because one source of truth is the whole point of the H3 fix, and the dashboard already shows bookings to owners.
Completeness: A=9/10, B=8/10
Pros / cons:
A) Freeze CSV, database only (recommended)
  ✅ One place holds bookings, so nothing can drift or contradict the double-booking guard
  ✅ Docs (SETUP.md, README) updated to point owners at the dashboard instead of a file
  ❌ Anyone used to opening bookings.csv in Excel sees no new rows after the upgrade
B) Keep CSV as export
  ✅ Existing habits keep working: new bookings still appear in bookings.csv
  ✅ Gives a plain-text backup next to the database
  ❌ Two booking records on disk; a hand-edit to the CSV silently does nothing, which confuses owners
Net: A is simpler and honest about where truth lives; B preserves a file-based habit at the cost of a second copy.
Header: CSV export
Options:
A) Freeze CSV, database only (recommended)
Import bookings.csv once (INSERT OR IGNORE, duplicates reported), never write it again; read_bookings/booked_pairs/dashboard shapes preserved and asserted; tests/test_storage.py:12 and tests/test_telephony.py:154 rewritten to the new contract; SETUP.md/README updated. Human ~3h / CC ~15 min.
B) Keep CSV as export
Same contract, plus append each committed booking to bookings.csv as a write-only export (never read back); docs say the CSV is an export copy. Human ~3.5h / CC ~20 min.

State: approved
Actual answer: A) Freeze CSV, database only (recommended), answer to D7, 2026-10-13
Accepted scope: bookings.csv is imported once into SQLite (INSERT OR IGNORE, skipped duplicates reported) and never written again. `read_bookings` / `booked_pairs` / dashboard JSON / tool-result shapes are preserved and asserted. The two intentionally changed assertions (tests/test_storage.py:12, tests/test_telephony.py:154-164) are rewritten to the new contract; every other existing test must pass unmodified. SETUP.md and README updated to point owners at the dashboard.
History: none

Test plan requirements (approved by D2–D7 and the brief's contracts; carried as required proof):
- tests/test_telephony.py: live-calls-disabled (webhook 503, stream 1008, outbound refuses); webhook rejects when token unset; signed webhook → TwiML with escaped attrs and a token; stream rejections (no token, bad HMAC, wrong callSid, expired, replayed, unknown business, inactive plan, at limit, missing/bad handshake signature), each asserting **no** agent or GeminiLive was constructed; limit slot released after a normal call; happy path start→stop with FakeLive.
- tests/test_storage.py: reserve ok/conflict; 20-thread race → exactly 1 row; CSV import once with duplicate skipped and CSV untouched; mirror called after commit (fake worksheet), mirror failure keeps booking, mirror off in test mode even with SHEET_ID set; test-mode write to repo data path raises; ETag changes after a booking.
- tests/test_agent.py: conflict → `failed` with current alternatives; a second agent's booking is excluded from the first agent's next check_availability.
- tests/test_access.py / tests/test_dashboard.py: /api/tts 401 without session, 422 over 1000 chars; chat 2001 chars → 422; voice > 5 MB → 413; admin placeholder and 11-char password → 503, 12-char works; /api/admin/login returns 200/401, never 500.
- llm.py: shared client constructed with `HttpOptions(timeout=GEMINI_TIMEOUT_S*1000)` (constructor spy, no network).
- docs/audit_repro.py rerun: R1, R2, R5, R6a, R6b, R7, R8b, R9 → NOT REPRODUCED; R3, R4 unchanged (out of scope).

Dispositions: regression contract R5 approved (D7); all gap tests above accepted as required proof of approved contracts.

## Section 4: Performance review

1. [P3] (confidence: 7/10) agent.py:278 `slots = self.slots.get(date)` — the plan makes `check_availability` re-read booked pairs from SQLite on each call instead of using the agent's snapshot. Scale: one indexed query over one client's confirmed rows per tool call, a few tool calls per conversation; at pilot volume (hundreds of rows) that's sub-millisecond [estimated; bench.py rerun required after implementation]. Acceptable; no question.
2. [P3] (confidence: 8/10) storage.py:136-147 — the CSV path cached a parsed index (`_booked_index`); the SQLite path queries per call. No cache is proposed: an index lookup is cheaper than cache-invalidation risk on the exact path that prevents double-booking. bench.py must show "availability for the whole window" and "build an agent" still sub-ms [re-measure before gate].
3. No new unbounded queries: read_bookings returns one client's rows (unchanged semantics). The LLM timeout (exposure item) bounds the previously unbounded `generate_content` call (llm.py:235).

Dispositions: #1–#3 no change; a bench rerun is part of verification.

## Outside voice

Codex CLI is not installed and Aside is unavailable; the native fallback requires the TaskOutput tool, which this session does not declare → **Outside voice unavailable.** No clean-review credit; missing coverage recorded.

## Final planning decisions

TODOS.md (new file): 4 proposals, each asked individually, all answered "Add to TODOS.md": M7+M8 phone resilience, M9 rate limiting, M11 retention/redaction, M1+M2 honest metrics.

Approval readiness: PASS. Checked R1 (D3), R2 (D4), R3 (D5), R4 (D6), R5 (D7); structure D2; scope-challenge items #5 and #6 and section items carried as necessary implementation of brief-approved contracts (H1 "check plan and connection limits before allocating"; H2 "make reserving a slot atomic"; H3 "read consistently by availability checks and the dashboard").

## Reality rows

| premise | claim | receipt | verdict |
|---|---|---|---|
| unsigned stream accepted | `/twilio/stream` trusts customParameters | telephony.py:243-247; audit_repro R9 | true |
| concurrent double-booking | two agents both confirm | agent.py:146,321; R1 | true |
| Sheets bookings invisible | reads only CSV | storage.py:127-147; R2 | true |
| google-genai supports request timeout | `HttpOptions.timeout` ms | probe: `types.HttpOptions.model_fields['timeout']` | true |
| SQLite partial unique index enforced | duplicate confirmed rejected, cancelled allowed | probe, sqlite 3.51.2 | true |
| twilio validator signature | `validate(uri, params, signature)` | probe: inspect.signature | true |
| Twilio WS upgrade signed params | exact URL + empty params | twilio.com docs do not specify | **unverified** |
| free-tier Live concurrency = 3 | README "free: 3" | README.md capacity note, no primary source | **unverified** (default only; configurable) |
| single uvicorn process | no workers arg | server.py:703, go_live.py:202 | true |

REALITY: premise-table finding unverified=2 (Twilio WS signing params; Live concurrency default) telephony.py:229-257 README.md:208
REALITY: already-done pass local-only repo, base main has 2 commits, no prior fix for H1-H3 ab8abbc
REALITY: surface-check pass HttpOptions.timeout, RequestValidator.validate, WebSocket.headers/url, pydantic max_length, sqlite partial index all probed llm.py:235
REALITY: binding-decisions pass gstack-decision-search empty; D2-D7 recorded in ledger docs/HARDENING_PLAN.md:74-241
REALITY: numbers pass TTL 120 s [estimated], admin min 12 chars [decided D6], chat 2000 / TTS 1000 chars [estimated], voice 5 MB [estimated], LLM timeout 30 s [estimated], MAX_CONCURRENT_CALLS 3 [README claim, unverified], bench sub-ms [re-measure before gate] bench.py:1
REALITY: deferred-asks pass brief asks "inspect personal-data retention": inspected, deferred to TODOS.md M11 by user answer; all other asks in scope TODOS.md:31-41
REALITY: pr-count pass 1 PR (no ship-policy.json; default); no git remote exists, so /ship cannot open a PR until one is added ab8abbc
REALITY: transaction-semantics pass single-statement INSERT under a partial UNIQUE index, per-thread connections, WAL; no pool; race test (20 threads) is the crash-robot equivalent storage.py (proposed)

## NOT in scope

- M1/M2 metric correctness: TODOS.md; overlaps the Phase 2/3 conversation format.
- M7/M8 phone resilience and event-loop blocking: TODOS.md; needs async restructuring beyond gating.
- M9 rate limiting: TODOS.md; only the constant-time comparison lands here.
- M10 committed demo access codes: left in AUDIT.md follow-ups; demo-only data, and rotating needs the owner's choice of new codes.
- M11 retention/redaction: TODOS.md; needs an owner policy decision first.
- L3–L12: remain in AUDIT.md as recorded low-severity items.
- Multi-worker deployment: R1 chose a per-process secret; scale-out would switch to option B.

## What already exists

- `auth.py:74-92` per-thread SQLite connection pattern: mirrored (not shared) in storage.py; extraction rejected in Section 2 #3.
- `telephony._validate_signature` + twilio `RequestValidator`: reused for the webhook (now fail-closed) and the websocket handshake.
- `billing.client_active`: reused at both webhook and stream start.
- `tests/conftest.py` `tmp_storage` / `FakeLLM`, `tests/test_telephony.py` `FakeLive`: reused for all new tests.
- `docs/audit_repro.py`: reused as the before/after security evidence.

## Failure modes

| New path | Realistic failure | Test / handling | User sees |
|---|---|---|---|
| Stream token check | server restarts between webhook and stream start | token invalid (R1) → close 1008; covered by bad-HMAC test | caller hears the call end; retry works (clear, rare) |
| Handshake signature (R2) | Twilio signs differently than assumed | close 1008; negative tests; first real call is the verification step | first verification call fails loudly in a controlled test, not silently |
| Concurrency limit | slot not released after an exception | released in `finally`; test asserts release after a normal and an aborted call | busy message if leaked (visible, not silent) |
| reserve_booking | SQLite locked under contention | `timeout=10` on connect; race test with 20 threads | booking fails with a model-readable error, agent offers alternatives |
| CSV import | malformed CSV row | rows lacking key fields are skipped and counted; import logged | dashboard shows imported rows; warning printed |
| Sheets mirror | network/credential error | caught after commit, warning logged; test with failing fake | booking succeeds; Sheet misses a row (logged, not silent) |
| Admin password policy | owner's existing short password | 503 with message + startup warning; tests | clear error naming ADMIN_PASSWORD |

Critical gaps (no test AND no handling AND silent): **0**.

## Worktree parallelization strategy

| Step | Modules touched | Depends on |
|------|----------------|------------|
| H2+H3 booking store | storage, agent, evals, tests | — |
| H1 phone gating | telephony, server (outbound), go_live, tests | — |
| Exposure items | server, auth, llm, web, tests | — |
| Docs (AUDIT, SAFE_TESTING, SETUP/README) | docs | all three |

Lane A: H2+H3. Lane B: H1. Lane C: exposure items. They share `server.py` (B: outbound gate; C: tts/limits/admin) and `tests/test_telephony.py` / `tests/test_access.py`. Conflict flag: server.py is shared. **Sequential implementation chosen** (A → B → C → docs): the change is ~1 day of work for one builder, and the shared server.py makes parallel merges costlier than they save.

## Implementation Tasks

Synthesized from this review's findings. Each task derives from a specific finding above.

- [ ] **T1 (P1, human: ~1 day / CC: ~30 min)** — storage/agent — SQLite booking store with atomic reserve, CSV import, Sheets mirror, test mode
  - Surfaced by: Fix 2/3; R3 (D5); R5 (D7); Scope #5; Section 1 #1
  - Files: storage.py, agent.py, evals/run_evals.py, tests/conftest.py, tests/test_storage.py, tests/test_agent.py
  - Verify: `python -m pytest tests -q`; `python docs/audit_repro.py` (R1, R2 → NOT REPRODUCED)
- [ ] **T2 (P1, human: ~1 day / CC: ~30 min)** — telephony — ENABLE_LIVE_CALLS gate, fail-closed webhook signature, escaped TwiML, stream token (R1), handshake signature (R2), billing + concurrency checks before allocation
  - Surfaced by: Fix 1; R1 (D3); R2 (D4); Scope #6; Section 1 #2, #4; Section 2 #1
  - Files: telephony.py, server.py (outbound), go_live.py, .env.example, tests/test_telephony.py
  - Verify: pytest; audit_repro R8b, R9 → NOT REPRODUCED
- [ ] **T3 (P1, human: ~4h / CC: ~20 min)** — server/auth/llm/web — admin password policy (R4), /api/admin/login fix, tts session + limit, chat/voice limits, Gemini timeout, constant-time compares
  - Surfaced by: R4 (D6); exposure table; Section 2 #2
  - Files: server.py, auth.py, llm.py, web/index.html, tests/test_access.py, tests/test_dashboard.py
  - Verify: pytest; audit_repro R5, R6a, R6b, R7 → NOT REPRODUCED
- [ ] **T4 (P2, human: ~2h / CC: ~15 min)** — docs — AUDIT.md status + evidence, SAFE_TESTING.md, SETUP.md/README booking-store and live-call notes
  - Surfaced by: brief deliverables; R1/R2 documentation scope; R5 docs scope
  - Files: docs/AUDIT.md, docs/SAFE_TESTING.md, SETUP.md, README.md
  - Verify: read-through; every claim cites a test or repro result
- [ ] **T5 (P2, human: ~30 min / CC: ~5 min)** — verification — bench.py rerun, ruff on changed files
  - Surfaced by: Section 4 #1, #2
  - Files: none (measurement)
  - Verify: `python bench.py` sub-ms on agent build and availability

## Unresolved decisions

None.

## Completion summary

- Step 0: Scope Challenge — scope accepted as-is
- Reality rows: 8/8 applicable rows emitted, 2 unverified premises
- Architecture Review: 4 issues found
- Code Quality Review: 3 issues found
- Test Review: diagram produced, 26 gaps identified
- Performance Review: 3 issues found
- NOT in scope: written
- What already exists: written
- TODOS.md updates: 4 items proposed to user (4 added)
- Failure modes: 0 critical gaps flagged
- Unresolved decisions: 0 in this review
- Outside voice: codex, unavailable (CLI not installed; native fallback needs TaskOutput, not declared)
- Parallelization: 3 lanes identified, 0 parallel / 4 sequential
- Lake Score: 0/5 = no scored option was 10/10; all five scored answers (D3–D7) picked the highest-scored option (9/10)

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 0 | — | — |
| Outside Review | codex via `/plan-eng-review` outside voice | Independent 2nd opinion | 1 | unavailable | CLI not installed; native fallback lacks TaskOutput |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 1 | ISSUES OPEN | 36 issues, 0 critical gaps |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | — | — |
| DX Review | `/plan-devex-review` | Developer experience gaps | 0 | — | — |

- **OUTSIDE COVERAGE:** codex, plan-review phase, unavailable (not installed); no native fallback ran (TaskOutput not declared). Missing coverage, not a pass.
- **VERDICT:** no review CLEAR. Eng Review ISSUES OPEN: all 36 findings are mapped to tasks T1–T5 with approved decisions D2–D7; eng review required.

NO UNRESOLVED DECISIONS
