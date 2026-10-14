# VoxAgent — Phase 0 Repository Audit

**Date:** 2026-10-13 · **Scope:** the code in `voxagent-main/` (all 15 Python modules, 2 HTML pages, tests, evals, configs, docs)
**Method:** read every source file, ran the existing tests/linters/type checker/dependency audit/benchmark, then wrote offline reproductions for each suspected defect (`docs/audit_repro.py`).
**Rule applied:** a defect is marked **Reproduced** only if a script observed it. Problems found by reading the code alone are marked **Static** (evidence is a line reference, not a run). Anything that needs a real API key or network is marked **Not reproduced**.

---

## 0. Status after Phase 0.5 hardening (2026-10-13, branch `harden/phase-0.5`)

Plan and decisions: `docs/HARDENING_PLAN.md` (eng review D2–D7). Safe testing and the live-call switch: `docs/SAFE_TESTING.md`. Deferred work: `TODOS.md`.

**Evidence method.** The same `docs/audit_repro.py` was run against the baseline commit (`main` @ `ab8abbc`, in a temporary git worktree) and against the hardened branch. Phone checks R8/R9 run with live calls **enabled** and correctly signed requests (the attacker's best case), so they test the gates themselves, not just the off-by-default switch. For each fix, the fix was removed temporarily and at least one test failed ("mutation check").

| Finding | Baseline | Hardened | Regression tests | Status |
|---|---|---|---|---|
| **H1** unauthenticated phone stream (R9) | REPRODUCED: accepted, 1 Gemini session | NOT REPRODUCED: closed 1008, 0 sessions | `tests/test_telephony.py` (20 new test cases, replacing 2 that relied on unsigned "local mode": ticket missing/tampered/expired/other call/replayed, unknown business, inactive plan, call limit, handshake signature missing/forged, live calls off, slot release) | **Fixed.** One part unverified, see below |
| **H2** concurrent double-booking (R1) | REPRODUCED: 2 confirmed rows | NOT REPRODUCED: 2nd booking refused | `tests/test_storage.py` 20-thread race; `tests/test_agent.py` two conversations / race lost | **Fixed** |
| **H3** Sheets bookings invisible (R2) | REPRODUCED: slot still offered, dashboard 0 | NOT REPRODUCED: slot gone, dashboard 1 | `tests/test_storage.py` mirror copy, mirror failure, test mode ignores SHEET_ID, real-data write guard, explicit Sheet import (pause until run, text-intact phones, skip, missing-credentials stays paused), CSV re-import on change, export with backup | **Fixed**: SQLite is the single source of truth; the Sheet gets a copy of each booking and is read only by the one-time `python storage.py import-sheet` upgrade step |
| M3 placeholder admin password (R6b) | REPRODUCED: 200 + access keys | NOT REPRODUCED: 503 | `tests/test_access.py` placeholder / 11 / 12 chars, weak password disables admin bearer tokens, placeholder email not seeded | **Fixed** |
| M4 open `/api/tts` (R5) | REPRODUCED: 200 for 200 KB | NOT REPRODUCED: 422 | session required (404 unknown), ≤1000 chars | **Fixed** |
| M5 unbounded payloads (R7) | REPRODUCED: 2 MB → 200 | NOT REPRODUCED: 422 | chat ≤2000 chars, voice ≤5 MB (413, never sent to the model) | **Fixed** for chat/voice/TTS; other bodies not individually capped |
| M6 no LLM timeout | static | client built with `HttpOptions(timeout=GEMINI_TIMEOUT_S·1000)` | `tests/test_agent.py` constructor spy | **Partly fixed**: requests are bounded (30 s default), but 429/5xx retries can still sleep up to ~75 s in total (`llm.py:_call_with_retry`); not exercised against a real stalled request |
| M9 secrets / brute force | static | `hmac.compare_digest` for admin key, business codes, password hashes | covered by access tests | **Partly fixed**: no attempt rate limits yet (TODOS.md) |
| L1 `/api/admin/login` 500 (R6a) | REPRODUCED: 500 | NOT REPRODUCED: 200/401 | `test_admin_login_endpoint_never_crashes` | **Fixed** |
| L2 TwiML injection via `From` (R8b) | REPRODUCED (signed request) | NOT REPRODUCED | `test_twiml_attributes_are_escaped` | **Fixed** |
| M1/M2 metrics (R3/R4) | REPRODUCED | REPRODUCED | none | **Open**: out of scope, TODOS.md |
| M7 dead air, M8 blocking loop | static | unchanged | none | **Open**: TODOS.md |
| M10 committed demo codes, M11 PII retention | static | unchanged (`bookings.db` now gitignored) | none | **Open**: M11 in TODOS.md |

**Not fully verified:**
1. **Media-stream handshake signature.** Twilio's documentation requires validating `x-twilio-signature` on Media Streams (lowercase header on websockets), but doesn't state the signed URL/parameters for the upgrade. VoxAgent checks the exact `wss://…/twilio/stream` URL from its TwiML with no parameters, and **rejects on mismatch** (decision D4). Correct behaviour is proven offline only against signatures we computed ourselves. The first real call is the verification step (`docs/SAFE_TESTING.md` §5). If Twilio signs differently, real calls are refused (fail closed), never silently accepted.
2. **No real Twilio, Gemini or Google Sheets traffic was exercised.** No Twilio account or keys exist in this environment, and none were used.
3. **Single-process assumption.** Stream tickets use a per-process key (decision D3); a multi-worker deploy would reject calls. Documented.

**Results on the hardened branch:** `python -m pytest tests -q` → 100 passed (baseline 58) on both Python 3.13.13 and 3.11.15. Per file: test_telephony 8→26, test_storage 4→15, test_agent 13→17, test_access 6→15; others unchanged. `bench.py` with 300 bookings: build an agent 0.09 ms, whole-window availability 0.09 ms, dashboard 0.24 ms.

**Bug introduced and caught during the work:** the first SQLite version computed the dashboard ETag before the database file existed, so the second poll saw a "changed" file and returned 200 instead of 304. The existing `tests/test_dashboard.py` caught it. Fixed by opening the DB before stamping it.

The sections below are the original Phase 0 audit, unchanged, kept as the baseline record.

---

## 1. Facts first

### 1.1 What this repository is

VoxAgent is an AI receptionist for Indian small service businesses. One channel-independent agent core (`agent.py`, `ReceptionistAgent`) has three tools (`check_availability`, `book_appointment`, `save_lead`) and is wrapped by five channels:

| Channel | File | Needs | Verified here |
|---|---|---|---|
| Terminal chat | `main.py` | Gemini key | Starts; exits with `RuntimeError: GEMINI_API_KEY is not set` (expected) |
| Push-to-talk voice | `voice_main.py` + `audio_io.py` + `tts.py` | Gemini key, mic, speakers, network (edge-tts) | Not run (needs key and hardware) |
| Live interruptible call | `live_main.py` | Gemini Live key, mic, headphones | Not run |
| Web portal + admin console | `server.py`, `web/index.html`, `web/admin.html` | Gemini key for conversations only | **Boots without a key**; `/`, `/admin`, `/logo.svg` → 200; auth gates → 401 |
| Phone (Twilio Media Streams) | `telephony.py`, `go_live.py` | Twilio account + number, public URL, Gemini key | Bridge logic exercised offline with fakes; no real calls placed |

**Every conversation path needs a Gemini API key.** With no key you can run the portal UI, the tests, the benchmark, and the dashboards, but you can't have a conversation.

### 1.2 Version-control status (blocker for "work on a dedicated branch")

- `git rev-parse --show-toplevel` → **`/Users/kaush`**. The enclosing repository is your **home directory**. `voxagent-main/` is untracked there (`?? ./`), so **the project has no git history on this machine**.
- The folder sits next to `voxagent-main.zip`, which suggests a GitHub "Download ZIP" (no `.git`). Any history lives upstream.
- The home-directory repo shows 30 deleted files under `../files (2)/` (an unrelated SciRAG project). I did not touch them.
- **Consequence:** I made no git operations. Creating a branch in the home-directory repo would mix VoxAgent with your whole home folder. See §6 for the decision you need to make.

### 1.3 Real architecture and dependency graph (from imports, not docs)

```
channels:  main.py ─┐  voice_main.py ─┐  live_main.py ─┐  server.py ─┬─ telephony.py ─ (twilio, lazy)
                    │                 │                │            ├─ auth.py   (sqlite3, smtplib)
                    ▼                 ▼                ▼            ├─ billing.py ─ storage.py
core:            agent.py ──► scheduling.py (pure)     │            └─ tts.py    (edge-tts)
                    │  └────► storage.py (yaml, csv, json, gspread lazy)
                    └───────► llm.py  (google-genai: GeminiLLM.send/transcribe, GeminiLive)
hardware:        audio_io.py (sounddevice, pygame lazy)   go_live.py (cloudflared/ngrok download)
```

- The documented seams hold: only `llm.py` imports `google-genai`, only `tts.py` imports `edge_tts`, and only `telephony.py`/`go_live.py` touch Twilio. This was verified by grep, and the FakeLLM tests confirm it.
- **Persistence is split, which the docs only partly reflect.** Bookings go to Google Sheets or `bookings.csv`, leads to `leads.csv`, call logs to `calls/<client>/*.json`, client configs and billing state to `clients/*.yaml`, and accounts/tokens/resets to **SQLite** `voxagent.db` (`auth.py:9`). README §"Capacity" says "Storage is CSV/JSON", which is stale.
- **Persisted transcripts are flattened text.** `agent.history` is a clean structured list (roles, tool calls, tool results; format documented in `llm.py:7-21`), but `storage.log_call_from_agent` persists only `agent.transcript_text()` (`storage.py:237`), a human-readable string with tool results rendered via Python `repr`. **This matters for the reframe** (§5).

### 1.4 Working features vs. stubs vs. aspirational docs

| Claim (README/CLAUDE.md) | Status | Evidence |
|---|---|---|
| Text receptionist with auto-booking | **Works** (unit-level, FakeLLM) | `tests/test_agent.py` 13 tests pass |
| Slots generated from a rule, never expire | **Works** | `scheduling.py`; `tests/test_scheduling.py` pass |
| Multi-tenant per-client YAML | **Works** | 2 clients in `clients/` |
| Portal access control (bearer / business code / admin key) | **Works**, with gaps in §3 | `tests/test_access.py`, `test_auth.py` pass; smoke test 401/200 |
| Dashboard single request + ETag/304 | **Works** | `tests/test_dashboard.py` |
| Phone calls via Twilio | **Code-complete, never exercised end-to-end here** | Bridge tested with FakeLive. A real call needs the owner's Twilio account |
| "Evals are the quality gate" | **Exists, needs paid/free Gemini quota; not run** | `evals/run_evals.py`, 10 scenarios, substring checks only |
| Conversion metric on dashboard | **Incorrect** | R3, R4 below |
| Google Sheets booking store | **Writes work; reads never consult it** | R2 below |
| "One real conversation costs ₹1–2 paid"; "free key ≈ 20 req/day" | **Unverified claims.** No cost or token accounting exists anywhere in code | grep: no usage/token/cost fields |
| Stage 4/5 (multilingual Sarvam voices, campaigns) | Not started (as documented) | — |

### 1.5 External services, secrets, costs, hardware

| Dependency | Used by | Cost | Secret | Notes |
|---|---|---|---|---|
| Gemini API (`gemini-2.5-flash`, `gemini-2.5-flash-native-audio-latest`) | all conversations, STT | Free tier with quota; paid beyond | `GEMINI_API_KEY` | The `-latest` alias can change model behaviour under you (`llm.py:43`) |
| edge-tts | `tts.py`, `/api/tts` | Free | none | Unofficial client for Microsoft's Edge read-aloud service: no SLA, can break without notice (hypothesis about future risk, not observed) |
| Google Sheets (gspread) | bookings (optional) | Free | `credentials.json`, `SHEET_ID` | See R2 |
| Twilio | phone | Paid (number + per-minute) | `TWILIO_*` | Never invoked by tests |
| cloudflared / ngrok | `go_live.py` | Free | `NGROK_AUTHTOKEN` optional | **Downloads Windows `.exe` from `releases/latest` with no checksum** (`go_live.py:39,62`) |
| SMTP | password-reset email (optional) | Free (Gmail app password) | `SMTP_*` | — |
| Google Fonts | web pages | Free | — | External request on every page load |

**Hardware/platform:** the tooling is Windows-specific: `run.bat`, `.venv\Scripts\python.exe`, `cloudflared-windows-amd64.exe`, `ngrok-...-windows-amd64.zip`, and `.claude/launch.json` points at `C:\Users\…\vox agent\…` plus two unrelated projects. **You are on macOS**, so `run.bat` and `go_live.py` don't run here as written. The Python code itself is portable (tests pass on macOS).

---

## 2. Baseline results (before any modification)

Environments were created **outside the repo** (scratch virtualenvs via `uv`) so the baseline didn't modify the project. No `.env` exists, so no secrets were present or printed.

| Check | Command | Result |
|---|---|---|
| Tests, Python 3.13.13 | `python -m pytest tests -q` | **58 passed**, 3 warnings, 3.1 s |
| Tests, Python 3.11.15 (stated minimum) | same | **58 passed**, 4 warnings, 2.3 s |
| Warnings | — | FastAPI `on_event` deprecated (`server.py:46`); stdlib `audioop` deprecated on 3.11–3.12 (`telephony.py:30`); Starlette TestClient/httpx deprecation |
| Test side effects | `ls` after run | None. Tests redirect storage and the auth DB to temp dirs |
| Coverage | `pytest --cov=.` | **66 % total**. `llm.py` 23 %, `telephony.py` 66 %, `server.py` 75 %; `main/voice_main/live_main/audio_io/go_live/bench` 0 % |
| Lint (defaults) | `ruff check .` | 34 findings: 12 blind `except Exception`, 12 unused `noqa`, 5 import order, 3 `try/except/pass`, 1 unused import (`tests/conftest.py:9`), 1 B008 |
| Lint (security rules) | `ruff check --select S` | Non-test: 2× `subprocess` (go_live, expected), 1× `urlopen` (go_live), 3× `try/except/pass` (`go_live.py:112,130`, `telephony.py:276`) |
| Types | `mypy --ignore-missing-imports *.py` | 17 errors, mostly Optional-narrowing noise in `llm.py`/`go_live.py`; one real signature mismatch `storage.booked_pairs` returns `frozenset` while annotated `set` (`storage.py:147`, harmless) |
| Known CVEs | `pip-audit -r requirements.txt` | **No known vulnerabilities** (resolved versions: fastapi 0.143.0, starlette 1.8.0, google-genai 2.30.1, twilio 9.12.0, edge-tts 7.2.8) |
| Benchmark | `python bench.py` | All paths ≈ 0.01 ms. **Not meaningful:** the bench runs against empty data (no call logs, no bookings) and skips the auth path unless `ADMIN_EMAIL` is set |
| Server boot, no key | in-process TestClient | Boots; logs `warm-up skipped: GEMINI_API_KEY is not set` |
| CI | — | **None** (no `.github/`, no lint/type config, no `pyproject.toml`) |
| Evals | `evals/run_evals.py` | **Not run.** Needs a Gemini key and quota |

**Note:** dependency versions are unpinned (`>=` only), so this baseline may not reproduce on a future install.

---

## 3. Findings

Severity reflects impact on what CLAUDE.md ranks first ("never embarrass a client in front of their customer"), plus security when the server is internet-exposed, which `go_live.py` does by design (it tunnels the **whole** app, portal and admin included, to a public URL).

Reproduction IDs (R#) refer to `docs/audit_repro.py`. Run it from the repo root: `python docs/audit_repro.py`. It's fully offline and uses temp storage.

### High

**H1. Phone websocket is unauthenticated and bypasses billing.** *Reproduced (R9)*
`/twilio/stream` (`telephony.py:229-257`) accepts any websocket and trusts `client_id` from the client-supplied `start.customParameters`. The billing check only exists on `/twilio/voice` (`telephony.py:206`). Observed: for a client whose plan expired in 2000, an unauthenticated websocket opened **1 Gemini Live session**. Impact once exposed via `go_live.py`: anyone can open paid model sessions against any tenant and make bookings or leads in their data. *Fix direction:* sign/verify a one-time stream token issued in the TwiML, re-check `billing.client_active`, and validate `client_id` against known clients.

**H2. Two concurrent conversations can book the same slot.** *Reproduced (R1)*
Each `ReceptionistAgent` snapshots availability at construction (`agent.py:146`) and only removes the slot from **its own** copy (`agent.py:321`). `storage.save_booking` writes without re-checking. Observed: two agents both returned `confirmed` for 2026-10-14 09:30, leaving 2 rows. Any two overlapping calls or web sessions can trigger this. The existing test `test_double_booking_same_slot_fails` only covers a single agent. *Fix direction:* an atomic check-and-insert in storage (e.g., SQLite with a unique `(client_id, date, time)` constraint).

**H3. In Google Sheets mode, bookings are invisible to availability, the dashboard, and evals.** *Reproduced (R2)*
`save_booking` writes to the Sheet **instead of** the CSV (`storage.py:127-133`), but `booked_pairs` and `read_bookings` only read the CSV (`storage.py:136-147`). Observed: after a Sheet booking, a new conversation still offered the same slot, and the dashboard showed 0 bookings. Consequences: guaranteed double-booking across conversations, the dashboard under-reports, and `evals` `bookings:` checks fail. Also *static*: `evals/run_evals.py:76-79` redirects CSV paths but not `SHEET_ID`, so with Sheets configured **evals write test bookings into the real business Sheet**. That contradicts its docstring ("real bookings/leads are untouched").

### Medium

**M1. Conversion metric counts failed booking attempts.** *Reproduced (R3)*
`server.py:556` (and `server.py:307` for admin) counts a call as converted if the substring `book_appointment` appears in the transcript, and failed attempts are logged too. Observed: 1 call, 0 bookings, **conversion 100 %**. This is a headline sales metric shown to owners.

**M2. Phone and live calls lose tool activity, and the turn count is inflated.** *Reproduced (R4)*
`TwilioBridge.pump_gemini` (`telephony.py:154-162`) and `live_main.py:81-87` execute tools but never append them to `agent.history`. `finish()` inserts `[caller id: …]` as a *user* turn (`telephony.py:181`). Observed: 1 real booking, conversion 0 %, `turns=2` for a one-exchange call. Phone transcripts can't show *why* a booking happened. That's the exact evidence a diagnostics product needs.

**M3. `.env.example` placeholder admin credentials work verbatim.** *Reproduced (R6b)*
`ADMIN_PASSWORD=choose_a_strong_password` (`.env.example:6`) is accepted (`/api/admin/overview` → 200, response includes every business's `access_key`). `ensure_admin_seed` will likewise create `you@example.com` as an admin with that password (`auth.py:150-164`). `copy .env.example .env` is the documented setup step. *Fix direction:* refuse to start, or disable admin, while placeholders are present.

**M4. Unauthenticated, unbounded `/api/tts`.** *Reproduced (R5)*
`server.py:541-546` has no auth and no length limit. Observed: a 200 KB text request → 200. When public, this is a free TTS proxy on your IP and an easy way to tie up worker threads (the synthesis is a blocking network call).

**M5. Unbounded request payloads.** *Reproduced (R7) / Static*
`ChatRequest.message` has no max length; a 2 MB message → 200 and is re-sent to the LLM on every later turn (`agent.py:208`), which costs quota and money. `/api/voice` reads the whole upload into memory with no limit (`server.py:535`). The repo has no bounded-payload checks anywhere.

**M6. LLM calls have no timeout; retries block for up to ~75 s.** *Static*
`generate_content` is called with no request timeout (`llm.py:235`). Retries sleep up to 25 s × 3 (`llm.py:130,249-251`) inside a sync handler. On a voice/phone path this is silence the customer hears. Not reproduced (needs the real API).

**M7. A failed model stream leaves the phone call in silence.** *Static*
`twilio_stream` runs `pump_gemini` as a task but only awaits `read_twilio()` (`telephony.py:265-269`). If the Gemini stream raises or ends (network drop, session limit), the exception is never observed and Twilio audio keeps being read until the caller hangs up. Not reproduced (needs a live session).

**M8. Blocking I/O inside the async phone loop.** *Static*
Tool execution in `pump_gemini` is synchronous (`telephony.py:158`). In Sheets mode `save_booking` makes network calls (`storage.py:167-168`), which stalls the event loop for **every** concurrent call during a booking.

**M9. Low-entropy codes with no rate limiting.** *Static*
Business access codes are `VX-` + 3 random bytes = 24 bits (`server.py:459`). Password-reset codes are 24 bits valid for 60 min (`auth.py:247`). No endpoint limits attempts (`/api/portal/login`, `/api/auth/reset`, `/api/auth/login`). Secret comparisons use `==` rather than constant-time (`server.py:186,254,426`). The password minimum is 6 characters (`auth.py:144`).

**M10. Business codes are committed in the repo.** *Static, factual*
`clients/demo_clinic.yaml:2` (`VX-84KQ2N`) and `clients/lakshmi_beauty_salon.yaml:2` are in the source tree, and README repeats one. Verified: `X-Client-Key: VX-84KQ2N` → dashboard 200. These are demo clients, but if they're deployed as-is, the codes are public.

**M11. PII stored unredacted with no retention policy.** *Static*
Names, phone numbers, and caller IDs land in `calls/*.json`, `leads.csv`, `bookings.csv`, and the Sheet. Server logs `print` full booking details (`agent.py:322-325`). No redaction, retention, or deletion path exists.

### Low

| ID | Finding | Evidence | Status |
|---|---|---|---|
| L1 | `/api/admin/login` returns **500 for every input**: `require_admin()` is called directly, so `authorization` defaults to a `Header` object and `.startswith` crashes | `server.py:258-260`, `:170`; no UI or test calls it | Reproduced (R6a) |
| L2 | TwiML built by f-string: an unescaped `From` injects XML when signature validation is off (no `TWILIO_AUTH_TOKEN`). Injection via `client_id` was **not** reproduced (an unknown client fails the billing check first) | `telephony.py:215-223` | Reproduced (R8b) / Not reproduced (R8a) |
| L3 | `sessions` dict mutated from the threadpool without a lock; `purge_idle_sessions` iterates it, so "dict changed size" is possible under concurrency | `server.py:74,203-207` | Static, plausible |
| L4 | One customer can book every slot (no per-phone or per-conversation booking cap), via a prompt-injected or abusive caller | `agent.py:295-334` | Static, plausible; needs a real LLM |
| L5 | Prompt cache keyed on `id(cfg)`, so id reuse after GC could serve a stale prompt | `agent.py:169` | Static, unlikely |
| L6 | No structured logging, run IDs, or trace IDs; errors go to `print` | all modules | Static |
| L7 | `go_live.py` downloads executables from `releases/latest` with no checksum or pinning | `go_live.py:39-44,62,94` | Static |
| L8 | All deps unpinned; desktop-only `pygame`/`sounddevice` are core requirements for a server | `requirements.txt` | Static |
| L9 | Deprecated APIs: `@app.on_event`; `audioop` (handled on 3.13 via `audioop-lts`) | test warnings | Reproduced |
| L10 | Stale docs: README opens "this is Stage 1"; `evals/scenarios.yaml:15` cites a 2026-07-09 slot list; README says storage is CSV/JSON (auth is SQLite) | files cited | Static, factual |
| L11 | Eval checks are case-insensitive substrings, e.g. `"deal"` also matches "ideal" (`scenarios.yaml:34`) | `evals/run_evals.py:100-104` | Static |
| L12 | No CI; 0 % coverage on CLI channels; `bench.py` measures empty data | §2 | Reproduced |

### Not defects (checked and cleared)

- **XSS in the portal:** user data is rendered with `textContent`/`createElement`; the only `innerHTML` with interpolation is the chart, which receives numbers only (`web/index.html:696-717`).
- **Provider isolation:** holds (grep).
- **Prompt template injection via `.format`:** client values are substituted into the template, not used as the format string, so braces in owner data are safe (`agent.py:178`).
- **Password hashing:** salted PBKDF2-SHA256, 200k iterations (`auth.py:137-140`).
- **Twilio signature validation:** works when the token is set (`tests/test_telephony.py:167`).

---

## 4. Latency and cost risks (product-relevant)

- **Latency on the customer's path:** blocking retries with no timeout (M6), blocking Sheet writes in the async loop (M8), and edge-tts as a blocking network call per reply (`tts.py:68`). The good work already done (shared client, caches) is real but unmeasured under data load (L12).
- **Cost visibility: none.** No token counts, no per-call cost, no ledger. "₹1–2 per conversation" is an unverified README claim. Gemini responses carry usage metadata that is currently discarded in `llm.py:_normalize`.

---

## 5. What to preserve and what to replace (input to Phase 1/2, not decisions)

**Preserve (assets for a reliability/diagnostics product):**
- **The neutral message format** (`llm.py:7-21`): role-tagged turns plus tool calls and tool results. This is already a good canonical conversation schema.
- **The FakeLLM seam** (`tests/conftest.py:57-68`): proves deterministic, key-free replay is possible today.
- **`evals/`**: an embryonic evaluator (scenario YAML, checks, JSON report under `evals/results/`). It's the seed of the new product, but its checks are substring-based (L11) and need a live model.
- **Tool validation errors written for the model** (`agent.py:295-345`) and the rule-based scheduler (`scheduling.py`).
- **Test discipline:** 58 fast, hermetic tests.

**Candidates for replacement or extension:**
- Persist **structured** history (with tool calls and results, M2) alongside or instead of `transcript_text()`. Without it, there's no evidence to link findings to.
- CSV + Sheets dual store → one SQLite store (stdlib, already used by `auth.py`) with constraints. This fixes H2/H3 at the root.
- Substring metrics → computed from structured tool results (fixes M1/M2).
- `print` → structured logs with run and trace IDs (L6).
- Windows-only launch tooling → cross-platform commands.

**Observation for the product challenge:** the codebase's own history is a list of exactly the failure classes the new vision targets. Silently expired slots, a tool hiding slots from the model, a conversion metric that lies (M1), and transcripts missing tool evidence (M2) all happened, and each was caught late or not at all. That's a hypothesis for Phase 1 to test, not evidence of market demand.

---

## 6. Blockers and decisions needed from you

1. **Version control (blocks "dedicated branch").** Options: (a) `git clone` the upstream VoxAgent repo, if you have one, and work there with full history (recommended); or (b) `git init` inside `voxagent-main/` and commit this snapshot as the baseline. Don't use the home-directory repo.
2. **Scope of fixes.** H1–H3 affect the existing receptionist product. The prompt says to prove one new workflow first. Decide whether to fix H1–H3 before Phase 3 or record them as known defects. My recommendation: fix H2/H3 only if the receptionist stays a demo surface, and gate H1 by never running `go_live.py` until it's fixed.
3. **Evals need a key.** The quality gate can't run without Gemini quota. The Phase 3 MVP (transcript import → deterministic checks) is designed to need none.
4. **Tooling not available here:** the GitHub MCP connector failed to connect this session (auth header error). Not needed for Phase 0.

## 7. How to reproduce this audit

```bash
uv venv -p 3.13 /tmp/vox-venv && VIRTUAL_ENV=/tmp/vox-venv uv pip install -r requirements.txt ruff mypy pip-audit pytest-cov
/tmp/vox-venv/bin/python -m pytest tests -q            # 58 passed
/tmp/vox-venv/bin/python docs/audit_repro.py           # R1–R9, offline
/tmp/vox-venv/bin/ruff check .                         # 34 findings
/tmp/vox-venv/bin/mypy --ignore-missing-imports *.py   # 17 errors
/tmp/vox-venv/bin/pip-audit -r requirements.txt        # no known CVEs
```
