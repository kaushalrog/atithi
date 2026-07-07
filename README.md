# VoxAgent

An AI receptionist for Indian small service businesses — clinics, salons,
coaching institutes. The long-term goal is a voice agent that answers and makes
phone calls in English, Telugu, and Hindi, books appointments automatically, and
logs every conversation. It's being built in stages; **this is Stage 1**: a
text-based receptionist you chat with in the terminal, with real auto-booking
into Google Sheets (or a local CSV fallback).

## Quick start

Double-click **`run.bat`** — the portal opens in your browser, with the server
running minimized in the background (close its taskbar window to stop). On first
run it creates the virtualenv and installs everything automatically. You still
need `.env` with your `GEMINI_API_KEY` (see SETUP.md).

Other modes from a terminal: `run.bat text | voice | live | live-hd`.

## Run Stage 1 manually

```
cd "vox agent"
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
copy .env.example .env          # then put your GEMINI_API_KEY inside (see SETUP.md)
python main.py --client demo_clinic
```

You play a customer; the agent plays the receptionist of the demo dental clinic.
Commands: `/reset` (clear history), `/transcript` (save chat to `transcripts/`),
`/quit`. Transcripts also auto-save when you quit.

## Run Stage 2 (voice)

```
python voice_main.py --client demo_clinic
```

At the prompt, press **ENTER alone** to start talking and **ENTER again** to stop —
the agent transcribes you, replies in text, and speaks the reply out loud. You can
also just type (all `/` commands still work). Use `--mute` to skip the spoken audio.
Speak Telugu/Hindi/Tamil and it both understands you and answers in a matching
neural voice.

How voice fits the architecture: `agent.py` didn't change at all. The pipeline is
mic (`audio_io.py`) → Gemini STT (`llm.py`) → the same `ReceptionistAgent` →
edge-tts (`tts.py`) → speaker. STT/TTS are each isolated behind one small file,
exactly like the LLM, so Deepgram/Sarvam later means swapping one file each.

## Run Stage 2.5 (live call — no Enter key, interruptible)

```
python live_main.py                 # 🎧 wear headphones
python live_main.py --half-duplex   # no headphones (mic mutes while agent talks)
```

This is a real-time call over the Gemini Live API: just talk, the server's voice
activity detection figures out when you start and stop, and you can interrupt the
agent mid-sentence (barge-in) — exactly how the Stage 3 phone line will behave.
Tool calls (slot checks, bookings) happen live inside the stream. Ctrl+C hangs up
and auto-saves the transcript. Headphones matter in full-duplex mode: through
laptop speakers the mic hears the agent's own voice and it interrupts itself.

## Run the business portal (web)

```
python server.py        # opens http://127.0.0.1:8765 in your browser
```

This page is for the **business owner** (the clinic/salon/institute — our client):

- **Onboarding** — "＋ Add business" opens a form (services & prices, FAQs,
  policies, open days and hours). Submitting it writes `clients/<id>.yaml`:
  the multi-tenant principle as a web form. Appointment slots are generated
  from the chosen days/hours/gap.
- **Dashboard** — top-line stats (calls handled, minutes talked, bookings made,
  leads captured, call→booking conversion), a 7-day activity chart, full
  **call history** with chat-styled transcripts, the bookings table, and a
  **Leads** view: callers who showed interest but didn't book are saved by the
  agent (name, phone, what they wanted) for the owner to follow up. Every call
  from every channel — terminal, voice, live, web — is one JSON file in
  `calls/<client_id>/`.
- **📞 Test your agent** — a call widget (type or talk via the browser mic,
  spoken replies via edge-tts) so owners can try their receptionist before a
  real phone number exists (Stage 3). Test calls appear in the history like
  any other call.

The backend (`server.py`) is a thin FastAPI layer over the same
`ReceptionistAgent` — and the foundation Stage 3's telephony webhooks build on.

## The admin console (`/admin`)

The platform owner's view — same backend, separate page at
**http://127.0.0.1:8765/admin**, protected by `ADMIN_PASSWORD` from `.env`:
every business on the platform with per-client calls/minutes/bookings/leads,
platform totals, and the latest calls across all clients. The client portal is
what a business owner sees; the admin console is what YOU see.

Note on access today: the client portal has no per-client logins yet, so
locally it shows all businesses in its dropdown. Real client accounts (each
owner sees only their own business) arrive with public deployment.

## Architecture

```
 channels (thin wrappers)          core                 providers (one-file swaps)
 ┌─ main.py       terminal ─┐
 ├─ voice_main.py push-talk ─┼──►  agent.py  ──chat──►  llm.py   (Gemini: chat, STT, Live)
 ├─ live_main.py  live call ─┤     (the brain) ──speak─► tts.py  (edge-tts Indian voices)
 └─ server.py+web portal ────┘         │
                                   storage.py ──► Google Sheet / bookings.csv
                                   (all disk I/O)   leads.csv / calls/*.json
```

Rules that keep this clean: channels never contain business logic; the agent
never touches disk or provider SDKs directly; every conversation from every
channel lands in the same call log. `tests/` proves the seams work — the agent
runs against a scripted FakeLLM with no API key and no network:

```
python -m pytest tests -q     # 21 tests, ~2 seconds
```

## Project structure

```
vox agent/
├── run.bat                 # double-click launcher (sets up .venv on first run)
├── clients/
│   └── demo_clinic.yaml    # ALL business knowledge for one client (multi-tenant)
├── prompts/
│   └── receptionist.txt    # one prompt template with {slots} filled per client
├── llm.py                  # the ONLY file that talks to Gemini: chat + STT + Live
├── agent.py                # channel-independent agent core + 3 tools
├── storage.py              # ALL persistence: bookings, leads, call logs
├── tests/                  # pytest suite — runs with no API key (FakeLLM)
├── main.py                 # thin terminal wrapper (text mode)
├── voice_main.py           # Stage 2: push-to-talk voice wrapper around the SAME agent
├── live_main.py            # Stage 2.5: real-time interruptible call (Gemini Live API)
├── server.py               # business-portal backend: FastAPI over the SAME agent
├── web/
│   ├── index.html          # client portal — onboarding, dashboard, test-call widget
│   └── admin.html          # platform owner's console (/admin, password-protected)
├── calls/                  # one JSON per call: duration, turns, transcript (gitignored)
├── tts.py                  # the ONLY file that talks to edge-tts (swap voices here)
├── audio_io.py             # hardware layer: mic recording + speaker playback
├── transcripts/            # saved conversations (created on first /transcript)
├── bookings.csv            # local booking fallback (created on first booking)
├── SETUP.md                # Gemini key + Google Sheets setup, step by step
├── .env.example            # copy to .env, add real keys (never commit .env)
└── requirements.txt
```

## How the tool-use loop works (5 lines)

1. The customer's message is appended to history and sent to Gemini along with two tool schemas: `check_availability` and `book_appointment`.
2. Gemini replies either with plain text (done — show it to the customer) or with one or more **tool calls** (a name + arguments, e.g. `check_availability(date="2026-07-09")`).
3. Our Python code executes each requested tool — reading slots from the client YAML, or appending a booking row to the Sheet/CSV.
4. The tool results are appended to the conversation and sent **back** to Gemini, which now writes its reply using real data ("We have 10:00 or 16:00 free").
5. Steps 2–4 repeat until Gemini answers with plain text — so the model can chain calls, e.g. check a slot first, then book it, in a single customer turn.

## Stages

| Stage | What | Status |
|-------|------|--------|
| 1 | Text receptionist with auto-booking | ✅ done |
| 2 | Mic input (Gemini STT) + voice output (edge-tts) | ✅ done |
| 2.5 | Real-time interruptible voice call (Gemini Live API) | ✅ done |
| 2.75 | Business portal: onboarding, dashboard (calls/minutes/bookings), test-call widget | ✅ done |
| 3 | Real phone number (Vapi or Pipecat+Plivo), inbound + outbound | later |
| 4 | Multilingual voices (Telugu/Hindi via Sarvam), outbound campaigns | later |
| 5 | Dashboard: transcripts, extracted leads, bookings | later |
