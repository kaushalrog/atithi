# Hyperframes Composition Brief: Atithi

## Objective
Create a short, polished launch film for Atithi: an AI receptionist whose answer becomes a saved booking the owner can see.

## Output
- Composition directory: `brag-output/composition/`
- Rendered video: `brag-output/brag.mp4`
- Format: landscape, 1920x1080, 30 fps
- Duration: 25.0 s

## Source Material
- Project root: `/Users/kaush/Downloads/voxagent-main`
- **Primary files read:**
  - `README.md`, `site/src/components/{Hero,Signal,BookingRecord,Pilot}.tsx`, `site/src/styles/tokens.css`, `site/docs/PRODUCT_TRUTH.md`;
  - `web/logo.svg`, `web/index.html` (test chat, call history, bookings);
  - `demo/film/BRIEF.md` (the owner's direction).
- Product name: Atithi
- **Tagline:** "Every caller, welcomed." (the product's own tagline)
- **Key UI to recreate:** the real owner-portal screens, captured today on synthetic data (`assets/screens/`, cut from `demo/film/screens/`):
  1. the test chat's availability check;
  2. the booking request;
  3. the transcript's "Result: confirmed";
  4. the bookings row "confirmed".
- **Copy that must appear verbatim:**
  - "Every caller, welcomed."
  - the UI text as captured: "Checked availability for 31 Oct", "Booking request: …", "Result: confirmed", "confirmed".
- **Framing copy:** this asserts nothing new about the product.
  - "A call isn't a booking."
  - "It listens. Then it checks the real calendar."
  - "Then it books, and saves."
  - "You see what it said, and what it saved."
  - "Early access · atithi.support@gmail.com"

  Each is grounded in `PRODUCT_TRUTH.md` list 1: availability via a live tool, the booking saved before confirming, transcripts with actions, and the early-access pilot.

## Creative Direction
- Tone preset: polished
- Creative direction: a quiet, premium product film, editorial on warm paper
- **Interpretation:**
  - long still holds;
  - per-word blur-in titles that land and stay dead still;
  - slow soft crossfades (0.6–0.8 s) between worlds;
  - motion lives in the product UI arriving piece by piece and in the Welcome Signal stroke.
- Angle: the moment talk becomes a record. The signal resolves into the check only after "Result: confirmed".
- Hook: a teal waveform draws in; "A call isn't a booking." lands word by word by about 0.7 s.
- Outro: the signal draws wave → doorway → line and resolves into the Atithi mark (beat-locked 23.02 s), then "Atithi / Every caller, welcomed.", held to the end.
- **Avoid:**
  - generic SaaS language;
  - abstract filler, floating cards, glows, gradients, purple;
  - phone or WhatsApp imagery (not live);
  - statistics of any kind, and the promise-check metric (the dashboard stats row and "verified" badges);
  - `voxcheck`;
  - real-looking personal data beyond the synthetic demo.

## Visual Identity
- **Background:** `#F5F3EA` paper; `#ECE8DA` deeper paper; cards `#FFFDF7` with a `#DDD8C8` hairline.
- **Text:** `#182A25` ink; `#5A6A64` muted.
- **Accent:** `#176F63` teal (the signal, highlights); `#E2EEE9` teal-soft (highlight wash).
- **Display font:** Instrument Serif 400, local woff2 in `assets/fonts/`.
- **Body font:** Instrument Sans 400/500/600, local woff2.
- **References from the project:** the Welcome Signal paths (`site/src/components/Signal.tsx`); the Atithi mark (`web/logo.svg`).

## Storyboard (absolute seconds)
1. **Hook** — 0.0–3.2 — "A call isn't a booking." + the wave draws.
2. **Reveal** — 3.2–5.8 — mark + "Atithi" + "Every caller, welcomed."
3. **Listen, then check** — 5.8–11.8:
   - left: "It listens. / Then it checks the real calendar.";
   - right: the chat pieces arrive in turn: the customer's question, the "Checked availability" chip (underlined, ~8.0 s, on a beat), the reply with the free times.
4. **The booking lands** — 11.8–18.8:
   - "Then it books, and saves.";
   - the 10:30 request, then the "Booking request" chip (~14.0 s), then "All set, Ananya!…";
   - **payoff at 17.02 s (beat-locked):** the chat card carries away; the transcript "Result: confirmed" (highlighted) and the bookings row "confirmed" arrive; the signal line draws to the confirmed pill; its check lands at 18.02 s (beat-locked) with the bell.
5. **The owner's view** — 18.8–21.8 — "You see what it said, and what it saved." with both records.
6. **Outro** — 21.8–25.0 — the signal resolves into the mark at 23.02 s; "Atithi", "Every caller, welcomed.", "Early access · atithi.support@gmail.com".

## Audio
- **Role:** a warm bed under picture plus sparse professional accents.
- **Arc:** quiet bed from 0 (1.0 s fade-in); the track's own lift at about 17 s carries the payoff; fade out over the final 1.5 s.
- **Music:** `assets/music/happy-beats-business-moves-vol-1-by-ende-dot-app.mp3`, volume about 0.35. Credit: Sascha Ende, ende.app (CC BY 4.0).
- **Music cue guidance:** preset `.agents/skills/brag/assets/music/cues/…vol-1….music-cues.json`, 120.19 BPM, beats every 0.5 s.
  - Strong cues used: 17.02 (payoff), 18.02 (check), 23.02 (mark).
- **Audio-reactive:** none. A deliberate choice for the polished tone; motion comes from the UI and the stroke.
- **Audio-coupled moments:**
  - availability chip: soft impact (`impactSoft_medium_002`);
  - booking chip: soft impact (`impactSoft_medium_004`);
  - confirmed check: bell (`impactBell_heavy_000`), low.
- **SFX:** low-HF-risk picks from `sfx-analysis.md`, peak about 1 frame after the picture; nothing on titles.
