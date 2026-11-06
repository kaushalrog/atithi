# Atithi capability audit — what the code actually does today

**Repo:** `C:\Users\saire\OneDrive\Desktop\Workspace\05_Startup-Projects\Atithi`
**Pinned to commit `bdc8db9`** ("feat: caller memory — greet a returning customer by name"), audited 2026-10-25.
**Read-only audit.** No file in the repo was created, modified or deleted. Tests were not run (that would
write `__pycache__`/`.pytest_cache` into the repo); test counts below are static counts of `def test_` functions.

> **Caveat the reader must know:** the repo was being actively committed to *during* this audit. Between my
> first and last tool call, HEAD moved from `222d62e` → `5e81029` → `bdc8db9`, and two modules (`plans.py`,
> `memory.py`) went from untracked to committed. Line numbers in `telephony.py` and `server.py` shifted by
> ~5 lines mid-audit. Every citation below was re-verified against `bdc8db9`, but anything committed after
> that is outside this report.

---

## 1. Capability matrix vs Outpero

| # | Outpero capability | Atithi | Evidence | If not YES: what's missing, effort, where it hangs off |
|---|---|---|---|---|
| 1 | **Outbound speed-to-lead (<30 s from ad lead)** | **PARTIAL** | `telephony.start_outbound_call` (telephony.py:795) dials and the agent takes the call; `callbacks.run_due` (callbacks.py:37) is a real dialer with opening-hours gating, atomic claim (`storage.claim_callback`), 1-per-number-per-6 h and 30/business/day caps (storage.py:716-717) | No lead *intake*: the full route list has no POST that accepts a lead from Meta/Google (server.py routes end at `/api/leads/update`). Dialing is admin-only, one number at a time (`/api/admin/call`, server.py:566). The dialer polls every **60 s** (`CALLBACK_POLL_S = 60`, callbacks.py:34), so sub-30-s is structurally impossible today. Needs: signed per-business intake endpoint + immediate dial path. **M**, on `callbacks.py` + `telephony.py`. Blocked by TRAI/DLT compliance which `docs/STRATEGY.md` §7.1 flags as unverified. |
| 2 | **Bulk CSV campaigns with retry schedules** | **NO** | Only CSV *export* exists (`/api/export/{kind}.csv`, server.py:1284) | The `callbacks` table (storage.py:275-279) is the queue seed but has no attempt counter and no `next_attempt_at`; a failed row goes to status `failed` and `pending_callbacks` only selects `pending` — **one attempt, no retry**. Needs: campaign table, CSV upload endpoint, attempt/backoff columns, per-campaign caps. **M**, on `storage.py` + `callbacks.py`. |
| 3 | **Call recordings (audio) with playback** | **NO** | Zero hits for `record=`, `Recording`, `RecordingStatusCallback`, `.mp3` audio storage anywhere in `telephony.py`/`storage.py`/`server.py`. `TwilioBridge` (telephony.py:334) passes μ-law frames through `handle_twilio`/`pump_gemini` and discards them | Both audio directions already flow through one class. Writing them to a WAV alongside `calls/<client>/<id>.json`, plus a `/api/recording/{call_id}` route and an `<audio>` tag in `web/index.html`, is small. Alternative: Twilio's own `record=True` + status callback. **S–M**, on `telephony.py` (capture) + `storage.py` (path) + `web/index.html` (player). |
| 4 | **Sentiment scoring** | **NO** | No occurrence of "sentiment" in any `.py`/`.html` | No per-call sentiment or emotion signal anywhere. Cheapest route: one post-call pass over `record["transcript"]` on `storage._BackgroundQueue` (storage.py:182) so it never touches the call path. **S** if bundled with #5 in a single post-call extraction call. |
| 5 | **Structured lead extraction (intent, budget, requirement, next step)** | **PARTIAL (weak)** | `save_lead` takes only `name, phone, interest, note` — free text (agent.py:85-99). Stored to `leads.csv` + a follow-up status table (`lead_followups`, storage.py:266-270), shown in the portal Leads tab | No typed fields, so nothing is queryable or chartable; "3BHK, ~90 lakhs, site visit Sat" lands as one prose string. Two options: widen the tool schema (**S**) or a post-call extraction pass (**M**). On `agent.py` (schema) + `storage.py` (columns) + `web/index.html` (columns). |
| 6 | **Caller memory across calls** | **YES (phone only)** | `memory.recall` / `memory.brief_for` (memory.py:63, 147) read the business's own call log + bookings by last-10-digits, build a factual briefing (name, last-seen, upcoming appointment, "calls regularly"), 120-day lookback (memory.py:30); wired at telephony.py:708 | Phone path only. WhatsApp knows the sender's number (`telephony.twilio_whatsapp`) but never calls `memory.brief_for`; neither does website chat. Extending it is two lines. **S**, on `telephony.py` (`_wa_turn`) + `server.py` (`public_session`). Deliberately summary-only, never replays old transcripts (memory.py:9-15) — a good design, not a gap. |
| 7 | **CRM webhooks / custom API actions mid-call** | **NO** | No outbound HTTP to a customer endpoint anywhere. The only external write is the Google **Sheets** booking copy (`storage._copy_to_sheet`, storage.py:829) | Post-call webhook: one POST of the existing call record using the already-built bounded background queue (storage.py:182) + a `webhook_url` key in the client YAML. **S**, on `storage.py`. Mid-call custom actions: `TOOL_SCHEMAS` is a module-level constant shared by every business (agent.py:46), so per-business tool injection is an architectural change. **L**, on `agent.py` + `llm.py`. |
| 8 | **WhatsApp Business templates** | **PARTIAL** | `POST /twilio/whatsapp` (telephony.py:~967) runs the same `ReceptionistAgent`, signature-validated, per-sender rate-limited (20/10 min), 30-min session idle, records saved with channel `whatsapp` | **Replies only** — the module comment is explicit: "Atithi never starts a WhatsApp conversation". No templates, no business-initiated messaging, no media (a photo/voice note gets "I can only read text messages"). Templates need Meta/Twilio template registration + a send path. **M**, on `telephony.py` + `notify.py`. |
| 9 | **Google Calendar booking** | **NO** | Source of truth is SQLite `bookings.db` with a partial unique index (storage.py:251). Optional copy to a Google **Sheet**, not Calendar | `agent._check_availability` already carries the seam comment "Later stages replace this body with a real calendar lookup — the tool's name and schema stay the same" (agent.py:495-496). One-way push is easier than two-way sync (two-way means an external booking must invalidate `scheduling.available_slots`). **M**, on `agent.py` + `storage.py`. |
| 10 | **Knowledge base training** | **PARTIAL** | FAQ q/a pairs + policies + fallback typed into onboarding/settings and rendered into one prompt template (`agent._render_system_prompt`, agent.py:306); `note_unanswered_question` tool (agent.py:154) + Questions inbox closes the loop (`/api/questions/answer`) | No document/URL/PDF ingestion — the only `UploadFile` in the codebase is the test-call microphone (server.py:~915). Per CLAUDE.md principle 5 ("no RAG, no vector DB") this is a deliberate choice, not an oversight. A file-upload → FAQ-extraction step would be **M**, on `server.py` + `storage.py`. |
| 11 | **7 Indian languages** | **PARTIAL (4)** | `agent.LANGUAGES = {en, hi, te, ta}` (agent.py:193); `voices.LANGUAGES = ("en","hi","te","ta")` (voices.py:42); edge voices for all four (voices.py:118-123). `language_instruction` (agent.py:196) also handles Hinglish/Tenglish roman mixes | English + 3 Indian vs their 7. Text side is cheap: add codes to two tuples + voice ids. Quality side is not — needs real voices and listening tests (`voice_lab.py` exists for exactly this). **S** for the plumbing, **M** including provider keys and A/B. On `agent.py` + `voices.py`. |
| 12 | **Voice choice (Standard / Premium tiers)** | **PARTIAL** | `voices.py` is a real pluggable registry: edge (free, no key), Sarvam, ElevenLabs, Cartesia, each self-enabling when its env key appears (`Provider.available`, voices.py:102), with per-language preference order (voices.py:46-51) and fallback-down-the-order on any failure (`voices.synthesize`, voices.py:353) | Three problems. (a) The `voice:` YAML block is **not exposed in the UI** — it is absent from `BusinessRequest` (server.py:250) and `_settings_view` (server.py:728), so only hand-editing a YAML selects it. (b) `/api/tts` builds `EdgeTTS()` with **no config** (server.py:87) so a business's voice block is ignored on the portal path too. (c) See §3 overclaim 1: it does not reach the phone path at all. (d) No tier is priced. **S** to expose it in the portal; **L** to actually route cascaded TTS on a live phone call (needs switching `response_modalities` and streaming TTS→μ-law, i.e. `llm.py` + `telephony.py`). |
| 13 | **Self-serve signup with free credits** | **PARTIAL** | Signup is genuinely self-serve: `POST /api/auth/signup` (server.py:613) → `POST /api/business` (server.py:668) writes `clients/<id>.yaml`, links it to the account, and starts `billing.new_trial()` = **7 calendar days** (billing.py:26-29). Password reset incl. SMTP (auth.py:338) | "Free credits" don't exist — the trial is time-based, not minute-based. And the self-serve path stops short of a phone line: `twilio_number` is set by the platform (it is explicitly preserved, not editable, in `save_settings`, server.py:~771), so a new signup gets portal + browser test call + website chat but **no phone number** without the founder. `plans.py` defines 60 trial minutes but is unwired (next row). **S** to show trial minutes, **L** to self-provision a number (Twilio subaccounts + number purchase + DLT). |
| 14 | **Usage-based per-minute pricing** | **PARTIAL — written, tested, and dead** | `costs.py` meters every call: `cost_for` (costs.py:97) per-channel line items, written into every record at storage.py:~1052, with an honest `assumed` flag while any rate is a placeholder. `plans.py` has Trial/Clinic/Growth tiers, `usage()`, `invoice()`, `allowance()`, `channels()`, `price_check()` and a 3× margin rule, with 15 tests (`tests/test_plans.py`) | **Nothing imports `plans`** except its own test file (verified by grep across all `.py`/`.html`). Live billing is still flat: `billing.status` returns `BILLING_PRICE_INR` (default ₹1,999, billing.py:60) and `billing.client_active` is a pure date check (billing.py:38). No cost or credit figure appears anywhere in `web/index.html`. Concurrency is a global `MAX_CONCURRENT_CALLS` env var, not `plans.channels(client_id)`. **S — pure wiring**: `allowance()` into `telephony._business_problem` + `server._open_session`, `channels()` into `telephony.max_concurrent_calls`, `invoice()` into `/api/dashboard` + a card in the portal. |
| 15 | **Live dashboard: recordings / transcripts / credits per call** | **PARTIAL** | One ETag'd request `GET /api/dashboard` (server.py:~1007) returns stats, calls with chat-style transcripts incl. plain-word tool chips (web/index.html:1327+), bookings, leads, callbacks owed, open questions, billing, phone status, a 7-day chart, and the proof card "N of N promises backed by a real record" (web/index.html:959). Real outcomes come from tool results, not transcript grep (`record_outcome`, server.py:~952) | **No recordings** (#3) and **no credits/cost per call** — `record["cost"]` is computed and stored but never returned to the browser and never rendered. Surfacing it is **S** (one field in the `/api/dashboard` payload + one stat tile). On `server.py` + `web/index.html`. |

---

## 2. Top five gaps, ranked by (customer impact ÷ effort)

**1. Wire `plans.py` into the running system — S effort, already written and tested.**
This is the highest-ratio item in the repo because the work is done and switched off. `plans.py` computes
allowance, usage, overage, invoices and a 3× margin check, and has 15 passing tests; not one line of it is
imported by `server.py`, `telephony.py` or `billing.py`. Until it is wired, three separate things stay
broken at once: (a) the margin risk `docs/STRATEGY.md` §5 identifies — a clinic doing 600 min/month against
a flat ₹1,999 can cost more than it pays, and `costs.py` already knows that per call; (b) "free credits"
on signup, which needs `allowance()` at session/call start; (c) selling concurrency as channels, which needs
`channels(client_id)` instead of one global `MAX_CONCURRENT_CALLS`. Four call sites. Do this first.

**2. Call recordings + playback — S/M, and their own strategy doc calls it "table stakes".**
Owners want to listen, not read. The audio already passes through one class in both directions
(`TwilioBridge.handle_twilio` for inbound μ-law, `pump_gemini` for outbound), so capture is a buffer and a
file write next to the call record, which `storage.py` already owns exclusively. The dashboard already has
a per-call detail view to hang an `<audio>` player on. This is the single most visible "we match them"
feature per unit of work — and it is also the one that most needs the DPDP retention policy that
`TODOS.md` still has open, so pair it with a delete path.

**3. One post-call extraction pass → structured lead fields + sentiment — M, and it buys two matrix rows.**
Items #4 and #5 collapse into one job: after the call, run one model pass over the stored transcript on
the existing bounded background queue (`storage._BackgroundQueue`, storage.py:182 — off the call path by
construction, so zero added latency the caller hears) and write `intent / budget / requirement / next_step /
sentiment` into the record. The Leads tab, the CSV export and the follow-up status table already exist to
display it. This is what turns the dashboard from a log into something worth a monthly fee, which is
priority #2 in CLAUDE.md's own ordering (demo-to-sale path).

**4. Per-business post-call webhook — S, and it unblocks every business that already has software.**
A single POST of the existing call-record JSON to a `webhook_url` in the client YAML, queued on the same
background queue as the Sheets copy. ~30 lines in the one file that is allowed to do I/O. It converts a
hard "no, we don't integrate" into "yes, we post the call to your system", which is the answer that keeps
a deal alive. Note the *mid-call* version is genuinely **L** (per-business tools require breaking
`TOOL_SCHEMAS` out of being a module constant) — ship the post-call half and say so precisely.

**5. Fix the Telugu/Tamil voice on the phone path — L, but it is the one gap a customer hears in the first sentence.**
Ranked fifth only because of effort: it means taking Gemini off `response_modalities=["AUDIO"]` for those
languages and streaming a dedicated TTS back as μ-law, which touches both `llm.py` and `telephony.py`.
The *policy* for it is already written (`voices.plan`, `voices.use_cascaded_on_phone`) and completely
unused. In a Telugu-first market against a Telugu-first competitor, an English-accented Telugu voice loses
the call before the agent's quality matters — `docs/STRATEGY.md` §3 says exactly this and calls it "the bug".
Do the **S** slice first (expose the Gemini voice name in the portal; pass the business config into
`/api/tts`) so the owner can at least choose, then schedule the L.

---

## 3. Real advantages Atithi has that are NOT on the rival list (all verified in code)

1. **Proof, not promises — a pre-send claim check.** `proof.py` is pure (no disk, no clock, no model):
   `claims()` matches booked/cancelled/rescheduled/callback assertions with hedge-stripping
   (`_NOT_A_CLAIM`), `evidence()` reads what the tools actually returned, and `unbacked()` is called
   *inside* `agent.chat` before the reply leaves (agent.py:~381). The model gets exactly one nudge, which is
   never stored in history; a second failure sends `proof.SAFE_REPLY` instead. `report()` (proof.py:192)
   goes into every call record and `_proof_totals` (server.py:~983) renders "N of N promises backed by a
   real record" in the portal. Nothing on the rival list is comparable, and it is the stated positioning.
2. **Double-booking is structurally impossible, not an integration detail.** A partial unique index —
   `one_confirmed_booking_per_slot ON bookings(client_id, date, time) WHERE status='confirmed'`
   (storage.py:251) — plus `reserve_booking` returning `None` on conflict so the agent re-offers
   (agent.py:~543). Two simultaneous callers cannot both get 10:30, regardless of model behaviour.
3. **Unanswered-question inbox.** `note_unanswered_question` (agent.py:154) + a `one_open_question` unique
   index with a repeat counter (storage.py:262) + `/api/questions/answer` turning an answer into a
   permanent FAQ. This is the inverse of "knowledge base training": the agent tells the owner what it
   *couldn't* answer rather than hallucinating. Competitor list has the upload half, not the feedback half.
4. **Machine-readable per-call traces, privacy-scoped.** `storage._write_trace` (storage.py:1162) writes
   timezone-aware turns, typed actions and a booking snapshot — with full rows only for *this* caller and
   other customers' slots reduced to `{date, time, status}` with no name or number. Wrapped so a trace
   failure never costs the call record.
5. **Honest cost metering with an "assumed" flag.** `costs.py` refuses to look precise: every report states
   which rates are placeholders and `docs/STRATEGY.md` §5 forbids pricing off them. Rare discipline, and it
   is the prerequisite for competing on usage pricing at all.
6. **Self-instrumenting latency/perf, privacy-allowlisted.** `perf.py` — stdlib only, fixed memory, random
   per-conversation id, label allowlist that *raises* in test mode so a PII leak fails a test; exposed at
   `/api/admin/perf`. Plus `bench_load.py`, a fake-provider load harness with failure injection.
7. **Human handoff + Indian missed-call callbacks.** `transfer_to_owner` → `agent.handoff` →
   `telephony.transfer_call` replaces the stream with a `<Dial>`; missed-call mode answers with a busy
   `<Reject>` (free for the caller, which is how Indian customers actually ask to be called back) and
   queues a callback. Both off by default behind their own env flags.
8. **Website chat widget as a second customer channel.** `/widget.js` + `/chat` iframe +
   `/api/public/*`, off per business by default, per-IP new-session limits, per-business daily turn cap, and
   widget sessions cannot reach `/api/voice` or `/api/tts`.
9. **Customer SMS with a dry-run default.** `notify.py` queues confirmed/moved/cancelled texts plus
   `python notify.py reminders`; with `ENABLE_SMS=false` every message is written to
   `notifications.jsonl` so the owner can read exactly what customers *would* get first.
10. **Test-mode blast radius of zero.** `VOXAGENT_ENV=test` makes any write to a real data file raise
    (`storage._guard_write`) and refuses to even open the real accounts DB (auth.py:85-88).
11. **Slots are a rule, not dated rows.** `scheduling.py` generates from `days/ranges/gap/horizon` with a
    30-minute lead time and never offers a past slot — a documented fix for a real two-month outage.
12. **Multi-tenant access control on three mechanisms** (bearer sessions, per-business `access_key`,
    admin password) with constant-time comparison, plus one-time HMAC stream tickets bound to a single
    Twilio CallSid (telephony.py:192-257) — a fix for a real audit finding where a stranger could open paid
    model sessions against any business.

---

## 4. Places the docs claim something the code does not deliver

Ordered by how much damage each would do in a live sales demo.

### 4.1 CRITICAL — a competitive latency number taken from a fake-provider benchmark and labelled "a real call"

> `docs/STRATEGY.md:64` — "**Latency.** They advertise 0.8–1.3s. Our Live path measured ~0.1–0.5s gaps **on a
> real call.** Verify under load, then say it loudly."

Contradicted by the repo's own two statements:

- `README.md:396` — "**No real Twilio, Gemini Live or Google Sheets traffic** has been exercised in
  development; everything was tested with fakes."
- `bench_load.py:7-14` — "driven by **FAKE** providers… Model 'thinking time' is a fixed, known sleep…
  These numbers say nothing about real Gemini/Twilio/Google latency. **Never quote them as call latency.**"

And by the data itself: `docs/perf/after.json` records `"model_think_ms": 250.0` — a hardcoded sleep — on
`"platform": "macOS-27.0-arm64"`. The ~0.1–0.5 s figure is Atithi's *own code overhead* above a simulated
model, not a call latency. Saying "we measured 0.1–0.5 s on a real call" to a prospect comparing against a
published 0.8–1.3 s is a claim the repo cannot support and the benchmark explicitly forbids. **Fix the
sentence before any demo; it is also the one line here that could later be called misrepresentation.**

### 4.2 HIGH — "matching neural voices" for Telugu/Hindi/Tamil is not true on the phone

> `README.md:66` — "**Speaks Indian languages.** It understands and answers Telugu, Hindi and Tamil with
> **matching neural voices** via edge-tts (free, no key)."

On a real phone call the voice is a Gemini prebuilt voice, never an edge-tts Indian voice:

- `telephony.py:713` — `live = GeminiLive(voice=voices.live_voice(agent.config))`
- `voices.py:54` — `DEFAULT_LIVE_VOICE = "Kore"`, and `voices.live_voice` returns it unless a business
  hand-edits a `voice:` block into its YAML (which no UI writes — absent from `BusinessRequest`, server.py:250).
- `voices.py:346` — `use_cascaded_on_phone()` exists to route Indian languages to a dedicated TTS and is
  **called from nowhere in production**; a grep across the whole repo finds exactly one caller,
  `tests/test_voices.py:99`.

The product's own strategy doc already states this plainly (`docs/STRATEGY.md:84-89`: web widget gets
`te-IN-ShrutiNeural`, real phone calls get `Kore`, Telugu quality "poor — an English-first voice attempting
Telugu", "That is the bug"). The README has not caught up. In a phone demo to a Telugu-speaking clinic this
is the first thing the buyer notices.

Secondary, same theme: even on the portal path the business's voice choice is ignored — `/api/tts` calls
`tts.synthesize_bytes(clean)` on the module-level `tts = EdgeTTS()` built with **no config**
(server.py:87), so `voices.synthesize(text, None)` falls through to the global preference order.
Provider selection works from env keys; *per-business* voice selection effectively does not.

### 4.3 HIGH — `voices.py`'s own docstring promises routing the phone path never consults

> `voices.py:18-21` — "**The routing policy** (`plan`): for each language, who should speak and **whether the
> phone call should stay on Gemini's native audio (fastest) or go through a dedicated Indian TTS
> (smoothest)**."

`plan()` does compute `native_ok`, and `use_cascaded_on_phone()` does wrap it — but `telephony.py` only ever
calls `voices.live_voice()`. The hybrid routing described in `docs/STRATEGY.md` §3 as "the fix
(recommended)" reads, in the code, as a shipped policy. It is dead code. A reader auditing the module
(including a future engineer, or the founder's co-founder) would reasonably conclude Telugu calls are
already cascaded. Either wire it or mark the function as not-yet-wired.

### 4.4 MEDIUM — `docs/ARCHITECTURE.md` says the trace work doesn't exist; it does

> `docs/ARCHITECTURE.md:3` — "**Status:** planned. **Nothing in the "new" boxes exists yet.**"

But traces are implemented and running: `storage._write_trace` (storage.py:1162) is called from
`log_call_from_agent` (storage.py:~1069) on every channel, `TRACE_VERSION = 1`, with the exact fields the
doc specifies. `README.md:50` correctly marks this "✅ Done and reviewed". Two docs in the same repo
disagree about whether a feature exists; a reader cannot tell which is current. (The *checker* half,
`voxcheck`, genuinely does not exist — there is no `voxcheck/` directory — and the README is honest about
that at line 52.)

### 4.5 MEDIUM — understatements that make the product look thinner than it is

These are the mirror image of overclaims: every one of them *loses* credit the code has earned, and each
makes the docs untrustworthy as a map of the system.

| Doc line | Says | Code |
|---|---|---|
| `README.md:260`, `README.md:331`, `CLAUDE.md:67` | "three tools" / "3 tools" | **Eight** tools in `TOOL_SCHEMAS` — `check_availability`, `book_appointment`, `save_lead`, `find_booking`, `cancel_booking`, `reschedule_booking`, `note_unanswered_question`, `transfer_to_owner` (agent.py:48-170) |
| `README.md:56`, `README.md:301` | "177 tests pass" | **349** `def test_` functions across 26 files in `tests/` (before parametrize expansion) |
| `README.md:65` | "Works on four channels" | Seven surfaces: terminal, push-to-talk, live mic, portal test call, real phone, **WhatsApp**, **website chat** |
| `README.md:394` (Known limitations) | "The conversion rate counts failed booking attempts… the dashboard fix is still pending" | **Already fixed.** `server.record_outcome` (server.py:~952) prefers `record["outcome"]`, written by `storage.call_outcome` (storage.py:1089) from real tool results; the transcript-grep rule survives only as a fallback for pre-fix records |
| `README.md:328-352` (Project structure) | Lists 20 files | Omits **8 modules**, several of them the differentiators: `proof.py`, `perf.py`, `notify.py`, `callbacks.py`, `voices.py`, `costs.py`, `memory.py`, `plans.py` |

### 4.6 Worth stating plainly, though the docs are technically honest

- **No phone call has ever demonstrably been completed.** `README.md:214` ("no real account was used in
  development") and `README.md:396` are honest, but the Status table's "✅ Code-complete" next to "Real
  phone calls via Twilio (inbound and outbound)" reads as ✅ at a glance. Supporting signal: the demo
  business is mapped to a **US** number (`clients/demo_clinic.yaml`: `twilio_number: '+16592517349'`), and
  `ENABLE_LIVE_CALLS` defaults to `false` in `.env.example`. Treat "it answers the phone" as unverified
  until `docs/SAFE_TESTING.md` §5 is actually done.
- **`plans.py` ships unreferenced.** Not a doc overclaim — no doc claims it is live — but a reader seeing
  Trial/Clinic/Growth tiers with 15 passing tests will assume usage pricing is in effect. It is not
  (§1 row 14). Say "computed, not enforced" wherever it comes up.

---

## 5. Ambiguities I could not resolve from the code

1. **Real-world voice quality and latency** cannot be established from this repo: no provider key was
   exercised, and every benchmark uses fakes. Any number quoted in a sale needs one real metered call first
   — which is also `docs/STRATEGY.md` §5's own "step zero".
2. **The `_HTTPProvider` request shapes for Sarvam / ElevenLabs / Cartesia are self-declared UNVERIFIED**
   (voices.py:144-147: "have not been run against a live key here"). They fail soft to edge-tts, so a wrong
   shape degrades rather than breaks — but "we support Sarvam voices" is untested.
3. **Whether `plans.py` / `memory.py` were intended to be live at `bdc8db9`** is unclear; both were
   committed during this audit and `CLAUDE.md` was still dirty in the working tree when I finished, so the
   architecture map may be mid-update.
4. **Google Sheets** is a one-way booking *copy* plus a one-time `import-sheet`, read exactly once. Whether
   that is intended to count as a "calendar integration" in a sales conversation is a positioning question,
   not a code question. It is not Google Calendar, and an external edit to the Sheet is invisible to
   availability.
