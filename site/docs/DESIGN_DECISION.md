# Design decision

## The three directions

Each direction was built as a real coded hero in `site/prototypes/`, all sharing one Welcome Signal path (`signal.js`), and screenshotted at 1440 × 900 in the browser on 2026-10-21.

| Criterion | A · Editorial hospitality (`a-editorial.html`) | B · Living signal (`b-signal.html`) | C · Product theater (`c-theater.html`) |
|---|---|---|---|
| Memorable in 5 s | **Strong.** The 112 px serif headline, with "A booking that lands." in teal, is the thing you remember. | Medium. The line itself reads best here (wave → doorway → check), but a centred white headline on dark could belong to any AI company. | Weak. The headline shrinks to make room for the stage. |
| Communicates the product | Good: the eyebrow, the paragraph and a small booking record. | Medium: "turns words into a confirmed booking" is abstract without UI. | **Strong**: question, availability check, saved booking, record. |
| Original, not a template | Good. Editorial type on warm paper isn't the category default. | Poor. Dark + glow + centred is the category default (see Vapi and ElevenLabs in `REFERENCE_RESEARCH.md`). | Medium. Close to the Granola pattern. |
| Product evidence as hero | Weak: the record card is small and the signal sits below the fold. | None. | **Strong.** |
| India without clichés | Good. Real names, ₹ prices, Coimbatore hours from the demo configs. | Neutral. | Good. |
| One developer, zero budget | Easy. | Easy. | Medium. The stage needs real choreography. |
| Responsive / accessible | The huge serif needs careful scaling. | Glow and contrast need care. | Two-column stage collapses awkwardly on phones. |

## Decision: A's hierarchy, carrying C's evidence, drawn with B's line

**The chosen composition, "The line that ends in a record":**
- The first screen is A's editorial headline, *A better first hello. A booking that lands.*, set large and asymmetric on warm paper.
- Under it, the Welcome Signal runs the width of the page as one thin teal stroke:
  1. it starts as a voice wave beside a real customer question ("Do you have a slot tomorrow at 10:30?");
  2. it passes through a doorway arch (the front desk, the threshold of hospitality);
  3. its final check **lands inside a booking record card**, a faithful recreation of the record Atithi saves.

The motif says the product's promise without a metaphor to decode: the conversation becomes a record.

**Why B lost:** its line drawing was the clearest of the three, so the line survives. But the dark, centred, glowing composition is exactly what the category already looks like, and it shows no booking. Its *Listen · Check · Confirm* labels moved to the "How it works" section.

**Why C lost:** the evidence was right but the first screen had no voice; the headline lost to the UI. Its stage became the **interactive sample booking** directly below the hero, where it has room to play properly.

## System

- **Palette** (tokens in `src/styles/tokens.css`): paper `#F5F3EA`, ink `#182A25`, teal `#176F63` (5.4 : 1 on paper), brass `#D7A66B` only as a fill (2.0 : 1, too light for text) with `#8A5A1E` (5.3 : 1) when brass must be read. All text pairings were computed: the lowest is muted text on the deeper paper, 4.65 : 1.
  - The portal's teal (`#0f766e`) is a near relative, so the site and the product feel like one family.
- **Type:**
  - *Instrument Sans* for UI and body, the same face the portal uses.
  - *Instrument Serif* (regular only) for display lines.
  - Both are OFL and self-hosted as latin-subset woff2 via `@fontsource`, so the page makes no third-party font request.
- **Motion:**
  - The signal draws once, in 1.6 s.
  - The hero copy is visible at first paint; nothing is gated on animation (the family.co lesson).
  - The sample booking moves only on state changes.
  - With reduced motion everything is static and complete.
- **Not used:**
  - stock photos, people on headsets, gradients, orbs, particle fields, glassmorphism;
  - logo walls, quotes, metrics;
  - Indian ornament; the India in the page is in the names, the ₹, the hours and the Telugu.
