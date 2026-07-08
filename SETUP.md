# VoxAgent Setup Guide

Two things need setting up: a **Gemini API key** (required — the brain) and
**Google Sheets** (optional — bookings fall back to a local `bookings.csv` if you
skip this, so the demo works either way).

---

## Part 1: Gemini API key (5 minutes, required)

1. Go to **https://aistudio.google.com** and sign in with your Google account.
2. Click **"Get API key"** in the left sidebar (or go directly to
   https://aistudio.google.com/apikey).
3. Click **"Create API key"**. If it asks you to pick a Google Cloud project,
   choose **"Create API key in new project"** — you don't need to understand
   projects for this to work.
4. Copy the key that appears (it looks like a long random string).
5. In the VoxAgent folder, copy `.env.example` to a new file named exactly `.env`:
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

The goal: create a robot account ("service account") that VoxAgent uses to write
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
4. A `.json` file downloads. Move it into the VoxAgent folder and rename it to
   exactly **`credentials.json`**.

**This file is a secret** — anyone with it can write to sheets shared with the
robot. It's already in `.gitignore`.

### Step 5 — Create the bookings sheet and share it

1. Go to **https://sheets.google.com** and create a blank spreadsheet.
   Name it `VoxAgent Bookings`.
2. (Optional — VoxAgent adds it automatically if missing) put this header in row 1:
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

### Step 6 — Point VoxAgent at it

In `.env`:
```
GOOGLE_SHEETS_CREDENTIALS_PATH=credentials.json
SHEET_ID=paste_the_sheet_id_here
```

Done. Next booking lands in the sheet. If anything about Sheets fails, VoxAgent
prints a warning and writes to `bookings.csv` instead — the conversation never
breaks.

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

### Step 3 — make your laptop reachable from the internet

Twilio must be able to reach your server. Easiest way while testing — ngrok:

1. Download from **https://ngrok.com/download**, sign up (free), and run the
   `ngrok config add-authtoken ...` command they show you once.
2. Start VoxAgent (`run.bat`), then in another terminal:
   ```
   ngrok http 8765
   ```
3. ngrok prints a line like `https://ab12cd34.ngrok-free.app` — copy it into `.env`:
   ```
   PUBLIC_BASE_URL=https://ab12cd34.ngrok-free.app
   ```
4. Restart VoxAgent so it reads the new `.env`.

(The free ngrok URL changes every restart — update `.env` when it does. For a
permanent URL later: an ngrok paid domain, or host the server on a cloud VM.)

### Step 4 — point the number at VoxAgent

1. Twilio console → **Phone Numbers → Manage → Active numbers** → click your number.
2. Under **Voice Configuration → A call comes in**, choose **Webhook** and paste:
   ```
   https://YOUR-NGROK-URL/twilio/voice
   ```
   Method: **HTTP POST**. Save.

### Step 5 — call it!

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
