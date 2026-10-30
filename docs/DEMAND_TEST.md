# Demand test: do missed calls cost clinics real appointments?

**Owner decision (2026-10-21):** no new features until this test reports.
**Who runs it:** Sai and the team, in person or by phone. Claude prepared this kit but contacts nobody.

## The question

> When a clinic misses a call, does it lose an appointment it would otherwise have had, often enough that the owner will try, and keep using, something that answers for them?

Each of these alone is **not** evidence:
- compliments ("nice idea");
- website visits;
- "I'd use that";
- a "yes" to a pilot that is never used.

What counts is the **evidence ladder** below.

## Who to ask: 15 clinics

- Owner-run dental, skin or general clinics with **1–3 doctors**, where the owner or one receptionist answers the phone.
- Start in one city you can visit (Coimbatore or Hyderabad). Telugu-speaking clinics are a plus: the Telugu text checks pass, and that's a possible wedge.
- **Not** hospital chains, clinics with a call centre, or friends and family. Friends say yes to be kind.

## The conversation (about 15 minutes)

**Ask for a real example before you describe Atithi at all.** If you pitch first, people answer about the pitch, not their week.

1. "Who answers the phone here, and what happens when they can't?"
2. "Think of the last time you know a call was missed. What happened? Did they call back? Did they book somewhere else?" **Write down the actual story.** No story means no evidence for this clinic.
3. "Roughly how many calls a day? How many go unanswered: before opening, at lunch, after hours, when the receptionist is busy?" (Their estimate. If they can, look at the phone's missed-call list together.)
4. "What's one appointment worth to you?" (An average bill, not a guess about lifetime value.)
5. "What have you tried? A second phone, WhatsApp Business, a booking app, nothing?" Then: "Why did you stop?"
6. **Only now** describe Atithi in one sentence:
   > "An AI receptionist that answers your chat, checks your free slots, books the patient, and shows you every conversation. It tells patients it's an AI."

   Show the sample booking on the website, `#sample` (scripted; say so).
7. The offer:
   > "We're running free two-week pilots. You'd use it through the test chat with your real services, prices and hours. Phone calls aren't part of it yet. Would you try it?"

   If yes, book the set-up now. If no: "What would have to be true for you to try it?"

**Don't promise:**
- phone answering (not live);
- a launch date;
- prices;
- anything the status table on the site doesn't say.

## Evidence ladder: record the highest step each clinic reaches

| Step | What happened | Counts as |
|---|---|---|
| 0 | Talked, no concrete missed-call story | Nothing |
| 1 | Told a **real, specific** missed call that cost an appointment | Pain exists |
| 2 | Agreed to a pilot **and** gave services, prices and hours | Willing to try |
| 3 | Used it in week 1: at least 5 real or staff-test conversations | Actually tried |
| 4 | **Still using it on day 14** without being chased | Continued use |
| 5 | Asked what it would cost, or said they'd pay | Willing to pay (bonus, not required) |

## Pass and fail (decided now, before the results)

Out of 15 clinics:

| | Steps reached | Decision |
|---|---|---|
| **PASS** | **at least 10** reach step 1, **at least 4** reach step 2, **at least 2** reach step 4 | Continue: proceed to the first real phone line (with the Twilio Auth Token) for the pilot clinics |
| **NARROW** | at least 8 reach step 1, but fewer than 4 reach step 2 | The pain is real but the offer isn't. Change who or what (another segment, WhatsApp first, after-hours only), then test again |
| **STOP or RETHINK** | fewer than 8 reach step 1 | Missed calls aren't costing these clinics enough. Revisit the problem before writing more code |

**Time box:** 3 weeks for the 15 conversations, plus 2 weeks of pilots. Report on the date the last pilot ends.

## Tracking sheet

Keep this offline (not in the repo, since it holds real names and numbers). One row per clinic:

| # | Clinic (initials) | Type | City | Who answers | Calls/day (their estimate) | Missed/day | Real missed-call story? (paste it) | Value of 1 appointment | Tried before | Highest step (0–5) | Pilot start | Day-14 use? | Notes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|

## Privacy for the test itself

- Don't record the conversations unless the person agrees first.
- Pilot clinics' data follows `docs/DATA_HANDLING.md`. Tell each clinic, in writing:
  - what's kept, and for how long;
  - that patients are told it's an AI;
  - that they can ask for deletion at **atithi.support@gmail.com**.
- **Before any pilot uses real patient conversations, settle the open items in `docs/DATA_HANDLING.md`**, especially the Gemini terms for the tier you use.

## Outreach messages (edit freely)

**WhatsApp or SMS to a clinic you'll visit:**

> Hello Dr. ___, I'm Sai, building a small tool for clinics in ___. Could I take 15 minutes of your time this week to ask how your clinic handles phone calls? I'm not selling anything in this visit. I'd like to hear what actually happens when calls are missed.

**Email:**

> Subject: 15 minutes on how your clinic handles missed calls?
>
> Hello Dr. ___,
>
> I'm building Atithi, an AI receptionist for small clinics. Before building more, I'm talking to 15 clinic owners about what really happens when a call can't be answered. Could I visit or call for 15 minutes this week? There's no sales pitch. If it turns out to be useful, there's a free two-week pilot, but that's optional.
>
> Thanks,
> Sai, atithi.support@gmail.com
