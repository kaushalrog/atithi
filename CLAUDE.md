# Atithi (codebase: VoxAgent)

Product name since 2026-10-20: **Atithi** ("Atithi Devo Bhava", the guest is God;
tagline "Every caller, welcomed."). The rename is UI and docs only: code identifiers,
env vars (`VOXAGENT_*`), file names and the `voxagent_auth` browser key keep the old name.

AI receptionist for any Indian business that takes bookings (clinics, salons, restaurants, gyms, coaching centres, repair shops...). `business_type` and `booking_word` in the client YAML adapt the prompt and copy.

**Long-term vision:** a voice agent that answers/makes phone calls in multiple languages
(English, Telugu, Hindi), books appointments automatically, and logs every conversation.

## Stages

- **Stage 1 (DONE 2026-07-07):** Text-based receptionist agent with auto-booking.
- **Stage 2 (DONE 2026-07-07):** Mic input + voice output. STT = Gemini audio
  understanding (in llm.py; Deepgram/Sarvam arrive with streaming in Stage 3).
  TTS = edge-tts (free Microsoft neural Indian voices, no key) behind tts.py —
  same one-file swap pattern as llm.py. Hardware I/O isolated in audio_io.py.
- **Stage 2.5 (DONE 2026-07-07):** Real-time interruptible voice call via the Gemini
  Live API (`gemini-2.5-flash-native-audio-latest`, free tier). GeminiLive class in
  llm.py normalizes Live events; live_main.py streams mic/speaker with sounddevice.
  Server-side VAD + barge-in — the same conversational architecture Stage 3 will
  run over a phone line.
- **Stage 2.75 (DONE 2026-07-07):** Business portal (the SaaS face of VoxAgent,
  aimed at the business OWNER, not their customers) — server.py (FastAPI, port
  8765) + web/index.html. Self-service onboarding form writes clients/<id>.yaml
  (slots generated from chosen days/hours/gap); dashboard with stats (calls,
  minutes talked, bookings, call→booking conversion), call history with
  transcripts (one JSON per call in calls/<client_id>/, gitignored), bookings
  table; and a test-call widget (browser mic + edge-tts replies) until Stage 3
  brings real numbers. This FastAPI app is the base for Stage 3 webhooks.
- **Stage 3 (CODE-COMPLETE 2026-07-07):** Real phone calls via Twilio Media
  Streams — telephony.py holds ALL Twilio code (inbound webhook -> TwiML
  <Connect><Stream>, websocket audio bridge with mulaw 8k <-> PCM 16k/24k
  conversion via audioop-lts, outbound calls from /admin, signature
  validation, per-client number mapping via `twilio_number` in the YAML).
  Waiting ONLY on the owner: Twilio account/number/keys + PUBLIC_BASE_URL in
  .env (SETUP.md Part 3). Owner explicitly owns: telephony purchase + clients.
- **Stage 4 (later):** Multilingual voices (Telugu/Hindi via Sarvam), parallel outbound campaigns.
- **Stage 5 (later):** Dashboard for transcripts, extracted lead details, and bookings.

## Architecture principles (do not violate)

1. **Multi-tenant from day one:** business knowledge lives in a per-client config file
   (`clients/<client_id>.yaml`), NEVER hardcoded in Python. One prompt template with slots:
   `{business_name}`, `{services_and_prices}`, `{timings}`, `{address}`, `{faq}`,
   `{policies}`, `{fallback_instruction}`.
2. **All secrets in `.env`**, loaded with python-dotenv. `.env.example` has placeholder keys
   (`GEMINI_API_KEY`, `GOOGLE_SHEETS_CREDENTIALS_PATH`, `SHEET_ID`). `.env`,
   `credentials.json`, and `*.csv` are gitignored. Never print or commit real keys.
3. **The agent core** (conversation loop + tool handling) must be a clean class independent
   of the input channel (terminal now, websocket audio later). Terminal I/O is just a thin
   wrapper around it.
4. **Anything that changes in real time** (slot availability) is a TOOL CALL, never prompt
   text. Static facts go in the system prompt.
5. **Keep it simple:** no RAG, no vector DB, no agent frameworks (no LangChain). The owner
   is a student learning this — prefer readable code over clever code.
6. **Wrap the LLM behind a single small class** (`llm.py`) with one method:
   `send(messages, tools) -> response`. All Gemini-specific code lives ONLY in that file,
   so we can swap providers later by rewriting one file. The rest of the codebase must
   never import google-genai directly.

## Architecture map

- Channels (thin): main.py (terminal), voice_main.py (push-to-talk),
  live_main.py (Gemini Live call), server.py + web/index.html (portal).
- Core: agent.py — ReceptionistAgent, 3 tools (check_availability,
  book_appointment, save_lead). Tools validate inputs and return errors the
  model can act on (bad slot -> offers alternatives; short phone -> re-confirm).
- Availability: scheduling.py — a client YAML stores the RULE
  (`schedule:` days/ranges/gap/horizon), never dated slots. Dated slots
  silently expired once and the agent lost the ability to book anything for
  two months; a rule cannot expire. Past times are never offered.
- Providers (one-file swaps): llm.py (ALL Gemini code: chat, STT, Live),
  tts.py (ALL edge-tts code). ONE shared genai client for the process —
  constructing it costs ~780 ms, so it is built at server startup, never
  per conversation.
- Persistence: storage.py (ALL disk I/O: bookings.db SQLite, leads.csv,
  calls/<client_id>/*.json, plus one trace per call in calls/<client_id>/traces/
  for the voxcheck checker — see docs/ARCHITECTURE.md). Nothing else touches
  paths. Every channel runs tools through agent.run_tool; streaming channels
  (phone, live) record turns with agent.TurnRecorder. bookings.db is the
  single source of truth for bookings; a partial UNIQUE index allows one
  confirmed booking per slot (the double-booking guard). Google Sheets
  receives a copy of each booking; it is read only once, by the explicit
  `python storage.py import-sheet` upgrade step (new bookings pause until
  then if SHEET_ID is set). Rollback: `python storage.py export-csv`. Every file is
  parsed once and cached until it changes (our writes invalidate exactly;
  outside edits are caught by an mtime+size check). **Cached values are
  shared — treat them as read-only and copy before mutating.**
- Instrumentation: perf.py (stdlib, no disk): spans/events/gauges with a
  monotonic clock, allowlisted labels, a random per-conversation id, fixed
  memory; `/api/admin/perf` shows them, VOXAGENT_PERF_LOG=<path> adds a JSONL
  log written by storage.py's bounded background thread. The Sheets copy is a
  bounded background queue too, never on the call path. Phone calls run
  blocking work (tools, agent setup, record save) on telephony's call-I/O
  pool, never on the shared event loop. `python bench_load.py --suite full`
  is the offline fake-provider load benchmark (docs/perf/).
- Customer texts: notify.py (booking confirmed/moved/cancelled + day-before
  reminders via `python notify.py reminders`) on a bounded background queue;
  telephony.send_sms is the only sender. OFF unless ENABLE_SMS=true: until then
  every text is a dry-run line in notifications.jsonl (gitignored, PII).
- Owner tools (portal): Settings (services, prices, hours, closed dates,
  languages, texts, website chat), Questions (unanswered-question inbox ->
  FAQ), lead follow-ups + CSV export, cancel/reschedule. Website chat is the
  only PUBLIC surface: /widget.js + /chat iframe + /api/public/*; off per
  business by default, rate-limited per IP, capped per business per day,
  and its sessions can't use /api/voice or /api/tts.
- Safety: VOXAGENT_ENV=test (tests, evals) disables the Sheets copy and makes
  writes to real data files raise. Live phone calls are off unless
  ENABLE_LIVE_CALLS=true; see docs/SAFE_TESTING.md before enabling.

## Performance rules

- `python bench.py` measures the hot paths offline. Run it after touching
  agent.py, storage.py, auth.py, llm.py, perf.py or scheduling.py.
- Anything on the path between a caller speaking and the agent answering is
  latency the customer hears. Never construct a provider client, parse a
  YAML, or scan a CSV inside that path.
- The dashboard is ONE request (`/api/dashboard`) with an ETag; the periodic
  refresh answers 304 with no body when nothing changed.
- Access control: per-business codes (access_key in each client YAML,
  X-Client-Key header) lock owners to their own data; ADMIN_PASSWORD
  (X-Admin-Key) opens everything. Portal has a login gate; /admin
  (web/admin.html) is the platform console with system-status checks and
  the business-code list.
- Tests: tests/ — pytest, no network/key needed (FakeLLM proves the llm seam).
  Run `python -m pytest tests -q` after changes to core files.

## Tech stack

Python 3.11+, google-genai SDK (model: `gemini-2.5-flash`, free tier), gspread +
google-auth for Google Sheets, PyYAML, python-dotenv. Stage 2 added (owner delegated
the choice): edge-tts (free neural TTS, no key), sounddevice (mic), pygame (mp3
playback). Nothing else unless justified to the owner first.

## Owner & intent

Sai, founder. **VoxAgent is a real startup, not a class project.** Build to
production standards and prioritize in this order:
1. Reliability — the agent must never embarrass a client in front of their
   customer (evals in `evals/` are the quality gate; run them before demos).
2. Demo-to-sale path — features that help win a paying pilot beat features
   that are merely interesting.
3. Unit economics — know what a conversation costs before pricing anything.

Sai is also still learning: explain WHY for every architectural decision —
teach while building. Ask before adding anything outside the agreed direction.

## Skill routing

When the user's request matches an available skill, invoke it via the Skill tool. Route only to skills in the session's available-skills list; answer directly for quick questions or small scoped edits.

Key routing rules:
- Product ideas/brainstorming → invoke /office-hours
- Strategy/scope → invoke /plan-ceo-review
- Architecture → invoke /plan-eng-review
- Design system/plan review → invoke /design-consultation or /plan-design-review
- Full review pipeline → invoke /autoplan
- Bugs/errors → invoke /investigate
- QA/testing site behavior → invoke /qa or /qa-only
- Code review/diff check → invoke /review
- Visual polish → invoke /design-review
- Ship/deploy/PR → invoke /ship or /land-and-deploy
- Save progress → invoke /context-save
- Resume context → invoke /context-restore
- Author a backlog-ready spec/issue → invoke /spec

