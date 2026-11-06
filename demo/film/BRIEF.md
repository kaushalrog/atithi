# Atithi product film: brief for `/brag`

**Run from the repo root:**

```
/brag --full --tone polished --format landscape --duration 25 --title "Atithi — Every caller, welcomed"
```

Then paste the creative direction from the owner (below, "Direction"). Afterwards, make a separate 9:16 version for Reels. A 60–90 s walkthrough is a different film; don't squeeze a tutorial into this one.

## Assets (use these, nothing older)

| File | What it is |
|---|---|
| `screens/chat-1-availability.png` | Owner portal test chat: the customer asks for a slot tomorrow morning; the receptionist **checks availability** (action chip) and offers 9:30 / 10:00 / 10:30 |
| `screens/chat-2-booked.png` | Same chat: the customer picks 10:30 and gives a name and number; a **booking request** action, then "All set, Ananya! I have booked…" |
| `screens/transcript.png` | The owner's call history for that conversation: **"Checked availability → Found 16 free slots"** and **"Booking request → Result: confirmed"** sit right before the "booked" reply. This is the proof that the confirmation matches a successful tool result. |
| `screens/bookings.png` | The owner's bookings list: the same booking, status **confirmed** |
| `screens/conversation.json` | The exact words of that conversation |
| `logo.svg` | The Atithi mark and wordmark |

**How these were made (2026-10-30):** a real conversation with the live model in the **current build**, on a throwaway copy of the data.
- **Business:** a synthetic one, "Demo Dental Studio", Sample Road, Hyderabad (demo address), +91 90000 00000.
- **Customer:** synthetic, Ananya Rao, 90000 12345.
- **Date:** the appointment is "tomorrow" relative to the recording (31 Oct). Prefer saying "tomorrow" in the film over a fixed date.

**Brand:**
- Colours: warm paper `#F5F3EA`, deep ink `#182A25`, Atithi teal `#176F63`, brass `#D7A66B` as tiny accents only.
- Type: Instrument Serif for display lines, Instrument Sans for everything else.
- Signature: the Welcome Signal in `site/src/components/Signal.tsx`. A voice waveform becomes a doorway arch, then a straight line that ends in a check.

## Storyboard (owner's, 25 s)

| Time | Scene |
|---|---|
| 0–2 s | "A call isn't a booking." A subtle waveform appears. |
| 2–5 s | The Atithi logo emerges. "Every caller, welcomed." |
| 5–10 s | The customer asks for an appointment; Atithi checks availability (`chat-1-availability.png`). |
| 10–16 s | A slot is chosen, the booking succeeds, and the record appears (`chat-2-booked.png`, then `transcript.png` "Result: confirmed", then `bookings.png`). **The strongest moment** is the cut from the confirmed booking to the saved record. |
| 16–21 s | The owner's view: calls and bookings (`transcript.png`, `bookings.png`). |
| 21–25 s | The Welcome Signal resolves into the Atithi logo. |

**The waveform resolves into the check only after the booking is saved** (the "Result: confirmed" beat), never before.

## Rules: do not break these

1. Show only what `site/docs/PRODUCT_TRUTH.md` lists as working.
   - **Working:** the test chat; availability checks; booking, cancel and move; leads; the questions inbox; the owner dashboard.
   - **Not live:** phone calls and WhatsApp. They may appear only as "coming next", never as working. No ringing phone, no WhatsApp UI.
2. **No `voxcheck`.** It is not built.
3. **No statistics:**
   - no conversion rates, no call counts, no "N of N promises";
   - no dashboard stats row (it showed "100%" on a tiny sample);
   - no promise-check metric presented as a general guarantee.
4. Only the synthetic data above. Never the old walkthrough (`demo/atithi-demo.mp4`): it has old fixed dates, a business phone number and address, and the 100% stat.
5. Every "booked" on screen must come with the confirmed result (transcript chip or bookings row).
6. Atithi is honest that it's an AI. Don't imply it's a human receptionist.
7. Readable text: crop the screens tightly, hold each long enough to read, nothing tiny.

## Direction (owner, 2026-10-30)

A premium, cinematic product launch film.
- **Audience:** owners of Indian clinics, dental practices, salons and coaching institutes.
- **Style:** minimal, editorial and sophisticated. Warm paper, deep ink and Atithi teal. The custom Welcome Signal animates from waveform to doorway to saved-booking confirmation. Fluid transitions, refined typography, elegant motion and tasteful music. Real product UI must be prominent.
- **Avoid:** generic AI visuals, purple gradients, random floating cards, template-like SaaS animation.

**Story:**
1. A customer wants an appointment.
2. Atithi listens.
3. It checks real availability.
4. The customer chooses a slot.
5. Atithi makes the booking.
6. The owner sees the recorded result.

**Before declaring it done:** watch the whole render, check the opening two seconds and every transition, and improve the composition.
