# Product truth: what the marketing site may claim

Audited 2026-10-21 against branch `main` at `1fc0042`, plus this session's records.

Evidence comes from three places:
- the code;
- the unit tests (`tests/`, 336 passing, no network);
- the live-model checks run on 2026-10-20: the conversation evals in `evals/`, 11 of 11 passing on `gemini-3.5-flash-lite`, and the recorded walkthrough `demo/atithi-demo.mp4`, made on throwaway data.

**Rule for the site:** only list 1 may be stated as working. List 2 must be labelled (for example "being tested" or "switched off until verified"). List 3 is either labelled "planned" or left out.

## 1. Verified and usable

| Capability | Evidence |
|---|---|
| A text conversation with the receptionist in the owner portal's "Test your agent" chat | `web/index.html` (`openTest`), `server.py` `/api/session` + `/api/chat`; walkthrough 0:37–1:38 |
| Answers prices, timings and policies **only** from the business's own settings; unknown questions get "the front desk will call you back" instead of a guess | `prompts/receptionist.txt` rule 2; evals `price_from_config`, `unknown_question_no_invention`, `common_fact_not_in_info`, `discount_trap`, `service_we_dont_offer` |
| Checks live availability through a tool before offering times; past times and closed dates are never offered | `agent.py` `check_availability`; `scheduling.py` `available_slots`, `_apply_closures`; eval `unavailable_slot_uses_tool`; `tests/test_scheduling.py`, `tests/test_closed_dates.py` |
| Books only after the customer confirms, saves to the database **before** confirming, and can never double-book a slot | `agent.py` `_book_appointment`; `storage.py` partial UNIQUE index `one_confirmed_booking_per_slot`; evals `booking_happy_path`, `no_booking_without_confirmation`; `tests/test_storage.py` |
| Promise check: a reply saying "you're booked / cancelled / moved" is checked against what the tools actually did; an unbacked claim gets one correction, then an honest fallback; each conversation is marked "verified" or "check this call" | `proof.py`; `agent.py` `chat`; `tests/test_proof.py`; walkthrough 1:38–2:05 ("2 of 2 promises backed") |
| Cancel and reschedule, by the customer in conversation or by the owner with one click; the slot frees up | `agent.py` `_cancel_booking`, `_reschedule_booking`; `/api/bookings/cancel`; `tests/test_booking_changes.py`; walkthrough 2:50 |
| Saves leads when a customer is interested but doesn't book; owner follow-up status, notes, callback date; CSV export | `agent.py` `save_lead`; `/api/leads/update`, `/api/export/{kind}.csv`; eval `lead_capture_on_hesitation`; `tests/test_leads_tracker.py` |
| Unanswered-questions inbox: the owner answers once and it becomes an FAQ | `note_unanswered_question` tool; `/api/questions*`; `tests/test_questions.py`; walkthrough 2:13–2:26 |
| Owner dashboard: calls, minutes, bookings, leads, conversion; call history with full transcripts and plain-word action chips | `/api/dashboard`; `web/index.html`; walkthrough 0:29, 1:38 |
| Owner settings: business type, services, prices, hours, holidays and closed dates, languages | `/api/business/{id}/settings`; `tests/test_settings.py`, `tests/test_any_business.py`; walkthrough 2:26 |
| Replies in **Telugu** when the customer writes in Telugu | eval `telugu_customer`; walkthrough 2:40 |
| Multi-business: each owner signs in and sees only their own business | `auth.py`, `authorize_client` in `server.py`; `tests/test_access.py` |

## 2. Implemented but not verified end to end

| Capability | Status | Evidence |
|---|---|---|
| **Real phone calls** (Twilio Media Streams + Gemini Live voice) | Code-complete, **never run on a real phone line**. Off unless `ENABLE_LIVE_CALLS=true` | `telephony.py`; `tests/test_telephony.py` (fakes only); `docs/SAFE_TESTING.md` §5 |
| **WhatsApp replies** | Exercised once through the real webhook code with a locally signed request (walkthrough 3:02), **never through Twilio or WhatsApp itself**. Off unless `ENABLE_WHATSAPP=true` | `telephony.py` `/twilio/whatsapp`; `tests/test_whatsapp.py` |
| SMS booking confirmations and reminders | Dry-run only: messages are written to a log, not sent. Off unless `ENABLE_SMS=true`; Indian delivery needs DLT registration | `notify.py`; `tests/test_notify.py` |
| Talk to a person (live transfer to the owner's phone) | Off; fakes only | `transfer_to_owner` in `agent.py`; `telephony.transfer_call`; `tests/test_handoff_callbacks.py` |
| Missed-call callbacks (decline with a busy tone, ring back during opening hours) | Off; fakes only | `callbacks.py`; `tests/test_handoff_callbacks.py` |
| Replies in Hindi and Tamil | Allowed by the settings (`agent.LANGUAGES`); **no eval covers them** | `agent.py` `LANGUAGES`, `language_instruction` |
| Website chat widget a business can paste on its own site | Built, off by default, checked in a browser on throwaway data (2026-10-19). Never used by a real business. Its public-channel protections (no booking look-ups, change requests, 2-booking caps) are on branch `fix/public-channel-safety`, not yet merged | `web/widget.js`, `/api/public/*`; `tests/test_website_chat.py`, `tests/test_channel_trust.py` |
| Browser voice test (speak into the mic, hear an edge-tts voice) | Implemented; not exercised in this audit | `/api/voice`, `/api/tts`, `tts.py` |
| Copy of each booking to Google Sheets | Implemented; not exercised in this audit | `storage.py` Sheets queue, `import-sheet` |

## 3. Planned or not implemented

| Item | Source |
|---|---|
| `voxcheck`, the offline claim-vs-records checker for other builders | README "Roadmap"; `TODOS.md` (gated on outreach). **Not promoted on the site.** |
| Natural Telugu and Hindi *voices* on calls (Sarvam) | `CLAUDE.md` Stage 4 |
| Parallel outbound calling campaigns | `CLAUDE.md` Stage 4 |
| Pricing, customers, testimonials, uptime, compliance certifications | None exist. **The site claims none.** |
| A contact, waitlist or demo-request destination | None configured. The site's calls to action point to the in-page sample and the walkthrough video. |

## Wording the site uses because of this audit

Revised 2026-10-21 after the four-agent audit (red team RT-1–RT-4, demand strategist).

- Available today: the **test chat in the owner portal**, on sample data. Website chat, phone calls and WhatsApp are "**Not live yet**".
- Languages: "Passes our scripted checks (11 conversations, one in Telugu). Hindi and Tamil can be switched on but aren't checked yet."
- Promise check: "**In English text chats**… It catches common wordings, not every one." It is never presented as a guarantee: `proof.py` misses some phrasings (red team probe).
- Calendar: "your live booking calendar", meaning the bookings Atithi holds, which reach the owner through the dashboard and CSV. It is not the owner's own diary.
- Double booking: "The database refuses a second booking for the same time."
- "What it's built not to do" lists rules it's tested against, explicitly "not guarantees".
- Use cases are labelled "Illustrative situations built on our sample clinic and salon, not customer stories".
- Sample dates are relative ("tomorrow", "Saturday"), so they never go stale.

## The pilot call to action and privacy notice (2026-10-21)

- **The main CTA** is a `mailto:` link to **atithi.support@gmail.com**, the address the owner supplied. It has a prefilled subject and a short template. The site has no form and no server.
- **What happens next** (the pilot section) restates the owner's agreed process:
  1. email;
  2. a reply to arrange a short call that asks for a real missed-call example;
  3. a free two-week pilot, using the test chat (and website chat if wanted), with no phone calls;
  4. no payment, and deletion on request.
- **The privacy notice** retention periods must match `docs/DATA_HANDLING.md` in the main repo, which the server enforces.
- **Depends on the backend branch:** the notice says Atithi tells customers, at the start of every conversation, that it is an AI and that the conversation is saved as text, and that data past retention is deleted automatically. Both are built and tested on `feat/pilot-readiness` (commit `fc26803`):
  - unit tests cover each channel's disclosure;
  - eval `honest_about_being_ai` passes, and the full eval gate was 11/11 on 2026-10-30;
  - retention and deletion are in `docs/DATA_HANDLING.md`.

  **Merge `feat/pilot-readiness` before publishing the site.** The phone disclosure has still never played on a real call, but phone calls aren't offered in the pilot.
- The retention table must match `storage.RETENTION_DAYS`: 90 / 180 / 1 year after the appointment / 180 / 30 / 30 days.
- The interactive sample on the page is labelled "**Sample conversation. Scripted, no AI is running.**"
- No numbers about outcomes. The only numbers on the page are times and prices inside sample conversations, taken from the repo's demo clinic (`clients/demo_clinic.yaml`).
