# Atithi Setup Guide

Two things need setting up: a **Gemini API key** (required — the brain) and
**Google Sheets** (optional — bookings always live in the local `bookings.db`
database and show on the dashboard; a Sheet just receives a copy of each one).

Testing without spending money or touching real data: see
[docs/SAFE_TESTING.md](docs/SAFE_TESTING.md).

---

## Part 1: Gemini API key (5 minutes, required)

1. Go to **https://aistudio.google.com** and sign in with your Google account.
2. Click **"Get API key"** in the left sidebar (or go directly to
   https://aistudio.google.com/apikey).
3. Click **"Create API key"**. If it asks you to pick a Google Cloud project,
   choose **"Create API key in new project"** — you don't need to understand
   projects for this to work.
4. Copy the key that appears (it looks like a long random string).
5. In the Atithi folder, copy `.env.example` to a new file named exactly `.env`:
   ```
   copy .env.example .env
   ```
6. Open `.env` in any editor and paste your key:
   ```
   GEMINI_API_KEY=paste_your_key_here
   ```
   No quotes, no spaces around the `=`.

**Never share this key or commit it to git.** The `.gitignore` already protects it.

---

## Part 2: Google Sheets for bookings (15 minutes, optional)

The goal: create a robot account ("service account") that Atithi uses to write
booking rows into a Google Sheet you own.

### Step 1 — Create a Google Cloud project

1. Go to **https://console.cloud.google.com** and sign in.
   First visit: accept the terms of service.
2. At the top-left, click the **project dropdown** (next to the "Google Cloud"
   logo), then click **"New project"**.
3. Name it `voxagent` and click **Create**. Wait a few seconds, then make sure
   the dropdown at the top now shows `voxagent` (click it and select it if not).

### Step 2 — Enable the Google Sheets API

1. In the search bar at the top of the console, type **"Google Sheets API"**
   and click the result.
2. Click the blue **"Enable"** button. Wait until the page changes.

### Step 3 — Create a service account

1. In the top search bar, type **"Service accounts"** and open it
   (it's under "IAM & Admin").
2. Click **"+ Create service account"** at the top.
3. Service account name: `voxagent-sheets`. Click **"Create and continue"**.
4. It asks about roles — you can **skip this** (click "Continue") and skip the
   last step too (click "Done"). No roles are needed because we'll share the
   sheet with it directly.

### Step 4 — Download the credentials file

1. On the Service accounts page, click the account you just created
   (`voxagent-sheets@voxagent-....iam.gserviceaccount.com`).
2. Go to the **"Keys"** tab.
3. Click **"Add key" → "Create new key"** → choose **JSON** → **Create**.
4. A `.json` file downloads. Move it into the Atithi folder and rename it to
   exactly **`credentials.json`**.

**This file is a secret** — anyone with it can write to sheets shared with the
robot. It's already in `.gitignore`.

### Step 5 — Create the bookings sheet and share it

1. Go to **https://sheets.google.com** and create a blank spreadsheet.
   Name it `Atithi Bookings`.
2. (Optional — Atithi adds it automatically if missing) put this header in row 1:
   `timestamp | client_id | name | phone | service | date | time | status`
3. Open `credentials.json` in an editor and copy the value of `"client_email"`
   (looks like `voxagent-sheets@voxagent-....iam.gserviceaccount.com`).
4. In the spreadsheet, click **Share**, paste that email, set it to **Editor**,
   untick "Notify people", and click **Share/Send**.
   *This step is what actually grants access — without it you'll get a
   403 permission error.*
5. Copy the **sheet ID** from the browser address bar. In
   `https://docs.google.com/spreadsheets/d/1AbC...XyZ/edit`, the ID is the long
   `1AbC...XyZ` part between `/d/` and `/edit`.

### Step 6 — Point Atithi at it

In `.env`:
```
GOOGLE_SHEETS_CREDENTIALS_PATH=credentials.json
SHEET_ID=paste_the_sheet_id_here
```

Done. Each new booking is saved in `bookings.db` first, then copied into the
sheet. If anything about Sheets fails, Atithi prints a warning and the
booking is still safe in `bookings.db` — the conversation never breaks.

The Sheet is a **copy for you to read**. Atithi doesn't read it during
normal operation, so cancelling or editing a row there does NOT free the slot
for the agent.

**Upgrading from an older version (Atithi) that used a Sheet?** Older versions saved
bookings *only* in the Sheet. Before taking new bookings, copy them in once:

```
python storage.py import-sheet
```

Until you do, the server prints `NEW BOOKINGS ARE PAUSED` and `/admin` shows
it, because a new booking could otherwise land on a slot that's already taken
in the Sheet. If the Sheet has no bookings to keep, run
`python storage.py import-sheet --skip` instead.

**Going back to an older version:** first run
`python storage.py export-csv bookings.csv --force` (the old file is kept as a
`.bak` copy), so the older code sees every booking. When you upgrade again,
changes the older code made to `bookings.csv` are picked up automatically; in
Sheets mode, run `import-sheet` again.

---

## Part 3: The phone system — Twilio (your part, ~30 minutes)

Everything in the code is ready; you only add money and keys. When you finish
this section, calling your Twilio number rings straight into the AI
receptionist, and the admin console's "Call now" button starts working.

### Step 1 — Twilio account and number

1. Go to **https://www.twilio.com** → Sign up (free trial gives ~$15 credit).
2. Verify your email and your own mobile number when asked.
3. In the console click **Phone Numbers → Buy a number**. A **US number
   (+1…)** costs ~$1.15/month and works instantly — start with that.
   (Indian +91 numbers exist on Twilio but need regulatory documents from a
   registered business — do that later, when you have a paying client.)
4. Buy the number. Note it down.

### Step 2 — copy your keys into .env

On the Twilio Console home page you'll see **Account SID** and **Auth Token**.
Put them in `.env`:

```
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=your_auth_token
TWILIO_NUMBER=+1xxxxxxxxxx
```

### Step 3 — go live (one command)

Live calls are **off** until you switch them on. First work through the
checklist in [docs/SAFE_TESTING.md](docs/SAFE_TESTING.md) (tests pass, strong
admin password, a test business), then add to `.env`:

```
ENABLE_LIVE_CALLS=true
```

and run:

```
run.bat phone
```

Your first call is a verification step (SAFE_TESTING.md §5): one security check
on the audio connection can only be confirmed against real Twilio traffic.

That's it. The command opens a free tunnel to your laptop, points your Twilio
number's webhook at it automatically (through Twilio's API), and starts the
server. When it prints **"Atithi is LIVE — call +1... now!"**, dial.

Notes:
- If your Wi-Fi blocks Cloudflare tunnels (some campus/office networks do),
  the command tells you. Fix: switch to your phone's hotspot, or make a free
  https://ngrok.com account and add `NGROK_AUTHTOKEN=...` to `.env` — then run
  it again.
- The tunnel URL changes each run; the command re-points Twilio every time,
  so you never touch the Twilio console. For a permanent setup, host the
  server on a small cloud VM instead.

### Step 4 — call it!

Ring your Twilio number from your phone. The AI receptionist answers, books,
and everything appears on the dashboard as channel "phone". Outbound: open
`/admin` → "Place an outbound call".

**Which business answers?** Add the number to that client's YAML:
```yaml
twilio_number: "+1xxxxxxxxxx"
```
Numbers not mapped to any business go to `DEFAULT_CLIENT` from `.env`.
One number per business — each new client gets their own Twilio number
(~$1.15/month each).

**Trial-account limits:** until you upgrade the Twilio account, it can only
call/receive from phone numbers you have verified in the console, and plays a
short trial notice before connecting. Upgrading (adding a card) removes both.

---

## Capacity: what one server can carry (read before a pilot)

Atithi runs as **one process**. Two things only exist in its memory: the
key that signs phone tickets, and the portal's test-call sessions. So don't
run it with several workers (`--workers 2`) or behind a load balancer. The
server prints its limits at startup, in a line like:

```
[capacity] one process · portal worker threads: 40 · phone call-I/O threads: 8 · MAX_CONCURRENT_CALLS=3 …
```

- **`MAX_CONCURRENT_CALLS`** (default 3) caps live phone calls. Set it to what
  your Gemini Live tier allows (free tier: about 3 sessions). Callers beyond it
  hear "all our lines are busy".
- **Phone call-I/O threads:** `max(8, 2 × MAX_CONCURRENT_CALLS)`. They run each
  call's database work, so a slow booking never freezes other callers' audio.
- **Portal worker threads:** 40, shared by every portal request. A typed or
  voice turn holds one for as long as the model takes to answer. The model's
  retry waits are capped at 25 s and speech at 15 s, so one turn can't hold a
  thread for much longer than that.
- **Web test-call sessions:** 20 per business, 500 in total, 60 turns each.
  Closing the test widget frees its session at once. At 20, the business's oldest
  idle session makes room; idle ones are cleared after 2 hours anyway.

What has been measured: `python bench_load.py --suite full` runs an offline,
fake-provider workload of 1–10 simultaneous calls or chats. Results are in
`docs/perf/` and `docs/PERFORMANCE_AUDIT.md`. Those numbers measure Atithi's
own code only. They don't say how fast Gemini, Twilio or edge-tts will be, and
they don't prove any number of real concurrent calls. For real numbers, set
`VOXAGENT_PERF_LOG=perf.jsonl` during a pilot and read `/admin` → `/api/admin/perf`.

---

## Customer texts (booking confirmations and reminders)

When a booking is made, moved or cancelled, Atithi can text the customer from
your Twilio number, and remind them the day before. Each business can turn it
off in **Settings → Customer texts**.

It is **off** until you set `ENABLE_SMS=true` in `.env` (and Twilio is set up,
Part 3). While it's off, nothing is sent: every message is written to
`notifications.jsonl` as a `dry-run`, so you can read exactly what customers
would get first.

Reminders run once a day from a scheduled command (cron, or Task Scheduler on
Windows):

```
python notify.py reminders
```

It texts tomorrow's appointments, each only once, so running it twice is safe.

**India:** texts to Indian numbers are only delivered after DLT registration
(your sender ID and message templates) with a telecom operator. Register
before switching it on for a real business.

---

## Talk to a person, and missed-call callbacks

Both need the live phone line (Part 3) and are **off** until you switch them on.

**Live handoff** (`ENABLE_HANDOFF=true`): when a caller asks for a person, is
upset, or has an urgent problem, the receptionist says "connecting you now"
and the call rings the number in **Settings → Phone line**. If nobody picks up
in 25 seconds the caller hears that the team will call back, and the caller is
already in **Leads**. Without the switch (or on website chat) the receptionist
takes their number as an URGENT callback lead instead.

**Callbacks** (`ENABLE_CALLBACKS=true`): two ways a caller can be owed a call:

* **Missed-call mode** (Settings → Phone line): your number declines calls with a
  busy tone, which costs the caller nothing, and Atithi rings them back. This is
  how many Indian customers already ask for a call.
* **Lines busy**: instead of "call again later", the caller hears "we'll call you
  back in a few minutes".

The server rings them back by itself (checked every minute), but only while
the business is open, once per number per 6 hours, at most 30 a day per
business, and never more than a day late. They show on the **Calls** page
under "Callbacks owed", where the owner can mark one handled if they called
themselves. `python callbacks.py run` does one round by hand.

**Cost:** each callback is an outbound Twilio call plus a Gemini Live session.

---

## Website chat

Customers can chat with your receptionist on your own website. In the portal,
open **Settings → Website chat**, tick the box and save. A one-line snippet
appears; paste it into your website just before `</body>`:

```
<script src="https://YOUR-ATITHI-SERVER/widget.js" data-atithi="wk_..." async></script>
```

It adds a chat button in the corner. The chat runs in a frame served by your
Atithi server, so it can't read your website and your owner login code is
never on the page. Chats appear in **Calls** with the channel `website`.

It's public, so it's capped: 10 new chats per visitor per 10 minutes, 30 open
chats per business, 300 messages per business per day (set
`widget_daily_limit` in the business YAML to change it) and 500 characters per
message. Past the daily cap, visitors are asked to phone instead and no model
call is made. Your Atithi server must be reachable over HTTPS at a public
address for the snippet to work on a live website.
