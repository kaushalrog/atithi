# Data handling

What Atithi stores about customers, for how long, who processes it, and how to delete it.

**Status:** owner decision of 2026-10-21. The policy and its enforcement are implemented and unit-tested. **None of it has run in a real pilot yet.** Read this before any real customer talks to Atithi.

## What customers are told

Every conversation starts with a disclosure (`agent.disclosure`), on every channel:

| Channel | How | Exact words |
|---|---|---|
| Phone call (inbound, outbound, callback) | Twilio speaks it **before** the AI joins (`<Say>` in the TwiML), so it plays whatever the model does | "Hello, you've reached {business}. You're speaking with an AI receptionist. This call is transcribed and saved as text so the team can follow up." |
| Website chat | The first message, from the server | "Hello! I'm the AI receptionist for {business}. This chat is saved so the team can follow up. How can I help you today?" |
| WhatsApp | Put before the first reply of each conversation | "(You're chatting with {business}'s AI receptionist. This chat is saved so the team can follow up.)" |

**If asked:** prompt rule 12 tells the receptionist to say honestly that it is an AI receptionist, and to offer a person (`transfer_to_owner`). The eval `honest_about_being_ai` checks this. An older eval used to require the opposite.

**Not yet verified:**
- The phone disclosure has never played on a real call; phone calls are off.
- The English `<Say>` voice (`en-IN`) is Twilio's. A Telugu or Hindi disclosure isn't built yet.

## What is stored

Everything lives on the server that runs Atithi, except where noted.

| Data | Where | Personal data | Kept for | Then |
|---|---|---|---|---|
| Conversation record: transcript, outcome, promise-check report | `calls/<business>/<id>.json` | What the customer said, their number if given | **90 days** | Deleted |
| Trace of the same conversation (turns + actions) | `calls/<business>/traces/<id>.json` | Same | **90 days** (with its record) | Deleted |
| Leads | `leads.csv` | Name, number, interest, note | **180 days** | Deleted |
| The owner's follow-up on a lead | `bookings.db` `lead_followups` | Number, owner's note | **180 days** (with the lead) | Deleted |
| Bookings | `bookings.db` `bookings` | Name, number | **1 year after the appointment date** | Name and number removed; date, time and service kept for the business's records |
| Unanswered questions | `bookings.db` `questions` | Only what the customer typed | **180 days** after last asked | Deleted |
| Missed-call callback queue | `bookings.db` `callbacks` | Number | **30 days** | Deleted |
| SMS log (sent or dry-run) | `notifications.jsonl` | Number, message text | **30 days** | Deleted |
| Performance log (optional) | `VOXAGENT_PERF_LOG` | **None**: allowlisted labels and a random id only | n/a | n/a |
| **Call audio** | **Not stored by Atithi.** Calls are transcribed; Twilio call recording is not switched on. | n/a | n/a | n/a |
| Copy of each booking in Google Sheets (optional) | The business's own Sheet | Name, number | Not managed by Atithi | Delete by hand in the Sheet |

**Changing a period:** each one can be set with an environment variable, e.g. `VOXAGENT_RETAIN_CALLS_DAYS=60`. The keys are `CALLS`, `LEADS`, `BOOKING_CONTACT`, `QUESTIONS`, `CALLBACKS` and `NOTIFICATIONS`.

**Enforcement:** the server applies the periods **once a day** in the background (`storage.start_retention_worker`). `VOXAGENT_RETENTION=off` disables it.

## Deleting a person's data

When a customer (or the business, on their behalf) asks to be deleted:

```bash
python storage.py delete-customer "+91 98765 43210"             # shows what would be deleted
python storage.py delete-customer "+91 98765 43210" --apply     # does it
python storage.py delete-customer "98765 43210" --client demo_clinic --apply   # one business only
```

The number is matched on its last 10 digits, so `+91 98…`, `098…` and `98…` are the same person. The command does the following:
- **Bookings:** anonymised (name and number removed). A **future** confirmed booking is also **cancelled**, since nobody could be told about it any more. The command reports how many.
- **Leads, follow-ups, callback rows and SMS log lines:** deleted.
- **Conversations:** every record and trace where they are the caller **or their number appears in the transcript** is deleted.
- **Google Sheets:** if a Sheet is configured, it reminds you to delete their rows there by hand.

**Purge on demand:** to apply the periods now, run `python storage.py purge` (dry run), then `python storage.py purge --apply`.

## Who else processes the data

| Provider | What it receives | Why |
|---|---|---|
| Google (Gemini API) | Conversation text; call audio on phone calls | To understand the customer and write the reply |
| Twilio | The call audio stream and phone numbers; WhatsApp and SMS messages | To carry calls and messages (when switched on) |
| Microsoft (edge-tts) | Reply text, **only** for the optional spoken replies in the owner's test chat | Text-to-speech |
| Google (Sheets) | Booking rows, if the business turns the copy on | The business's own spreadsheet |

**Before a real pilot, check the Gemini terms for the tier you use.** Google's terms for unpaid Gemini API use have allowed content to be used to improve Google's products. Real customer conversations should go through a paid tier, or terms that exclude this. **This has not been checked against the current terms yet.**

## Never in development or tests

- **Tests:** `VOXAGENT_ENV=test` (set by `tests/conftest.py` and `evals/`) makes any write to the real data files raise. Tests use temp folders and synthetic names and numbers only.
- **Demos and screenshots:** the walkthrough video and the website screenshots were recorded on throwaway copies of the sample businesses.
- **Logs:** the console log shows a customer only as an initial and the last 4 digits (`P. …3210`).
- **Real customer data** must never be copied into the repo, test fixtures, issues or screenshots.

## Open before the pilot

1. Check the Gemini terms and choose the tier (above).
2. Decide who at the business may ask for deletions, and how requests reach you (the pilot email: atithi.support@gmail.com).
3. Play the phone disclosure on the first controlled real call (`docs/SAFE_TESTING.md` §5).
4. Telugu and Hindi wording of the disclosure, if those businesses greet in those languages.
