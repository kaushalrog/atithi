# VoxAgent

An AI receptionist for Indian small service businesses — clinics, salons,
coaching institutes. The long-term goal is a voice agent that answers and makes
phone calls in English, Telugu, and Hindi, books appointments automatically, and
logs every conversation. It's being built in stages; **this is Stage 1**: a
text-based receptionist you chat with in the terminal, with real auto-booking
into Google Sheets (or a local CSV fallback).

## Run Stage 1

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

## Project structure

```
vox agent/
├── clients/
│   └── demo_clinic.yaml    # ALL business knowledge for one client (multi-tenant)
├── prompts/
│   └── receptionist.txt    # one prompt template with {slots} filled per client
├── llm.py                  # the ONLY file that talks to Gemini: chat + STT (swap providers here)
├── agent.py                # channel-independent agent core + tools
├── main.py                 # thin terminal wrapper (text mode)
├── voice_main.py           # Stage 2: voice wrapper around the SAME agent
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
| 3 | Real phone number (Vapi or Pipecat+Plivo), inbound + outbound | later |
| 4 | Multilingual voices (Telugu/Hindi via Sarvam), outbound campaigns | later |
| 5 | Dashboard: transcripts, extracted leads, bookings | later |
