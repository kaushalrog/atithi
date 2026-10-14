# Safe testing, and why live phone calls start switched off

VoxAgent can book real appointments, write to a business's Google Sheet, and
answer or place real phone calls that cost money and reach real people. This
page explains how to test everything **without** doing any of that, and what
has to be true before you switch real calls on.

## 1. Everything you can test for free, offline

No API key, no Twilio account, no network:

```
python -m pytest tests -q          # 100 tests, about 2 seconds
python docs/audit_repro.py         # security/correctness reproductions (expect NOT REPRODUCED
                                   # for everything except R3/R4, which are known follow-ups)
python bench.py                    # hot-path timings
```

How the tests stay safe:

| Risk | What stops it |
|---|---|
| Writing a business's real bookings, leads, call logs, client files or accounts | `tests/conftest.py` sets `VOXAGENT_ENV=test` before anything is imported and points every storage path at a temp folder. In test mode, `storage.py` **raises** on any write to the repo's real data files, and `auth.py` refuses to open the real `voxagent.db`, so a test that forgot to redirect fails loudly instead of touching real data. (This guard caught one such test during review.) |
| Copying test bookings into a business's Google Sheet | Test mode switches the Sheets copy off entirely, whatever `SHEET_ID` says. Mirror tests use a fake worksheet object, never a network connection. |
| Calling Gemini | Tests use `FakeLLM` / `SpyLive`. The one LLM test only checks how the client is constructed. |
| Calling Twilio | No test creates a Twilio client. Signatures are computed locally with Twilio's validator and a made-up token. Stream tests use a fake model session. |

`evals/run_evals.py` (the conversation-quality gate) **does** call Gemini,
which needs a key and uses quota. It also forces `VOXAGENT_ENV=test` and a
scratch folder, so evals can never write real bookings or touch a real Sheet.

## 2. The web portal, locally

```
python server.py        # http://127.0.0.1:8765
```

The test-call widget is a simulated conversation with your agent: no phone
line, no real customer. Calls made there are logged with channel `web-test`,
so they're never mistaken for real calls. Bookings made there **are** real
rows in `bookings.db`, so use a test business (see below), not a paying
client's.

Admin console: `ADMIN_PASSWORD` must be at least 12 characters and not the
`.env.example` sample. Otherwise `/admin` stays disabled and the server prints
why at startup.

## 3. Why live calls are disabled by default

A live phone line means:
- Every call opens a **paid** Gemini Live session.
- A tunnel (`go_live.py`) publishes the **whole** server to the internet: the
  portal, the admin console and the phone endpoints.
- The agent talks to real people on behalf of a real business.

So the code fails closed:

| Gate | Off/invalid → |
|---|---|
| `ENABLE_LIVE_CALLS=true` in `.env` | webhook 503, media stream refused, outbound calls refused, `go_live.py` exits |
| `TWILIO_AUTH_TOKEN` set and the webhook's `X-Twilio-Signature` valid | 503 / 403 (no more "local mode" that answered anyone) |
| Admin password passes the policy | `go_live.py` exits, `/admin` returns 503 |
| Handshake `x-twilio-signature` on the media stream | stream closed (1008) before anything is allocated |
| One-time ticket (signed, 2-minute expiry, bound to the call, single use) | stream closed (1008) |
| Business exists and its plan is active | caller hears an apology / stream closed |
| Fewer than `MAX_CONCURRENT_CALLS` (default 3) calls in progress | caller hears "lines are busy" / stream closed |

Only after every gate passes does VoxAgent build an agent and open a Gemini session.

**Run one server process.** The ticket key exists only in that process's
memory, so a restart invalidates tickets in flight (harmless: they expire in 2
minutes anyway), and two worker processes would reject each other's tickets.
If you ever scale out, switch the key to one derived from `TWILIO_AUTH_TOKEN`
(eng-review decision D3, option B).

## 4. Checklist before setting `ENABLE_LIVE_CALLS=true`

1. `python -m pytest tests -q` passes, and `python docs/audit_repro.py` shows
   NOT REPRODUCED for R1, R2, R5–R9.
2. `ADMIN_PASSWORD` is strong (12+ characters), and `ADMIN_EMAIL` is your real
   email, not `you@example.com`.
3. The business that answers has `twilio_number` set in its YAML and an
   active plan. Use a **test business** for the first calls, not a client.
4. Your Twilio account is a trial or has a spending limit, and the only
   numbers that can call are ones you've verified.
5. You've read the known gaps in §6.

## 5. The first real call is a verification step, not a launch

One security check could not be verified offline: **the media stream's
`x-twilio-signature`.** Twilio's documentation says to validate this header
on Media Streams websockets (and that the header name is lowercase there), but
it doesn't state which URL and parameters Twilio signs for the websocket
upgrade. VoxAgent checks it against the exact `wss://…/twilio/stream` URL from
its TwiML with no parameters, and **rejects the call if that doesn't match**
(fail closed, decision D4).

What this check is worth: for the media stream, Twilio's signature covers a
fixed URL, so it's the same value on every call for a given deployment, a
constant rather than a per-call proof. Anyone who sees one (e.g. in the ngrok
inspector) could reuse it. **The real lock is the one-time ticket** (signed with
a key that never leaves the server process, bound to one call, two-minute life,
single use). The signature is a second fence, not the boundary.

So on the first test call, from your own verified phone:
- **Agent answers:** the assumption holds. Note it in `docs/AUDIT.md`.
- **Call connects then drops immediately,** and the server prints
  `[phone] stream rejected: bad or missing x-twilio-signature`: Twilio signs
  something different. Don't disable the check. Capture the request details,
  fix `telephony.py`, and add a test with the real shape.

Other things only a real call can show: audio quality over the phone line,
latency the caller hears, and Twilio trial-account messages.

## 6. Checking the Google Sheets copy by hand

Tests never touch Google. To check the real connection once, with a **throwaway** Sheet:

1. Create a new blank Sheet, share it with the service account (SETUP.md Part 2), and put its ID in `.env` as `SHEET_ID` along with `GOOGLE_SHEETS_CREDENTIALS_PATH`.
2. Make sure `VOXAGENT_ENV` is **not** set to `test` (test mode switches the copy off).
   Then run `python storage.py import-sheet`: with `SHEET_ID` set, new bookings stay
   paused until the Sheet's existing rows have been imported once (a blank Sheet
   imports nothing). This also proves the credentials can *read* the Sheet.
3. `python main.py --client demo_clinic` and book a slot.
4. Expect `saved to: bookings.db + Google Sheet copy` in the terminal and the row in the Sheet.
5. Put the real `SHEET_ID` back. VoxAgent has no cancel flow yet, so the test booking stays in `bookings.db` and blocks that slot; do this with a test business, or remove the row yourself with the `sqlite3` tool.

## 7. Known gaps (tracked, not fixed yet)

From `docs/AUDIT.md` and `TODOS.md`. All matter before a paying client goes live:
- If the Gemini stream dies mid-call, the caller hears silence until they hang up (M7).
- A booking's Google Sheets copy runs inside the async call loop and can stall other live calls (M8).
- The media-stream race on the call-slot table is guarded by a lock; the test checks the lock is
  always held, because the race itself can't be reproduced reliably under CPython's GIL.
- Login, business-code and reset endpoints have no attempt limit (M9).
- Personal data (names, phone numbers, transcripts) has no retention or deletion policy (M11).
- Dashboard conversion counts failed booking attempts, and phone bookings aren't counted (M1/M2).
