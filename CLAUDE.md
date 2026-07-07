# VoxAgent

AI receptionist for Indian small service businesses (clinics, salons, coaching institutes).

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
- **Stage 3 (later):** Real phone number via Vapi or Pipecat+Plivo, inbound + outbound.
  Blocked on the owner creating a telephony account (Vapi trial recommended first;
  Indian numbers need business KYC via Exotel/Plivo — defer until a real client).
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
- Providers (one-file swaps): llm.py (ALL Gemini code: chat, STT, Live),
  tts.py (ALL edge-tts code).
- Persistence: storage.py (ALL disk I/O: bookings Sheet/CSV, leads.csv,
  calls/<client_id>/*.json). Nothing else touches paths.
- Tests: tests/ — pytest, no network/key needed (FakeLLM proves the llm seam).
  Run `python -m pytest tests -q` after changes to core files.

## Tech stack

Python 3.11+, google-genai SDK (model: `gemini-2.5-flash`, free tier), gspread +
google-auth for Google Sheets, PyYAML, python-dotenv. Stage 2 added (owner delegated
the choice): edge-tts (free neural TTS, no key), sounddevice (mic), pygame (mp3
playback). Nothing else unless justified to the owner first.

## Owner

Sai, B.Tech AI student. Explain WHY for every architectural decision as you build —
teach, don't just generate. Ask before adding anything not in the spec.
