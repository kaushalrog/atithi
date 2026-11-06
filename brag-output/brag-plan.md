# Brag Plan: Atithi

Run: 2026-10-30-223342. Invocation:

```
/brag --full --tone polished --format landscape --duration 25 --title "Atithi — Every caller, welcomed"
```

The owner's direction is in `demo/film/BRIEF.md`.

## Step 1 rubric (inspected: `README.md`, `site/src/**`, `site/docs/PRODUCT_TRUTH.md`, `web/index.html`, `agent.py`, `demo/film/screens/*`)

1. **What is the app?** An AI receptionist for small Indian businesses that take bookings (clinics, salons, coaching institutes). It answers customers, checks the business's live booking calendar, books them in, and keeps a record the owner can read.
2. **Most impressive claim:** the booking is real. The transcript shows "Booking request → Result: confirmed" before the receptionist says "booked", and the same booking sits in the owner's list as confirmed.
3. **Visual hook:** the Welcome Signal (`site/src/components/Signal.tsx`). One teal stroke: a voice waveform, then a doorway arch, then a straight line that ends in a check.
4. **UI to show:** the owner portal's test chat (availability check, then booking), the call transcript with its action chips, and the bookings list. All are fresh 2× captures made today on synthetic data (`demo/film/screens/`).
5. **Shortest satisfying video:** 25 s. The owner's storyboard has six beats. The polished tone gets longer holds, not more scenes.
6. **Tone:**
   - Preset: `polished`.
   - Direction: "a quiet, premium product film, editorial on warm paper".
7. **Audio:** a warm, low corporate bed that stays under the picture, a handful of soft, motion-matched accents, and one restrained hit on the saved-record payoff.
8. **Share caption:** "A call isn't a booking until it's saved. Atithi answers, checks the real calendar, books, and shows the owner the record. Every caller, welcomed."
9. **User flow worth showing:**
   1. A customer asks for a slot tomorrow morning.
   2. Atithi checks availability and offers 9:30, 10:00 and 10:30.
   3. The customer picks 10:30 and gives a name and number. The booking request returns "confirmed". The owner sees it in Bookings as **confirmed**.

**Personal data:** everything on screen is synthetic.
- Business: "Demo Dental Studio", Sample Road, Hyderabad (demo address), +91 90000 00000.
- Customer: "Ananya Rao", 90000 12345.
- Nothing from the old walkthrough is used (it has fixed old dates, a business address and phone, and a 100% stat).

## What is this app?
An AI receptionist that turns a customer's question into a saved booking, and shows the owner the proof.

## The angle
"A call isn't a booking." Plenty of things can talk. This film is about the moment talk becomes a record. The Welcome Signal carries it: a voice line that only resolves into the check **after** the save returns "confirmed".

## Hook (first 2–3 seconds)
On warm paper, a thin teal voice waveform draws in. "A call isn't a booking." lands word by word in large Instrument Serif by 1.0 s and holds dead still.

## Key moments (the middle)
- The test chat. The customer's question, then the **"Checked availability"** chip, then three real free times. The chip is the hero: Atithi looked it up and didn't guess.
- The customer picks 10:30. The **"Booking request"** chip appears, then the receptionist's "All set, Ananya!".
- **Payoff:** a cut to the transcript, where **"Result: confirmed"** sits highlighted right before the reply. Then the Bookings row: Ananya Rao · Scaling & polishing · 10:30 · **confirmed**. The signal's check lands on the confirmed pill.

## Outro / punchline
The signal draws once more (wave, doorway, check) and resolves into the Atithi mark. Then "Atithi", "Every caller, welcomed.", and a small "Early access · atithi.support@gmail.com". Hold for 2 s or more.

## User flow worth showing
Question → availability check → slot chosen → booking confirmed → saved record. (Above.)

## Tone
- Preset: polished
- Creative direction: a quiet, premium product film, editorial on warm paper
- Interpretation:
  - few scenes with long, still holds;
  - per-word blur-in titles that land and stay dead still;
  - slow soft crossfades (0.6–0.8 s) between worlds;
  - motion lives in the product UI and the signal line, never in floating cards.

## Format: landscape — 1920x1080
## Duration: 25 s

## Visual identity (from the project: `site/src/styles/tokens.css`, `web/logo.svg`)
- **Colours:**
  - Background: `#F5F3EA` (paper); deeper paper `#ECE8DA`; card `#FFFDF7`.
  - Accent: `#176F63` (teal); `#0F5249` (teal-deep); brass `#D7A66B` (tiny fills only).
  - Text: `#182A25` (ink); `#33463F` (body); `#5A6A64` (muted).
- **Fonts:** display is Instrument Serif 400; body is Instrument Sans 400/500/600. Both are OFL and ship as woff2 in `site/node_modules/@fontsource`.
- **Strongest visual element:** the Welcome Signal paths and the booking-record card from the site's hero.

## Share copy (draft)
"A call isn't a booking until it's saved. Atithi answers your customers, checks the real calendar, books them, and shows you the record. Every caller, welcomed."

## Audio direction
- **Role:** warm bed under picture, plus sparse professional accents.
- **Music:** `happy-beats-business-moves-vol-1-by-ende-dot-app.mp3`. Measured: it holds about −18 dB RMS for the first 16 s, then lifts to −16 dB from 17 s. That is a calm opening with a lift at the payoff. CC BY 4.0, credit Sascha Ende (ende.app).
- **Treatment:**
  - starts at 0 with a 1.0 s fade-in;
  - low bed, volume around 0.35;
  - fades out over the final 1.5 s under the end card.
- **Music cue guidance:** preset `assets/music/cues/…vol-1….music-cues.json`, 120.19 BPM.
  - Strong cues in window: 16.02, 17.02, 17.52, 18.52, 20.02, 23.02 s.
  - Lock the **saved-record payoff to 17.02 s**, and the **logo resolve to 23.02 s**.
  - Beat grid (0.5 s apart) for chip landings, at every other beat at most, since the chips are readable text.
- **Audio-reactive:** none. Polished restraint; the signal and the UI carry the motion (documented choice, not a failure).
- **SFX:** sparse, motion-matched, low high-frequency risk.
  - a soft drop when each action chip lands;
  - one warm bell or soft impact on the payoff only;
  - nothing on titles.
- **Audio-coupled moments:**
  - "Checked availability" chip (soft drop);
  - "Booking request" chip (soft drop);
  - "Result: confirmed" + record (the single payoff hit, beat-locked 17.02 s).
- **Restraint rule:** no whooshes on every cut, no typing clicks, nothing over the hook line.

## Storyboard

### Scene 1 — Hook — 0.0–3.4 s (3.4 s)
- **On screen:** paper ground. A thin teal waveform (the signal's wave) draws left to right through the lower third. "A call isn't a booking." in Instrument Serif, about 8% of frame height, ink, per-word blur-in, landed by 1.0 s, held still to 3.0 s. Then it blurs out.
- Sequential/interaction: words arrive one by one (0.07 s apart).
- Audio intent: the bed fades in quietly; no hit.
- Audio-coupled idea: none.
- Transition mood: soft → Scene 2 (the waveform stays as the bridge).

### Scene 2 — Reveal — 3.4–6.2 s (2.8 s)
- **On screen:** the Atithi mark (teal tile, white microphone) and the wordmark "Atithi". Under it, "Every caller, welcomed." in Instrument Serif italic-free regular, muted ink.
- Sequential/interaction: the mark settles, then the wordmark, then the line.
- Audio intent: warm and calm.
- Transition mood: soft crossfade → Scene 3.

### Scene 3 — Listen, then check — 6.2–12.4 s (6.2 s)
- **On screen:** left, a quiet label "It listens. Then it checks the real calendar." (two short lines, each held at least 1.2 s). Right, the real test-chat screen, `chat-1-availability.png` cropped to the customer bubble, the chip and the reply, large and readable.
- The **"Checked availability for 31 Oct"** chip gets a teal underline drawn under it when it is in focus.
- Sequential/interaction:
  1. the customer bubble appears;
  2. then the chip;
  3. then the reply with the three times;
  4. hold the full set at least 2 s.
- Audio intent: gentle forward motion.
- Audio-coupled idea: a soft drop as the chip lands.
- Transition mood: slide or carry-across → Scene 4.

### Scene 4 — The booking lands — 12.4–19.4 s (7.0 s)
- **On screen:** label "Then it books, and saves." Right, `chat-2-booked.png` cropped to the "10:30 works…" bubble, the **"Booking request"** chip, and "All set, Ananya! I have booked your teeth cleaning for tomorrow…".
- **Payoff, beat-locked at 17.02 s:** carry the chat into the record.
  - The transcript crop (`transcript.png`: "Booking request…" + "Result: confirmed") takes focus, with **"Result: confirmed"** highlighted.
  - The Bookings row (`bookings.png`) settles beneath it.
  - The signal's straight line draws to the row, and its check lands on the **confirmed** pill.
- Sequential/interaction: bubble → chip → reply → (payoff) transcript highlight → bookings row → check.
- Audio intent: the music lifts naturally at 17 s; one soft bell on the check.
- Audio-coupled idea: a soft drop on the "Booking request" chip; a bell on the confirmed check.
- Transition mood: clean → Scene 5.

### Scene 5 — The owner's view — 19.4–22.4 s (3.0 s)
- **On screen:** "You see what it said, and what it saved." (8 words, held at least 2.5 s) over the quiet transcript and bookings crops.
- Audio intent: settle.
- Audio-coupled idea: none.
- Transition mood: soft → Scene 6.

### Scene 6 — Signal resolves — 22.4–25.0 s (2.6 s)
- **On screen:**
  - The Welcome Signal draws once (wave, doorway, check). Its check becomes the Atithi mark at 23.02 s (beat-locked).
  - "Atithi" and "Every caller, welcomed." hold dead still to the end.
  - A small line: "Early access · atithi.support@gmail.com".
- Audio intent: the music fades out under the card.
- Audio-coupled idea: none (the bell already played).
- Transition mood: end.

**Total:** 3.4 + 2.8 + 6.2 + 7.0 + 3.0 + 2.6 = **25.0 s**

**Music mood for this video:** warm, calm, confident (corporate bed kept low).
**Audio summary:** a quiet bed under the hook and the product UI, a soft drop on each real action, one bell when the booking is saved, and a fade under the logo.

## Claims check (from `site/docs/PRODUCT_TRUTH.md`)
- **Shown as working:** the test chat; the availability check; booking; transcripts with actions; the bookings list.
- **Not shown:**
  - phone or WhatsApp as working (no phone imagery at all);
  - `voxcheck`;
  - any statistic or promise-check metric;
  - the dashboard stats row.
- Every "booked" on screen is paired with its "Result: confirmed" chip or the confirmed row.
- The "early access" line is true (`site/src/components/Pilot.tsx`), and the email is the owner-supplied pilot address.
