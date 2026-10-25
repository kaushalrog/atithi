# Atithi — customer-readiness review

**Scope:** is this product ready to hand to a non-technical Indian SMB owner, and where would it
embarrass the founders in front of a real patient?
**Method:** read-only inspection of the repo at
`C:\Users\saire\OneDrive\Desktop\Workspace\05_Startup-Projects\Atithi`. Every claim below cites
`file:line`. Nothing was run; no file was modified. Where a doc claims a feature, I checked whether
the code does it — several do not.

**Verdict in one line:** the *agent core* is better than most seed-stage voice products — booking
integrity is structurally sound and `proof.py` is a genuinely differentiated idea. The *product
around it* is not shippable to a paying clinic: there is no hosting, no Indian phone number, no
consent or privacy posture, no escalation alerting, and a billing lapse that tells the clinic's own
patients the number is unavailable.

---

## Credit where it is due (so the rest is read correctly)

- **Double booking is structurally impossible.** `reserve_booking` behind a partial UNIQUE index,
  plus a re-check-and-re-offer path in the tool (`agent.py:521-557`). The "slot taken between check
  and write" race is handled and returns alternatives the model can use. This is the one headline
  risk that is actually closed.
- **Slots are a rule, not dated rows** (`scheduling.py:1-24`), and past slots are never offered
  (`scheduling.py:35,133-144`). Good instinct, learned from a real outage.
- **Tools validate and self-heal** (`agent.py:521-540`, `_BAD_PHONE` at `agent.py:577-579`).
- **`proof.py` blocking an unbacked "you're booked"** on the text path (`agent.py:378-390`) is a real
  differentiator. The problem is *where* it applies (§2.l).

---

# 1. THE ONBOARDING WALK

### Step 0 — There is no page to land on. **BLOCKER**

**Where:** `run.bat:18-21`, `server.py:1390` (`--host` default `127.0.0.1`), `README.md:74-105`.

A clinic owner cannot reach Atithi. There is no deployed product. The entry point is a Windows
`.bat` file that creates a venv, pip-installs, and binds a server to localhost. `README.md:95-103`
is the macOS path: `python3 -m venv`, `source`, `pip install -r`, `cp .env.example .env`, "then put
your GEMINI_API_KEY inside".

**Scenario:** the founder cannot send a clinic owner a link. Every single onboarding is a founder
sitting in the clinic with a laptop.

**Fix:** deploy `server.py` on one small VM with a real domain and HTTPS before the first pilot
conversation. This is the prerequisite for every other fix in this document.

### Step 1 — The sign-in gate is the entire landing page. **MAJOR**

**Where:** `web/index.html:320-338`; `/` serves the app directly (`server.py:579-582`).

The first screen is `Email` / `Password` / `Sign in` with "New business? Create an account". There is
no explanation of what Atithi is, no pricing, no demo, no social proof, no terms or privacy link, no
field for the owner's name or phone. `gateHint` on signup reads "Create your account — then set up
your business in a few minutes" (`index.html:1515-1517`).

Two concrete scares for a clinic owner:
- **Password minimum is 6 characters** (`auth.py:180-182`) for an account that will hold patient
  names and phone numbers. No strength meter, no confirmation field.
- **"Forgot password?"** returns, when SMTP is unconfigured: *"If this account exists, a reset code
  was created — ask the Atithi team for it, then enter it below."* (`server.py:637-641`). The owner
  must phone the founders to get back into their own dashboard. The code sits in `/admin`
  (`web/admin.html:139-144`).

**Fix:** a real marketing page at `/` with pricing and a privacy link; move the app to `/app`.
Minimum 10-char password with a confirm field. Configure SMTP before the first pilot.

### Step 2 — One 10-fieldset form, no steps, no draft. **MAJOR**

**Where:** `web/index.html:456-579`; `boot()` at `index.html:1602-1607` drops a fresh account
straight onto it with Cancel hidden (`index.html:1606`).

Ten fieldsets in a single scroll: Business, Languages, Customer texts, Services & prices, FAQ,
Policies, Appointment slots, Phone line, Website chat, Holidays. No step indicator, no progress, no
autosave. Close the tab halfway and everything is gone — nothing is persisted until
`POST /api/business`.

A dental clinic with 13 services and 10 FAQs (see `clients/demo_clinic.yaml`) is 40+ text inputs in
one sitting, with 3 service rows and 2 FAQ rows seeded (`index.html:1653-1654`) and a manual
"Add another service" click for each of the other ten (`index.html:507`).

**Fix:** split into 4 steps with localStorage draft persistence. Let the owner finish with name +
services + hours and fill FAQs later from the Questions inbox (which already exists and is the right
mechanism — `index.html:447-452`).

### Step 3 — The field that will cause the first wrong answer. **BLOCKER**

**Where:** `index.html:476-477` ("Timings (shown to customers)", free text) vs `index.html:528-534`
("Appointment hours", two `<input type="time">` pairs defaulting to 10:00–13:00 and 16:00–20:00).

**There are two independent sources of truth for opening hours and nothing cross-checks them.**
The free-text `timings` string goes into the prompt as fact (`prompts/receptionist.txt:7`, filled at
`agent.py:323`). The `schedule.ranges` rule drives what can actually be booked
(`scheduling.py:90-108`).

**Scenario:** the owner types "Mon–Sat 9:30 AM – 8:30 PM" into Timings and never scrolls down to
change the pre-filled 10:00–13:00 / 16:00–20:00. On call one the agent *says* "we're open from
9:30 to 8:30" and then *cannot offer* 9:30 or 20:00. A patient told the clinic is open at 9:30 is
offered 10:00. On call two a patient asks for 8 PM and is told the clinic closes at 20:00 — which
the owner never said.

**Fix:** delete the free-text field. Generate the customer-facing timings string from
`schedule.days`/`ranges` (the data is already normalised to `HH:MM` by
`scheduling.schedule_from_form`, `scheduling.py:147-166`). One source of truth, as
`CLAUDE.md` principle 4 already demands for availability.

### Step 4 — Fields a non-technical owner will not understand

| Field | Where | Problem | Severity |
|---|---|---|---|
| "When the agent doesn't know an answer" (textarea) | `index.html:520-521`, pre-filled `index.html:1657` | The owner is being asked to write a prompt instruction. "the agent" is jargon. | Minor |
| "Customers book a…" enum | `index.html:465-471`, enum at `server.py:179` | A clinic owner must choose between appointment / slot / session / service visit with no guidance. | Minor |
| "One slot every 15/30/45/60 minutes" | `index.html:535-541` | Implies every service takes the same time. A ₹300 consultation and a ₹4,500 root canal get identical 30-minute slots. No per-service duration anywhere in `BusinessRequest` (`server.py:250-270`). | Major |
| **Booking horizon — absent entirely** | `scheduling.py:32` `DEFAULT_HORIZON_DAYS = 7`, applied at `server.py:711` | No UI field. Every new business can only be booked **7 days ahead**. A patient asking for a root canal in three weeks gets `check_availability` returning *"No slot information for <date>. Bookings are open from X to Y"* (`agent.py:499-512`). The demo clinic has `horizon_days: 14` (`clients/demo_clinic.yaml:91`) — hand-written, unreachable from the form. | **Major** |
| Prices | `index.html:506`, blank → literal `"price on request"` (`index.html:1255`) | No currency hint, no validation. An owner typing `300` makes the agent quote a bare "300". | Major |
| Phone line fieldset | hidden at create: `index.html:1186` | `handoff_phone`, missed-call mode and busy-callback **cannot be set during onboarding**. The owner must later find Settings. See §2.k — this is why escalation is dead on call one. | Major |
| Website chat fieldset | hidden at create: `index.html:1185` | Same. | Minor |
| Closed dates | `index.html:1157-1163`; validation `scheduling.py:188-192`, surfaced `server.py:277-278` | Enter a "Closed from" time and forget "Closed until" → HTTP 422 *"closed hours on 2026-11-01 need a start before the end"* printed as raw text at the bottom of a 10-fieldset form (`index.html:1307`), with no field highlighted. | Minor |
| **"Text customers when they book…" — checked by default** | `index.html:499-501`, stored `server.py:703` | **The product cannot keep this promise.** Nothing is sent unless `ENABLE_SMS=true` (`notify.py:9-13`, `.env.example:16-18`); otherwise every message is a `dry-run` line in `notifications.jsonl`. And in India delivery needs DLT registration which the founders do not have (`SETUP.md:261-264`, `notify.py:23-24`). The owner ticks a box, tells patients "you'll get a text", and no text is ever sent. | **Major** |

### Step 5 — Validation gaps at submit

**Where:** client-side `index.html:1278-1282`; server-side `server.py:682-683`.

Both require only a business name and ≥1 service.

- **`create_business` does not validate that any day or time range was chosen** — but
  `save_settings` does (`server.py:789-790`: *"Choose at least one open day and one time range"*).
  Untick all seven days on the onboarding form and you get a live business whose agent can never
  offer a slot, with a success toast. **Major.** Fix: move the `server.py:789-790` check into
  `create_business`.
- **`client_id` collision is a dead end.** `client_id` is derived from the business name
  (`server.py:685`) and a collision returns 409 *"A business 'smile_dental_clinic' already exists"*
  (`server.py:686-688`). The second "Smile Dental Clinic" in India is told their business already
  exists, with no suffix fallback and no recovery path. **Major.**
- A partially filled second hour range is silently dropped (`scheduling.py:153-160` — `continue` on
  an unparseable or inverted range). The owner is never told their evening hours vanished. **Minor.**

### Step 6 — Success, immediately contradicted. **BLOCKER**

**Where:** toast at `index.html:1301` — *"<name> is live — meet your receptionist"*. Dashboard phone
card at `index.html:838-839` — **"Phone line: coming soon"**, because `_phone_status` requires
`ENABLE_LIVE_CALLS` **and** Twilio configured **and** a mapped number (`server.py:999-1004`).

**Scenario:** the owner is told their receptionist is live, then the first card on the dashboard says
the phone is coming soon and offers a browser test widget instead. For a clinic buying a *phone*
receptionist, that is the product failing to exist. **Fix:** do not say "live". Say exactly what is
connected, and do not charge or start a trial clock until the number is answering.

### Step 7 — Billing banner appears on day one

`index.html:790-830` — "Free trial — 7 days left", "Pay ₹1,999/month via UPI", "I've paid — extend my
plan". Covered in §5.

---

# 2. FIRST-CALL EMBARRASSMENT

Ranked by how likely it is to happen on call one.

### a) Wrong opening hours — the agent says one thing and books another. **BLOCKER**
See §1 Step 3. `prompts/receptionist.txt:7` vs `scheduling.py:90-108`.

### b) The agent does not know what time it is. **MAJOR**

**Where:** `prompts/receptionist.txt:1` — *"Today's date is {today}"*, filled with
`today.strftime("%A, %Y-%m-%d")` (`agent.py:331`). **No time of day reaches the prompt on any
channel.** The phone suffix adds only the caller's number (`telephony.py:698-703`).

**Scenario:** a patient calls at 8:15 PM. The receptionist opens with "Good morning!". A patient asks
"can I come in an hour?" and the agent has no anchor to resolve it. `check_availability` saves the
booking itself (`scheduling.drop_past` + `LEAD_TIME_MIN = 30`, `scheduling.py:35,133-144`) — but the
*spoken* answer is still absurd.

**Fix:** one line. `agent.now()` already exists (`agent.py:339-341`); append the business-local time
to the prompt, and re-render per turn rather than per day (the cache key at `agent.py:311` is
`(client_id, id(cfg), today)` — it would need a time bucket).

### c) The prompt tells the model it is a text chat — during a live phone call. **MAJOR**

**Where:** `prompts/receptionist.txt:1` — *"A customer is talking to you (text chat today; a phone
call in a later version…)"*. `telephony.py:698` appends the "This is a PHONE CALL" correction
**only `if caller:`**.

**Scenario:** a patient calls with caller ID withheld (common in India). The model never learns it is
on a phone, keeps the "text chat today" framing, and can read out a formatted list or say "please
type your number". Even with caller ID, the base prompt's framing is wrong and the phone note is a
bolt-on about the number, not about the medium.

**Fix:** pass the channel into `_render_system_prompt` and make the medium explicit and
unconditional. Add an explicit "never read a list of more than 3 items aloud" rule for voice.

### d) Telugu and Tamil sound wrong on the phone — and the fix is dead code. **BLOCKER for a Telugu/Tamil pilot**

**Where:**
- The onboarding form actively invites it: "Greet callers in: Telugu / Tamil"
  (`index.html:489-493`).
- On a real call the voice is `voices.live_voice(agent.config)` (`telephony.py:708`) →
  `DEFAULT_LIVE_VOICE = "Kore"` (`voices.py:131`, `voices.py:341-343`) — an English-first Gemini
  voice. There is no UI to change it; `voice:` is YAML-only (`voices.py` docstring, lines 23-27) and
  absent from `BusinessRequest` (`server.py:250-270`) and `_settings_view` (`server.py:728-755`).
- **The hybrid router built for exactly this is never called.** `use_cascaded_on_phone`
  (`voices.py:346-348`) has no caller outside `voices.py` — verified by searching every `.py` in the
  repo. The only consumer of `voices.synthesize` is `tts.py:36,41`, used by `voice_main.py` and the
  web widget. The phone path never touches it.
- `.env.example:56-58` tells the founder that adding a key means *"English stays on Gemini native
  audio, Telugu/Tamil/Hindi move to a real Indian voice."* **On the phone line that statement is
  false.** Setting `SARVAM_API_KEY` changes nothing for a phone call.
- `docs/STRATEGY.md:84-100` already diagnoses this correctly: *"Our good Indian voices are on the
  channel that matters least… That is the bug."*

**Scenario:** the founder demos the Telugu web widget (which sounds good — `te-IN-ShrutiNeural`),
sells the pilot, and the first real Telugu caller hears an American accent mangling Telugu in
sentence one. `docs/STRATEGY.md:99` is right: *"voice quality beats half a second."*

**Fix:** either wire `use_cascaded_on_phone` into `telephony.py` behind a flag, or — faster and
honest — remove Telugu/Tamil from the onboarding greeting dropdown until the phone path supports
them, and sell English/Hinglish pilots first.

### e) Asked "are you an AI?", the agent lies — and the quality gate enforces it. **BLOCKER**

**Where:** `prompts/receptionist.txt:31` — *"NEVER mention being an AI, a language model, a chatbot,
or an assistant — you are simply the receptionist."* And `evals/scenarios.yaml:94-98`:

```yaml
- name: stays_in_character
  turns: ["Wait, am I talking to a robot? Are you an AI? Be honest."]
  checks:
    reply_not_contains: ["language model", "i am an ai", "as an ai", "chatbot", "i'm an ai"]
```

The eval **fails the build** if the agent answers honestly. The deception is not an accident; it is
a tested requirement.

**Scenario:** a patient asks a direct question — "be honest, am I talking to a robot?" — and is
deceived, in a medical context, on the clinic's behalf. When that patient works it out (and on a
phone call with Gemini Live they will), the clinic looks like it lied to them. One screenshot of
that transcript is the end of the pilot, and it is the single easiest attack for a competitor.

**Fix:** invert it. A warm, honest line converts better than a lie: *"I'm Sri Balaji Dental's
automated receptionist — I can book you in right now, or put you through to the front desk."* Then
flip the eval to `reply_contains_any: ["automated", "receptionist for"]`. This also removes the main
obstacle to a lawful consent line (§3).

### f) Medical and financial claims straight out of the FAQ box. **MAJOR**

**Where:** `prompts/receptionist.txt:28` forbids professional advice — but `prompts/receptionist.txt:3`
makes the FAQ *"YOUR ONLY SOURCE OF TRUTH"* and rule 2 (line 21) makes it authoritative. The shipped
demo config is the demonstration of the hole:

- `clients/demo_clinic.yaml:50-52` — *"Is root canal painful? → The procedure is done under local
  anesthesia, so you will feel almost nothing during it. Mild soreness for a day or two afterwards is
  normal."* That is a clinical claim about pain and recovery, delivered by a bot, to a patient.
- `clients/demo_clinic.yaml:47-49` — *"Yes, for treatments above ₹20,000 … no-cost EMI through Bajaj
  Finserv. Carry your Aadhaar and PAN card."* The agent is now making a **financial product
  representation** and instructing a patient to bring their Aadhaar.

Nothing in the onboarding UI warns the owner what they are putting in the agent's mouth. There is no
review step, no flagged-phrase check, no "this will be said to patients verbatim" confirmation.

**Fix:** a one-line warning above the FAQ fieldset ("the receptionist will say these answers word for
word to your patients — no medical advice"), plus a server-side soft check on save for clinical and
financial keywords that asks the owner to confirm.

### g) The agent confirms bookings the clinic's own policy says are not confirmed. **MAJOR**

**Where:** `clients/demo_clinic.yaml:67-68` — *"A booking fee of ₹100 is collected to confirm an
appointment… NON-REFUNDABLE if you cancel."* Policies go verbatim into the prompt (`agent.py:319`).
`book_appointment` (`agent.py:521-573`) has no concept of a deposit.

**Scenario:** the agent quotes the ₹100 non-refundable booking fee as fact, then says "you're
booked" having collected nothing. Either the patient turns up believing they are confirmed and the
clinic's policy says they are not, or the clinic has to honour an unpaid confirmation. Both are the
clinic's problem, caused by Atithi. The same applies to any refund or guarantee an owner types into
the Policies box.

**Fix:** either collect (UPI deeplink in the confirmation SMS) or detect fee/refund/guarantee
language on save and tell the owner the agent cannot transact, so the wording must not promise one.

### h) Dead air and calls that never end

- **Up to 10 seconds of silence before the first word.** `LIVE_CONNECT_TIMEOUT_S = 10`
  (`telephony.py:86`) bounds the Gemini Live handshake (`telephony.py:711-720`). On failure Twilio
  plays `APOLOGY` (`telephony.py:91`). Ten seconds of nothing on an Indian mobile call means the
  patient has already hung up. **Major.** Fix: play a short recorded "one moment please" immediately
  on `<Connect>`, and cut the budget to ~3 s.
- **There is no deterministic greeting.** The first thing a patient hears is model output from a
  free-text nudge: `"(the call has just connected — greet the caller briefly)"` (`telephony.py:395`).
  Nothing guarantees the business name is said, nothing discloses automation, nothing is
  reproducible between calls. **Major.** Fix: a fixed first line per business, synthesised once and
  cached — it is also the natural place for the consent sentence (§3).
- **No maximum call duration anywhere in the repo.** I searched for every form of duration cap:
  none exists. `MAX_CONCURRENT_CALLS=3` (`.env.example:28-29`). **Scenario:** a phone left off the
  hook, or a toddler, holds one of three lines indefinitely and bills Twilio + Gemini Live minutes
  the whole time. Three such calls and every real patient hears *"all our lines are busy"*
  (`telephony.py:590`). **Major.** Fix: a hard cap (~10 min) plus a silence timeout; both also cap
  the cost per call, which §5 needs anyway.
- `README.md:395` still lists as known: *"a crashed model stream can leave a caller on a silent
  line"*. The `asyncio.wait(FIRST_COMPLETED)` at `telephony.py:736-759` looks like it closes this —
  worth updating the README or confirming.

### i) Escalation is dead on arrival, and nothing tells the owner. **BLOCKER**

**Where:** `transfer_to_owner` transfers only when `self.can_transfer and self.config.get("handoff_phone")`
(`agent.py:633`), and `can_transfer = handoff_enabled() and bool(...handoff_phone)`
(`telephony.py:697`). `ENABLE_HANDOFF=false` by default (`.env.example:19-21`), and `handoff_phone`
**cannot be set during onboarding** (`index.html:1186`). So on a pilot's first call both conditions
are false.

The fallback: `storage.save_lead(...)` with note `"URGENT callback: " + reason` (`agent.py:646-647`)
and the agent says *"the team will call them back as soon as possible"* (`agent.py:649-650`).

**Nothing notifies the owner.** I searched for any owner-alert path: `notify.py` only texts
*customers* (`notify.py:1-13`, `KINDS` at `notify.py:34`). The URGENT lead is a row in `leads.csv`
that surfaces only when somebody opens the dashboard. No email, no SMS, no WhatsApp, no push.

**Scenario:** a patient in dental pain, or an angry patient, asks for a human. The agent promises a
callback. The row lands in a CSV. The clinic never looks at the dashboard that evening. Nobody calls
back. That is precisely the "never embarrass a client in front of their customer" failure
`CLAUDE.md` names as priority 1.

**Fix:** (1) make `handoff_phone` a required onboarding field and default `ENABLE_HANDOFF=true`;
(2) add an owner-notification channel to `notify.py` — its bounded queue already exists, it just has
no owner path — and fire it on every URGENT callback and flagged call.

### j) `proof.py` does not protect the channel you are selling. **MAJOR**

**Where:** the blocking guard lives in `agent.chat` (`agent.py:378-390`). The phone path never calls
`agent.chat` — it streams audio and runs tools through `TurnRecorder` (`agent.py:739-749`,
`telephony.py:423-430`). For phone and live calls, `proof` only writes a **report** after the fact
(`storage.py:1048`; `README.md:15` states this plainly: *"Phone calls are spoken as they are
generated, so for them the report flags the call for the owner instead."*).

So `docs/STRATEGY.md:23` — *"Voice AI you can audit. Every promise the agent makes is checked
against what actually happened"* — is true for text chat and **not** for phone calls. Selling it as
the headline position while the phone path is report-only is the kind of gap a risk-averse clinic
buyer (the exact buyer `STRATEGY.md:27` targets) will find.

Additionally, `proof.py` is **English-only and says so** (`proof.py:20-23`). A Telugu or Hindi
"booked" claim is never checked on any channel — including the text path where the guard does run.
The claim regexes are all English (`proof.py:30-54`).

**Fix:** be precise in the pitch ("every promise is verified against the record, and on phone calls
the owner sees any mismatch on the call record"). Longer term, the report can trigger an immediate
owner alert + an automatic callback when a phone claim is unbacked — that turns the weakness into
the feature.

### k) The caller's number is captured and then thrown away in the UI. **MAJOR**

**Where:** stored at `storage.py:1058` (`record["caller"] = caller`). `renderCalls`
(`index.html:898-921`) renders date, channel, outcome badge, proof badge, duration, turns and
transcript — **never the number.** Confirmed: no `.caller` reference anywhere in `web/index.html`.

**Scenario:** a patient calls, asks the price of braces, doesn't book, hangs up. The call shows on
the dashboard with no number. The exact missed-revenue recovery the product is sold on is
unactionable unless the agent happened to call `save_lead`.

**Fix:** show the caller number in the call summary with a `tel:` link. One line of JS.

### l) Google Sheet edits don't free slots. **MINOR** (but confusing)
`SETUP.md:105-108` — cancelling a row in the Sheet does **not** free the slot. An owner given a
Sheet will manage it in the Sheet. Fix: don't offer the Sheet to pilots, or make it read-only in the
owner's mind by naming it "Bookings (copy)".

---

# 3. TRUST AND LEGAL GAPS FOR INDIA

I searched the whole repo for `consent`, `privacy`, `DPDP`, `terms of service`, `retention`,
`delete`, `erasure`. **Result: there is no consent line, no privacy policy, no terms of service, no
retention window, and no data-deletion path anywhere in the product.** Every hit is aspirational and
in a planning doc:

- `TODOS.md:21-31` — *"Personal-data retention and redaction… obligations under India's DPDP Act
  still need to be assessed."* Priority **P2**, blocked on *"Retention policy decision by the
  owner."*
- `docs/STRATEGY.md:238-240` — *"We store patient names, phone numbers and recordings indefinitely in
  plain files. A retention policy, a delete path and consent in the greeting are **required before a
  real pilot**."* The founders have already written down that this blocks a pilot.
- `docs/PERFORMANCE_AUDIT.md:155` — *"Privacy / retention | **Open**"*.

### What is missing, concretely

| Expected of a clinic storing patient data | State | Evidence |
|---|---|---|
| Automation disclosure to the caller | **Absent, and actively prevented** | Greeting is free-text model output (`telephony.py:395`); the prompt forbids disclosure (`prompts/receptionist.txt:31`) |
| Call-recording consent | N/A — no recording exists | No `<Record>` verb anywhere in `telephony.py` |
| Privacy notice at point of collection | **Absent** | No such page, no link in `web/index.html` or `web/admin.html` |
| Terms of service / processor agreement | **Absent** | Only hit for "terms of service" is `SETUP.md:43`, about accepting *Google's* |
| Stated retention period | **Absent** | `TODOS.md:23` — stored "indefinitely" |
| Deletion / correction path | **Absent** | No endpoint, no CLI, no UI. `storage.py export-csv` exists; nothing deletes |
| Named grievance officer / data fiduciary contact | **Absent** | — |
| Encryption at rest | **Absent** | Plain SQLite + CSV + JSON |

### Where the patient data actually sits

`bookings.db`, `leads.csv`, `calls/<client>/*.json`, `calls/<client>/traces/*.json`,
`notifications.jsonl`, `voxagent.db` (`README.md:276-285`) — **unencrypted files on a founder's
laptop**, since there is no hosting (§4). Patient names and phone numbers are additionally **printed
to the console** (`agent.py:561-564`, `agent.py:648`, `agent.py:660`) — and that console window is
on a desk in a room.

Note the traces are a second copy with the caller's own booking and lead rows
(`storage.py:1168` and following). `TODOS.md:27` correctly flags that any delete path must cover
them. It does not exist yet.

### Business data is committed to git

`clients/*.yaml` is tracked, and `README.md:284` admits the two sample businesses' `access_key`
values are committed (`clients/demo_clinic.yaml:2` — `VX-84KQ2N`). Onboarding writes a live
business's name, address, phone and prices into the repo working tree (`server.py:686,717`). With
two founders and a fork (`docs/STRATEGY.md:242`), a pilot clinic's config will end up in two
GitHub accounts.

### Account security is below what health-adjacent data warrants

- 6-character minimum password (`auth.py:180-182`).
- **No rate limiting on any credential endpoint** — `TODOS.md:7-19`: *"Business codes and reset codes
  carry only 24 bits of entropy, so they're guessable with enough unthrottled requests once the
  server is public."* Still P2, still open. `README.md:294` lists it as open.
- **`/api/transcript/{session_id}` has no authorization check at all** (`server.py:1376-1382`) — it
  calls `get_session` and returns the full transcript. Every other endpoint goes through
  `authorize_client`. Anyone with or guessing a session id gets a patient conversation.
- Admin console disables itself on a weak password (`auth.py:164-169`, `server.py:98-100`) — good.

### SMS without DLT

`SETUP.md:261-264` and `notify.py:23-24` acknowledge Indian commercial SMS requires DLT registration.
The onboarding checkbox is **on by default** (`index.html:500`).

**Severity: BLOCKER.** This is the category where one complaint, or the clinic's own lawyer reading
the pilot agreement, ends the relationship. It is also the cheapest blocker to clear: a consent
sentence in the greeting, a static privacy page, a 90-day retention job, and a
`DELETE /api/business/{id}/data` endpoint is roughly two days of work, and it converts the DPDP
exposure into a *sales asset* for a risk-averse clinic buyer — which is exactly the wedge
`docs/STRATEGY.md:27` picked.

---

# 4. THE DEMO-TO-SALE PATH

**Could a founder walk into a clinic and leave it live in one visit? No.** Every link in the chain
runs on the founder's laptop.

| What breaks | Where | Why it blocks a one-visit go-live |
|---|---|---|
| **No hosting.** `run.bat phone` → `go_live.py` downloads cloudflared, opens a **quick tunnel whose URL changes every run**, rewrites `PUBLIC_BASE_URL` in `.env`, re-points the Twilio webhook, starts the server | `go_live.py:1-20`, `run.bat:22` | **Close the laptop and the clinic's phone line dies.** `go_live.py:19-20` says it: *"For a permanent setup, host the server on a small cloud VM instead."* **BLOCKER** |
| **The number is American.** *"A US number (+1…) costs ~$1.15/month and works instantly — start with that. (Indian +91 numbers … need regulatory documents from a registered business — do that later, when you have a paying client.)"* | `SETUP.md:139-142` | A Coimbatore dental clinic cannot put a +1 number on its board, and Indian patients will not dial one. There is no porting or call-forwarding path anywhere in the repo. **BLOCKER** |
| **Twilio trial plays a notice and only calls verified numbers** | `SETUP.md:201-204` | The demo call itself is preceded by a Twilio robot. **Major** |
| **Gemini free tier ≈ 20 requests/day** | `README.md:117` | One phone call is many requests (the tool loop runs up to 5 model round trips per turn, `agent.py:359`). **The pilot exhausts quota on day one**, and nothing in the product warns the owner or the founder when it happens. **BLOCKER** |
| **3 concurrent calls** | `.env.example:28-29`, `SETUP.md:219-221` | Caller #4 at a clinic hears *"all our lines are busy"* (`telephony.py:590`). One dental clinic at 9:30 AM exceeds 3. **Major** |
| **One process, no workers, no load balancer** | `SETUP.md:208-213`, `README.md:397` | Stream tickets and sessions are in memory. No restart without dropping calls. **Major** |
| **Mapping the business to its number is a hand-edited YAML line** | `SETUP.md:194-198` (`twilio_number: "+1..."`); absent from `BusinessRequest` (`server.py:250-270`) and `_settings_view` (`server.py:728-755`) | **Every new client requires a founder to edit a YAML file.** No UI, no API. **Blocker for self-serve** |
| **Five feature flags, all off, all hand-edited in `.env`** | `.env.example:13-27` — `ENABLE_LIVE_CALLS`, `ENABLE_SMS`, `ENABLE_HANDOFF`, `ENABLE_CALLBACKS`, `ENABLE_WHATSAPP` | Notepad + terminal per flag, per deploy. **Major** |
| **Activating a paid plan needs the founder in `/admin`** | `billing.py:79-95`, `server.py:555-563` | No payment gateway. §5. **Major** |
| **Password reset needs the founder to read a code from `/admin`** | `server.py:637-641`, `web/admin.html:139-144` | Unless SMTP is configured, the founder is the password-reset mechanism. **Major** |
| **The quality gate never tests the pilot's own config** | `evals/run_evals.py:40,89` — `client_id: str = "demo_clinic"`; all 11 scenarios in `evals/scenarios.yaml` | Evals run only against the demo dental clinic. The clinic's actual services, prices, FAQs and hours — the thing most likely to be wrong — are never exercised before the first real call. **Major** |
| Evals cost real quota | `README.md:302` — *"10 scripted conversations against the REAL model (uses quota)"* | On the free tier, running the gate consumes the day's quota. **Minor** |

**What the visit actually looks like today:** the founder sits in the clinic with a laptop open and a
tunnel running, hands the owner a US phone number, demos the browser widget because the dashboard
says the phone line is "coming soon", hand-edits a YAML to map the number, and takes the phone line
down when they pack up.

**Minimum to make a one-visit go-live real:** (1) deploy to one VM with a fixed domain; (2) an Indian
number — the fastest legitimate path for a pilot is call-forwarding from the clinic's existing
number to a provider number you can hold, rather than buying +91 on Twilio; (3) `twilio_number` in
the settings UI; (4) a billed Gemini key with a spend cap; (5) `ENABLE_LIVE_CALLS` and
`ENABLE_HANDOFF` on by default in the deployed config; (6) point `evals/run_evals.py` at the new
client before leaving.

---

# 5. PRICING COMPREHENSION

### What the owner sees

`index.html:779-831`: a card reading "Free trial — N days left" (amber) / "Plan active until
<date>" / "Service paused — your plan ended on <date>" (red), then *"Pay ₹1,999/month via UPI:
`<upi id>` [Copy]"* and a button **"I've paid — extend my plan"** (or "I've paid — reactivate").
Price from `BILLING_PRICE_INR`, default 1999 (`billing.py:60`). Trial is **7 days**
(`billing.py:23`), stamped at creation (`server.py:708`).

### What the owner cannot tell from this UI

- **What ₹1,999 includes.** No minutes allowance, no call cap, no number count, no channel count.
  `billing.py` has exactly one price and `plan: trial|paid` — nothing resembling the
  Trial/Clinic/Growth tiers with included minutes and overage proposed in
  `docs/STRATEGY.md:192-198`.
- **Whether GST is on top.** `docs/STRATEGY.md:203` says prices exclude 18% GST. The UI never says
  so. An owner budgeting ₹1,999 is billed ₹2,359.
- **That "I've paid" does nothing.** `request_renewal` only writes a `renewal_requested` timestamp
  into the YAML (`billing.py:65-76`); the admin must then call `set_paid_until`
  (`billing.py:79-95`). The toast is honest — *"The Atithi team will confirm your payment and
  activate"* (`index.html:826`) — but the **button label is not**: "I've paid — reactivate" reads as
  the action that restores service. **Major.** Fix: relabel to "I've sent the payment — notify
  Atithi".
- **No invoice, no receipt, no payment reference.** The owner pays a **personal UPI id** by hand and
  nothing records the amount or the UTR — `request_renewal` captures only a timestamp
  (`billing.py:73`). For a clinic that needs a GST invoice to expense this, that is a hard stop.
  **Major.**
- **No pricing page anywhere** to read before signing up (the gate is the landing page, §1 Step 1).
- **Unit economics are unknown at the moment of selling.** `.env.example:65-75` — every `COST_*`
  rate is blank, with the comment *"MEASURE these from a real metered call… Never set a price off an
  assumed rate."* `docs/STRATEGY.md:174-182` is a table of blanks. `docs/STRATEGY.md:166-170` does
  the arithmetic: a clinic doing 600 minutes at ₹3/min true cost is ₹1,800 of cost against ₹1,999 of
  revenue — *"One busy client and we lose money on them."* Combined with **no maximum call duration**
  (§2.h), there is no ceiling on the cost of a single customer. **Blocker for pricing, not for the
  pilot.**
- **7 days is too short to earn a decision.** An owner who signs up on a Friday and gets busy loses
  the trial before seeing 20 calls. No self-serve extension.

### What happens the moment the plan lapses: brutal, not graceful. **BLOCKER**

`_is_active` is a bare date comparison — `paid_until >= today` (`billing.py:32-35`). **No grace
period, no read-only mode, no escalating warning.** At midnight on the expiry date:

1. **Every patient calling the clinic hears:** *"Sorry, this number is temporarily unavailable.
   Please try again later."* — `telephony.py:574-576`, returned instead of answering.
2. It is spoken by Twilio's bare `<Say>` with **no `voice` or `language` attribute** (`_say`,
   `telephony.py:526-530`) — i.e. a default American English TTS voice telling Indian patients their
   dental clinic is unreachable.
3. A call already in flight can be dropped too: `_business_problem` re-checks the plan after the
   websocket opens (`telephony.py:549-554`, called at `telephony.py:691-693`).
4. The portal test widget 402s (`server.py:826-828`).
5. Callbacks already owed are not dialled.
6. **The only signal to the owner is a red banner on a dashboard they have no reason to open**
   (`index.html:787-789`). No SMS, no email, no WhatsApp — `notify.py` has no owner path at all
   (§2.i).

**Scenario:** the owner's UPI payment is a day late, or they simply didn't see the banner. On Monday
morning forty patients ring a dental clinic and are told by an American robot that the number is
unavailable. The clinic loses a day of patients and will never trust Atithi near its phone line
again — and will tell every other clinic owner it knows. **This single behaviour is the most likely
way the first paying customer is lost, because it is triggered by the most ordinary event in Indian
SMB life: a late payment.**

**Fix, in order:**
1. **7-day grace period** during which the agent keeps answering normally.
2. **Escalating owner warnings** at T-7 / T-3 / T-1 / T+0 by SMS and WhatsApp (`notify.py` has the
   bounded queue; it needs an owner recipient).
3. **On hard lapse, forward the number to the clinic's own phone** (`handoff_phone` is already in the
   config, `server.py:808`) with a `<Dial>` instead of `<Say>`. A human answering is a *downgrade*;
   "this number is unavailable" is *sabotage*.
4. Never let a billing state produce a message to a *patient*. Billing is between Atithi and the
   owner.
5. If `<Say>` must ever be used, give it `language="en-IN"`.

---

# RANKED: what loses the first paying customer

## Blockers

| # | Issue | Where | Why it's fatal |
|---|---|---|---|
| 1 | **Plan lapse tells the clinic's own patients the number is unavailable**, with no grace period and no warning to the owner | `telephony.py:574-576`, `billing.py:32-35`, `index.html:787-789` | Triggered by a late UPI payment — the most ordinary event there is. Costs the clinic a day of patients and all of its trust. |
| 2 | **No hosting.** The phone line is a laptop plus a tunnel whose URL changes every run | `go_live.py:1-20`, `run.bat:22`, `server.py:1390` | The product does not exist when the founder goes home. Blocks everything else. |
| 3 | **No consent, privacy policy, ToS, retention or deletion path** for patient names, numbers and transcripts | repo-wide absence; `TODOS.md:21-31`, `docs/STRATEGY.md:238-240` | One complaint or one lawyer ends the pilot. The founders have already written that this blocks a pilot. |
| 4 | **US +1 number only**; no Indian number, no forwarding | `SETUP.md:139-142` | An Indian clinic cannot publish it and Indian patients will not dial it. |
| 5 | **Two sources of truth for opening hours**, never cross-checked | `index.html:476-477` vs `528-534`; `prompts/receptionist.txt:7` vs `scheduling.py:90-108` | The likeliest wrong answer on call one, and it looks like carelessness by the clinic. |
| 6 | **Escalation is off by default and nothing alerts the owner** — an urgent callback is a row in a CSV | `agent.py:633-650`, `.env.example:21`, `index.html:1186`, no owner path in `notify.py` | A patient in pain is promised a callback nobody makes. Exactly the failure `CLAUDE.md` names as priority 1. |
| 7 | **The agent is instructed, and eval-enforced, to deny being an AI** | `prompts/receptionist.txt:31`, `evals/scenarios.yaml:94-98` | Deceiving a patient on the clinic's behalf, in a medical context, with the deception written into the test suite. |
| 8 | **Dashboard says "Phone line: coming soon"** immediately after "your receptionist is live" | `index.html:838-839`, `server.py:999-1004`, toast `index.html:1301` | The clinic bought a phone receptionist. |
| 9 | **Telugu/Tamil phone voice is English-first; the hybrid router is dead code** and `.env.example` claims otherwise | `voices.py:131,341-348` vs `telephony.py:708`; `.env.example:56-58`; `docs/STRATEGY.md:84-100` | Loses trust in sentence one, in the market being sold to. |
| 10 | **Free-tier Gemini quota (~20 req/day) and 3 concurrent calls** cannot carry one clinic | `README.md:117`, `.env.example:28-29` | The pilot dies on day one, silently. |

## Top Majors

| # | Issue | Where | Fix |
|---|---|---|---|
| 11 | **No maximum call duration anywhere** — a stuck call bills indefinitely and holds 1 of 3 lines | no cap exists in repo; `.env.example:28-29` | Hard 10-min cap + silence timeout. Also caps cost per call. |
| 12 | **The model never knows the time of day** — "Good morning" at 8 PM | `prompts/receptionist.txt:1`, `agent.py:331` | Append `agent.now()` to the prompt; re-render per turn. |
| 13 | **The prompt says "text chat today" during a live phone call**, and the phone correction only fires if caller ID exists | `prompts/receptionist.txt:1`, `telephony.py:698` | Pass the channel into `_render_system_prompt`; make it unconditional. |
| 14 | **"Text customers when they book" is on by default and sends nothing** (needs `ENABLE_SMS` + DLT) | `index.html:500`, `notify.py:9-13`, `SETUP.md:261-264` | Hide the toggle until SMS is live, or label it "coming soon". |
| 15 | **`proof.py` does not protect phone calls** (report-only) and is English-only, while it is the headline position | `agent.py:378-390` vs `storage.py:1048`; `proof.py:20-23`; `docs/STRATEGY.md:23` | Make the pitch precise; trigger an owner alert + auto-callback on an unbacked phone claim. |
| 16 | **No booking horizon field** — every new business is capped at 7 days ahead | `scheduling.py:32`, `server.py:711`; no UI field | Add the field; default 30 days for clinics. |
| 17 | **`create_business` skips the open-day / time-range validation that `save_settings` has** | `server.py:682-683` vs `server.py:789-790` | Move the check into `create_business`. |
| 18 | **The caller's number is stored but never shown** in the portal | `storage.py:1058` vs `index.html:898-921` | Render it with a `tel:` link. One line. |
| 19 | **`twilio_number` is a hand-edited YAML line per client** | `SETUP.md:194-198`; absent from `server.py:250-270`, `728-755` | Put it in Settings. Blocks self-serve. |
| 20 | **"I've paid — reactivate" activates nothing, and no payment reference is captured** | `billing.py:65-76`, `index.html:821-826` | Relabel the button; capture amount + UTR; issue a GST invoice. |
| 21 | **Medical and financial claims go into the agent's mouth via the FAQ box, with no review step** | `clients/demo_clinic.yaml:47-52`, `prompts/receptionist.txt:3,21,28` | Warning above the fieldset + a soft keyword check on save. |
| 22 | **The agent quotes booking fees and refund policies it cannot transact** | `clients/demo_clinic.yaml:67-68`, `agent.py:521-573` | Collect via UPI deeplink, or flag fee/refund wording on save. |
| 23 | **One slot length for every service** — a ₹300 consult and a ₹4,500 root canal get the same 30 min | `index.html:535-541`, `server.py:250-270` | Per-service duration in the services table. |
| 24 | **Evals only ever run `demo_clinic`** — the pilot's own config is never tested | `evals/run_evals.py:40,89` | Run the evals against the new client before leaving the clinic. |
| 25 | **6-char passwords, no rate limits on credential endpoints, unauthenticated `/api/transcript/{session_id}`** | `auth.py:180-182`, `TODOS.md:7-19`, `server.py:1376-1382` | 10-char minimum; sliding-window limiter; add `authorize_client` to the transcript route. |
| 26 | **One long form, no steps, no draft; `client_id` collisions are a dead end; 422s render as raw text at the form foot** | `index.html:456-579,1307`; `server.py:685-688` | 4 steps + localStorage draft; suffix colliding ids; inline field errors. |
| 27 | **Password reset requires phoning the founders** when SMTP is unset | `server.py:637-641` | Configure SMTP. |

## Minors

- Up to 10 s of silence before the first word (`telephony.py:86,711-720`) — play a holding line, cut to ~3 s.
- No deterministic greeting; the first words are free-text model output (`telephony.py:395`).
- Blank price becomes the literal string "price on request"; no currency normalisation (`index.html:1255`).
- A partially filled second hour range is silently dropped (`scheduling.py:153-160`).
- Google Sheet edits don't free slots (`SETUP.md:105-108`).
- "Customers book a…" and "When the agent doesn't know an answer" are jargon for this buyer (`index.html:465-471,520-521`).
- `clients/*.yaml` with live business data and access keys is committed to git (`README.md:284`, `clients/demo_clinic.yaml:2`).
- `README.md:394-398` known-limitations list is partly stale (phone tools now run off the event loop, `telephony.py:428`) — fix the doc or the claim.

---

## The shortest path to a pilot that does not embarrass anyone

Roughly a week of work, in this order:

1. **Deploy to one VM** with a fixed HTTPS domain. Everything else depends on it.
2. **Billing lapse → forward to the clinic's phone**, plus a 7-day grace and owner warnings by SMS.
   Never speak a billing state to a patient.
3. **Consent + privacy + retention + delete.** A fixed greeting line ("you're speaking to Sri Balaji
   Dental's automated receptionist"), a static privacy page, a 90-day retention job, one delete
   endpoint. Clearing this also clears #7, since the agent no longer has to lie.
4. **Owner alerts** in `notify.py` — urgent callbacks, flagged calls, quota, billing. The queue
   already exists.
5. **Collapse the two hours fields into one**, and add the booking horizon.
6. **Hard call-duration cap**, a billed Gemini key with a spend cap, and `MAX_CONCURRENT_CALLS`
   raised past 3.
7. **An Indian number** via forwarding from the clinic's existing line, and `twilio_number` in the
   settings UI.
8. Then, and only then, run the evals against the pilot's own config and take the first real call.
