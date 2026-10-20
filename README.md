<p align="center"><img src="web/logo.svg" width="380" alt="Atithi"></p>

# Atithi

*Every caller, welcomed.* Named after **Atithi Devo Bhava**, "the guest is God": how a good front desk treats every caller. (Formerly VoxAgent; the code, folder and settings still use the `voxagent` name.)

**An AI receptionist for any business that takes bookings**: clinics, salons, restaurants, gyms, coaching centres, repair shops and more, built for India. It talks to customers by text, voice or phone, checks real availability, books appointments into a database that refuses double-bookings, saves leads, and logs every conversation for the business owner.

**Proof, not promises.** Before a chat reply goes out, `proof.py` checks every "you're booked", "I've cancelled it" or "moved to 4 PM" against what the tools actually did. A claim with no booking behind it (or the wrong time) gets the model one chance to fix it; otherwise the customer hears an honest "let me take those details again". Every call record carries a proof report, and the dashboard shows "N of N promises backed by a real record". Phone calls are spoken as they are generated, so for them the report flags the call for the owner instead. The rules are English-only and deterministic: no second model, no extra cost on honest replies.

A second piece is now being built on top of it: **voxcheck**, a free offline checker that compares what the agent *said* ("you're booked for 4 PM") with what the system *actually did*. Every call already writes the evidence it needs (see [Call records and traces](#call-records-and-traces)). The checker itself is planned but not built yet. See [Roadmap](#roadmap).

---

## Contents

- [Status at a glance](#status-at-a-glance)
- [What it does](#what-it-does)
- [Quick start](#quick-start)
- [Configuration (`.env`)](#configuration-env)
- [Ways to talk to the agent](#ways-to-talk-to-the-agent)
- [The business portal and admin console](#the-business-portal-and-admin-console)
- [Real phone calls (Twilio)](#real-phone-calls-twilio)
- [Call records and traces](#call-records-and-traces)
- [How it works](#how-it-works)
- [Data, privacy and safety](#data-privacy-and-safety)
- [Testing, evals and benchmarks](#testing-evals-and-benchmarks)
- [Maintenance commands](#maintenance-commands)
- [Project structure](#project-structure)
- [Documentation map](#documentation-map)
- [Roadmap](#roadmap)
- [Known limitations](#known-limitations)
- [Working on the code](#working-on-the-code)

---

## Status at a glance

| Area | State |
|---|---|
| Text, push-to-talk voice, and live interruptible voice receptionist | ✅ Working |
| Business portal (onboarding, dashboard, call history, leads, test call) | ✅ Working |
| Admin console, per-business access codes, accounts and billing banner | ✅ Working |
| Real phone calls via Twilio (inbound and outbound) | ✅ Code-complete. **Off by default.** Needs Twilio keys and the [safe-testing checklist](docs/SAFE_TESTING.md) |
| Security and correctness hardening (Phase 0.5) | ✅ Done: [docs/AUDIT.md](docs/AUDIT.md) §0 |
| Structured per-call traces on every channel (Phase 3, Lane A) | ✅ Done and reviewed |
| voxcheck claim-vs-records checker (Phase 3, Lane B) | 📋 Planned and designed. Starts once builder outreach is sent ([docs/PRODUCT.md](docs/PRODUCT.md)) |
| Multilingual voices (Telugu/Hindi via Sarvam), outbound campaigns | Later |

**Test suite:** 177 tests pass on Python 3.11 and 3.13, with no API key and no network.

---

## What it does

- **Answers customers** in the voice and knowledge of one specific business: services, prices, timings, address, FAQ, policies. All of it comes from a per-business YAML file, never from code.
- **Books real appointments.** It checks live availability first, and the database allows only one confirmed booking per slot, so two simultaneous callers can never both get 10:30.
- **Captures leads** when a caller is interested but doesn't book: name, phone and what they wanted, for the owner to follow up.
- **Works on four channels** with the same brain: the terminal, push-to-talk voice, a real-time interruptible voice call (barge-in supported), and a browser test call in the portal. Real phone calls via Twilio are code-complete.
- **Speaks Indian languages.** It understands and answers Telugu, Hindi and Tamil with matching neural voices via edge-tts (free, no key).
- **Gives the owner a dashboard** with calls handled, minutes, bookings, leads, a 7-day chart, the full call history with transcripts, and bookings and leads tables.
- **Records every call twice.** A human-readable call record feeds the dashboard, and a machine-readable trace feeds the upcoming checker.

---

## Quick start

You need **Python 3.11+** and a **Gemini API key** (free at [aistudio.google.com](https://aistudio.google.com/apikey)). Step-by-step key setup is in [SETUP.md](SETUP.md).

### Windows (one click)

Double-click **`run.bat`**. On first run it creates `.venv` and installs everything. Then the portal opens in your browser, with the server minimized in the background (close its taskbar window to stop). Before that, create `.env` with your key:

```bat
copy .env.example .env
notepad .env
```

Other modes, from a terminal:

```bat
run.bat text      &rem chat in the terminal
run.bat voice     &rem push-to-talk voice
run.bat live      &rem real-time voice call (wear headphones)
run.bat live-hd   &rem real-time call without headphones (half duplex)
run.bat phone     &rem go live on the phone network (see "Real phone calls")
```

### macOS / Linux (manual)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # then put your GEMINI_API_KEY inside
python server.py              # portal at http://127.0.0.1:8765
```

On Windows the manual equivalent is `.venv\Scripts\activate` and `copy .env.example .env`.

The demo business is **`demo_clinic`** (a dental clinic). A second sample, `lakshmi_beauty_salon`, is in `clients/`.

---

## Configuration (`.env`)

Copy `.env.example` to `.env`. **Never commit `.env`**; it's gitignored. Only `GEMINI_API_KEY` is needed to start.

| Variable | Needed for | Notes |
|---|---|---|
| `GEMINI_API_KEY` | Everything | The free tier allows roughly 20 requests per day |
| `GEMINI_TIMEOUT_S` | Optional | Give up on one Gemini request after this many seconds (default 30) |
| `ADMIN_PASSWORD` | `/admin` console | At least 12 characters. The `.env.example` placeholder keeps the console **disabled** |
| `ADMIN_EMAIL` | Admin account | The platform owner's login |
| `GOOGLE_SHEETS_CREDENTIALS_PATH`, `SHEET_ID` | Optional Sheets copy | Each new booking is also copied to your Google Sheet. The database stays the source of truth |
| `ENABLE_LIVE_CALLS` | Phone calls | **Leave `false`** until the [safe-testing checklist](docs/SAFE_TESTING.md) passes |
| `MAX_CONCURRENT_CALLS` | Phone calls | Match your Gemini tier's concurrent Live sessions (free tier: about 3) |
| `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_NUMBER` | Phone calls | From your Twilio console ([SETUP.md](SETUP.md) Part 3) |
| `PUBLIC_BASE_URL` | Phone calls | Where Twilio can reach this server (a tunnel or your host) |
| `DEFAULT_CLIENT` | Phone calls | Business that answers numbers not mapped in any client YAML |
| `NGROK_AUTHTOKEN` | Optional | Only if your network blocks Cloudflare tunnels |
| `BILLING_PRICE_INR`, `BILLING_UPI` | Billing banner | Price shown to owners and the UPI id they pay to |

---

## Ways to talk to the agent

All four channels wrap the **same** `ReceptionistAgent`. Channels contain no business logic.

### 1. Terminal (text)

```bash
python main.py --client demo_clinic
```

You play the customer. Commands:
- `/reset` clears the conversation.
- `/transcript` saves it to `transcripts/`.
- `/quit` exits, and the transcript auto-saves.

### 2. Push-to-talk voice

```bash
python voice_main.py --client demo_clinic          # add --mute for text-only replies
```

Press **Enter** to start talking and **Enter** again to stop. Your speech is transcribed by Gemini, the same agent replies, and edge-tts speaks it. You can also type, and all `/` commands work.

### 3. Live call (real time, interruptible)

```bash
python live_main.py                 # wear headphones
python live_main.py --half-duplex   # no headphones: the mic mutes while the agent talks
```

This uses the Gemini Live API. Just talk: server-side voice detection decides when you start and stop, and you can interrupt the agent mid-sentence. Tool calls (slot checks, bookings) happen inside the stream. **Ctrl+C** hangs up, and the call is still saved. This is the same conversational architecture the phone line uses.

### 4. Browser test call

Open the portal (`python server.py`) and use **📞 Test your agent**. You can type or talk through the browser mic, and replies are spoken. Test calls appear in the call history like real ones.

---

## The business portal and admin console

```bash
python server.py                      # http://127.0.0.1:8765, opens your browser
python server.py --no-browser         # same, without opening a browser
python server.py --host 0.0.0.0       # listen on all interfaces (only behind proper hosting)
```

**The portal** (`/`) is for the **business owner**:
- **Onboarding.** "＋ Add business" opens a form for services and prices, FAQs, policies, open days, hours and slot gap. Submitting writes `clients/<id>.yaml`.
- **Dashboard.** Calls, minutes, bookings, leads, call→booking conversion, a 7-day chart, the call history with chat-style transcripts, and bookings and leads tables. It's one request with an ETag, so idle refreshes cost nothing.
- **Test call.** See channel 4 above.

**The admin console** (`/admin`) is for **you**, the platform owner. It's protected by `ADMIN_PASSWORD` and shows:
- every business, with per-business numbers and platform totals
- the latest calls across all clients
- system status checks: Gemini, Twilio, the live-calls switch, Sheets, bookings
- the list of business access codes

**Who sees what:**
- Every business has a **business code** (`access_key:` in its YAML, e.g. `VX-84KQ2N`). An owner enters it on the portal and sees **only** their own business. Requests for another business's data are rejected server-side.
- `ADMIN_PASSWORD` opens everything.

---

## Real phone calls (Twilio)

`telephony.py` holds **all** Twilio code:
- the inbound webhook, which returns TwiML `<Connect><Stream>`
- a websocket audio bridge converting 8 kHz μ-law and 16/24 kHz PCM
- outbound calls started from `/admin`
- per-business number mapping via `twilio_number:` in each client YAML

**Phone calls are OFF by default.** Before setting `ENABLE_LIVE_CALLS=true`:
1. Add the Twilio keys and `PUBLIC_BASE_URL` to `.env` ([SETUP.md](SETUP.md) Part 3).
2. Work through [docs/SAFE_TESTING.md](docs/SAFE_TESTING.md).
3. Then run `run.bat phone` (or `python go_live.py`), which opens a tunnel, points your Twilio number's webhook at it, and starts the server.

**Built-in protections** (from the Phase 0.5 hardening):
- Every request is checked against Twilio's signature.
- Each media stream needs a one-time signed ticket bound to that exact call.
- The business's plan must be active.
- There's a concurrent-call limit, and an outbound call holds its slot while it rings.

**Not yet verified against real Twilio traffic:** no real account was used in development. The first real call is the verification step ([SAFE_TESTING.md](docs/SAFE_TESTING.md) §5).

---

## Call records and traces

Every conversation, on every channel, writes two files (both gitignored):

| File | For | Contents |
|---|---|---|
| `calls/<client>/<call_id>.json` | The dashboard | Channel, start/end, duration, customer turn count, the caller's number (phone), and a readable transcript including tool calls |
| `calls/<client>/traces/<call_id>.json` | The voxcheck checker | `trace_version: 1`: timezone-aware turns, typed actions, and a snapshot of the relevant booking rows at call end |

**Trace actions:**
- Each action records its type (`availability`, `book`, `lead` or `other`), a normalised `ok` flag, its arguments and its result.
- Each action is tied to the agent turn it belongs to.

**What makes traces trustworthy evidence:**
- **True order on streaming calls.** Phone and live calls record the caller's words, then anything the agent said *before* a tool, then the tool, then what it said after. A "you're booked!" spoken before the booking actually ran stays visible. Barge-in ends a turn, so exchanges never merge.
- **Only what the customer heard.** Text the model sends alongside a tool call is never shown to the customer, so it isn't recorded as speech.
- **No silent gaps.**
  - A phone call that booked something but produced no speech transcript is still recorded.
  - Phone call ids include the Twilio call SID, so two calls starting in the same second never overwrite each other.
- **Crash-safe.** Records are written to a temp file and renamed into place, so a crash never leaves half a file.
- **Never at the call's expense.** If building a trace fails, the call record is still saved and the error is logged.
- **Minimal personal data.** The snapshot holds full rows only for this caller's own bookings and leads. Other customers' same-day bookings appear only as taken slots (date, time, status), never with a name or number.

The format is specified in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) §3.

---

## How it works

```
 channels (thin wrappers)            core                       providers (one-file swaps)
 ┌─ main.py        terminal ──┐
 ├─ voice_main.py  push-talk ─┼──►  agent.py  ──chat──────►  llm.py   (Gemini: chat, STT, Live)
 ├─ live_main.py   live call ─┤     ReceptionistAgent ─speak─► tts.py  (edge-tts Indian voices)
 ├─ telephony.py   phone ─────┤     run_tool · TurnRecorder
 └─ server.py + web/  portal ─┘          │
                                    storage.py  ──►  bookings.db (SQLite) ──copy──► Google Sheet
                                    (ALL disk I/O)   leads.csv · calls/<client>/*.json · traces/
                                    scheduling.py    opening-hours rule → bookable slots
```

**The tool-use loop**, one customer turn:
1. The customer's message goes to Gemini with three tools: `check_availability`, `book_appointment` and `save_lead`.
2. Gemini answers with text (done) or with tool calls.
3. `agent.run_tool` runs each call. Every channel goes through this one method, so error handling and timestamps are identical everywhere. Tools validate their inputs and return errors the model can act on, for example "that slot isn't free, offer these instead" or "the phone number looks incomplete".
4. The results go back to Gemini, which replies using real data. Steps 2–4 repeat, up to 5 rounds, so the agent can check a slot and then book it in one turn.

**Design rules the code follows** ([CLAUDE.md](CLAUDE.md)):
- **Multi-tenant from day one.** All business knowledge lives in `clients/<id>.yaml`, filled into one prompt template (`prompts/receptionist.txt`).
- **Real-time facts are tool calls.** Availability is never pasted into the prompt.
- **Provider code stays in one file each.** All Gemini code is in `llm.py`, all edge-tts code in `tts.py`, all Twilio code in `telephony.py`, and all disk I/O in `storage.py`. Swapping a provider means rewriting one file.
- **Slots are a rule, not a list of dates.** Each business stores `schedule:` (open days, hour ranges, slot gap, booking horizon), and slots are generated on demand. An early version stored literal dates; two months later they had all passed and the agent silently couldn't book anything. A rule can't expire.
- **Nothing slow sits on the reply path.** One shared Gemini client is built at startup (it costs about 780 ms), and files are parsed once and cached.

---

## Data, privacy and safety

| Data | Where | In git? |
|---|---|---|
| Bookings (customer names, phones) | `bookings.db` (SQLite; the only source of truth) | No (gitignored) |
| Leads | `leads.csv` | No |
| Call records and traces | `calls/` | No |
| Saved transcripts | `transcripts/` | No |
| Accounts (emails, password hashes, sessions) | `voxagent.db` | No |
| Secrets | `.env`, `credentials.json` | No |
| Business knowledge and access codes | `clients/*.yaml` | **Yes.** The two sample businesses' codes are committed; treat them as demo-only and rotate before exposing a server |

**Safety switches:**
- **`VOXAGENT_ENV=test`** (set automatically by the test suite and evals) turns off the Google Sheets copy. Any write to the real data files raises an error, so tests can't touch real customer data.
- **`ENABLE_LIVE_CALLS`** stays `false` until you deliberately turn phone calls on.
- **Request size limits** cap chat messages at 2,000 characters, TTS at 1,000 characters and voice uploads at 5 MB.
- **The admin console stays disabled** while `ADMIN_PASSWORD` is the placeholder or under 12 characters.

**Still open** (tracked in [TODOS.md](TODOS.md)):
- a data-retention and delete policy (it must also cover traces)
- rate limits on login and code endpoints

---

## Testing, evals and benchmarks

```bash
python -m pytest tests -q     # 177 tests, ~2–4 s, no API key or network (FakeLLM)
python evals/run_evals.py     # 10 scripted conversations against the REAL model (uses quota)
python bench.py               # hot-path timings, offline
python docs/audit_repro.py    # re-runs the Phase 0 audit's reproductions in a temp dir
```

- **The tests** use a scripted `FakeLLM` and `FakeLive` in place of Gemini, with all storage redirected to a temp folder. They prove the provider seam: the agent only knows a neutral message format.
- **The evals** are the quality gate before demos. Run them after any prompt change.
- **The bench** measures what sits between a caller speaking and the agent answering. ⚠️ It reads your real data files, and on a machine with no `bookings.db` it creates an empty one. Run it in a throwaway copy if that matters (tracked in TODOS).

---

## Maintenance commands

```bash
python storage.py export-csv backup.csv     # dump all bookings to CSV (rollback path)
python storage.py import-sheet              # one-time import of bookings from your Google Sheet
python storage.py import-sheet --skip       # ...or explicitly skip it
```

If `SHEET_ID` is set, new bookings stay **paused** until you run `import-sheet` once. This guarantees bookings already in the Sheet are known before anyone can double-book them. `/admin` shows when this is pending.

---

## Project structure

```
voxagent/
├── run.bat                  # Windows launcher: web | phone | text | voice | live | live-hd
├── go_live.py               # phone go-live: tunnel + Twilio webhook + server (run.bat phone)
├── agent.py                 # ReceptionistAgent: tool loop, 3 tools, run_tool, TurnRecorder
├── llm.py                   # the ONLY Gemini code: chat, speech-to-text, Live API
├── tts.py                   # the ONLY edge-tts code (Indian neural voices)
├── audio_io.py              # mic recording + speaker playback
├── scheduling.py            # opening-hours rule → bookable slots (never expires)
├── storage.py               # ALL disk I/O: bookings.db, leads, call records, traces
├── server.py                # FastAPI portal + API (port 8765)
├── telephony.py             # ALL Twilio code: webhook, media-stream bridge, outbound
├── auth.py / billing.py     # owner accounts, sessions, plans and the billing banner
├── main.py / voice_main.py / live_main.py   # terminal, push-to-talk, live-call channels
├── clients/                 # one YAML per business (all business knowledge)
├── prompts/receptionist.txt # the one prompt template, filled per business
├── web/                     # index.html (portal), admin.html (console), logo.svg
├── evals/                   # scripted real-model conversations + runner
├── tests/                   # pytest suite (no key, no network)
├── bench.py                 # hot-path benchmark
├── docs/                    # audit, plans, architecture, product, metrics, safe testing
├── SETUP.md                 # Gemini key, Google Sheets and Twilio setup, step by step
├── TODOS.md                 # deferred work with context
├── CLAUDE.md                # project rules and architecture map (also read by AI tools)
├── .env.example             # copy to .env
└── requirements.txt
```

Created at runtime and gitignored: `.venv/`, `.env`, `bookings.db`, `leads.csv`, `calls/`, `transcripts/` and `voxagent.db`.

---

## Documentation map

| Doc | What's in it |
|---|---|
| [SETUP.md](SETUP.md) | Getting keys: Gemini, Google Sheets service account, Twilio |
| [docs/SAFE_TESTING.md](docs/SAFE_TESTING.md) | How to test safely and the checklist before enabling live calls |
| [docs/AUDIT.md](docs/AUDIT.md) | The Phase 0 audit (findings, reproductions) and what the hardening fixed |
| [docs/HARDENING_PLAN.md](docs/HARDENING_PLAN.md) | Phase 0.5 security/correctness plan and its decisions |
| [docs/PRODUCT.md](docs/PRODUCT.md) | Product direction: the claim-vs-records bet, facts vs hypotheses, the demand test and kill rule |
| [docs/COMPETITIVE_ANALYSIS.md](docs/COMPETITIVE_ANALYSIS.md) | Voice-agent testing tools, with sources and evidence labels |
| [docs/METRICS.md](docs/METRICS.md) | What gets measured and the targets |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Receptionist plus checker architecture and the trace format |
| [docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md) | Engineering plan, decisions and task list (E1–E9) |
| [docs/designs/](docs/designs/) | The approved design doc and CEO reviews |

---

## Roadmap

1. **Done:** receptionist on all channels, portal and admin, Twilio code, hardening, and per-call traces (Lane A).
2. **Next, once builder outreach is sent: voxcheck (Lane B).** `python -m voxcheck check <traces> --records <file>` checks each call for:
   - a record that's missing or doesn't match a successful action
   - a booking on a slot that wasn't free
   - double bookings
   - "you're booked" with no booking behind it
   - incomplete calls

   Output goes to a text summary, JSON run files with `compare`, and an escaped HTML report. Everything is offline and free. The design is in [docs/designs/claim-vs-records-checker.md](docs/designs/claim-vs-records-checker.md).
3. **After the demand checkpoint:** the remaining heuristic checks, adapters for other voice platforms, and the conversion-metric fix on the dashboard.
4. **Later:** Telugu/Hindi voices via Sarvam, and parallel outbound campaigns.

---

## Known limitations

- **The conversion rate counts failed booking attempts.** The portal number is a transcript search, not real outcomes (audit M1). Traces now carry the real outcomes, but the dashboard fix is still pending.
- **Phone tools run on the event loop.** A slow database or Sheets write briefly stalls other live calls, and a crashed model stream can leave a caller on a silent line (TODOS).
- **No real Twilio, Gemini Live or Google Sheets traffic** has been exercised in development; everything was tested with fakes.
- **Single server process only.** Phone stream tickets use a per-process key.
- **Scheduling uses the server's local clock**, while traces use the business timezone. Run the server in IST, or expect "today" to differ between 00:00 and 05:30.

---

## Working on the code

- **Run the tests after every change:** `python -m pytest tests -q`. Run `python bench.py` after touching `agent.py`, `storage.py`, `auth.py`, `llm.py` or `scheduling.py`.
- **Run the evals before demos** (they use real model quota).
- Read [CLAUDE.md](CLAUDE.md) first: it lists the architecture rules (multi-tenant YAML, one-file providers, tools for real-time facts) and the performance rules.
- **Never commit** `.env`, credentials, or anything from `bookings.db`, `leads.csv`, `calls/` or `transcripts/`. They hold customer data.
