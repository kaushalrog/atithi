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

## Tech stack

Python 3.11+, google-genai SDK (model: `gemini-2.5-flash`, free tier), gspread +
google-auth for Google Sheets, PyYAML, python-dotenv. Stage 2 added (owner delegated
the choice): edge-tts (free neural TTS, no key), sounddevice (mic), pygame (mp3
playback). Nothing else unless justified to the owner first.

## Owner

Sai, B.Tech AI student. Explain WHY for every architectural decision as you build —
teach, don't just generate. Ask before adding anything not in the spec.
