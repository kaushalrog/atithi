# Atithi — strategy, product and money

**Date:** 2026-10-23 · **For:** Sai and Kaushal · **Status:** proposal, needs a founders' decision on §1.

Companion docs: `PRODUCT.md` (the voxcheck bet), `COMPETITIVE_ANALYSIS.md` (the testing-tools market),
`METRICS.md`. This document covers the **receptionist business** and how it competes with Outpero.

---

## 1. The decision, in one page

**Keep the product. Change the position, the pricing and the voice.**

We are not rebuilding. Underneath, Outpero and Atithi are the same machine: telephony ↔ streaming model ↔
tools ↔ dashboard. We already own the hard part. What separates us from them is **commercial machinery**
(self-serve, usage pricing, recordings, outbound) and **voice quality** — not core engineering.

Three decisions to confirm:

1. **Position:** not "AI receptionist for clinics" (too small to pitch) and not "Outpero but better"
   (a feature race we lose to a funded incumbent on their home turf). Instead:

   > **Voice AI you can audit. Every promise the agent makes is checked against what actually happened.**

   Platform-sized story, defensible wedge, and it is already built (`proof.py`).

2. **Entry:** clinics, dental, diagnostics — where a false confirmation is a real problem and the buyer is
   risk-averse. Outpero is chasing real-estate volume; we take the trust-sensitive end first.

3. **Expansion:** same engine, add outbound + campaigns later, sell into the accounts we already serve.

**Big platform, narrow entry.** Build wide, sell narrow, expand from inside the account.

---

## 2. Where Outpero wins, where we win

Their wedge is **outbound speed-to-lead**: a Meta/Google lead arrives, the AI calls it in under 30 seconds in
Telugu, qualifies and books. Inbound reception is a side feature for them. Our wedge is inbound reliability.

### They are ahead on

| Gap | Why it costs us customers |
|---|---|
| **Self-serve signup + free credits** | Anyone can try them in 30 seconds. We need Sai to onboard by hand. This caps growth at however many businesses we can personally visit. |
| **Usage-based pricing, no lock-in** | ₹5/min prepaid credits removes buying friction. Our flat ₹1,999/mo is both a harder sell and a margin risk (§5). |
| **Call recordings (audio)** | Owners want to *listen*, not read transcripts. Table stakes. |
| **Structured lead extraction + sentiment** | "3BHK, ~90 lakhs, site visit Sat 11:00" is what makes a dashboard feel worth paying for. |
| **Outbound + bulk CSV campaigns** | This is where Indian SMB money is: real estate, coaching, insurance. Inbound-only halves our market. |
| **Caller memory** | Returning callers picked up where they left off. |
| **CRM webhooks / custom API actions** | Required by any business with an existing system. |
| **WhatsApp Business templates** | Ours is sandbox only. |
| **Voice choice (Standard/Premium) + 7 languages** | We have one fixed voice on the phone path (§3). |
| **Distribution** | 10 city SEO pages, ROI calculator, FAQ schema, live app. We have a private repo. |

### We are ahead on

1. **Proof, not promises.** Their own site hedges: *"AI conversational systems may occasionally vary."*
   That is a hallucination disclaimer. `proof.py` blocks a false "you're booked" before the customer hears
   it, and the dashboard shows "N of N promises backed by a real record". **Nobody else in this market can
   say that.** This is the whole positioning.
2. **Questions inbox.** They offer "knowledge base training" (you upload what it should know). We close the
   loop: the agent reports what it *could not* answer, the owner answers once, it becomes an FAQ.
3. **Latency.** They advertise 0.8–1.3s. Our Live path measured ~0.1–0.5s gaps on a real call. Verify under
   load, then say it loudly.
4. **Double-booking is structurally impossible**, not a calendar integration detail.

### Strategy

Do **not** fight them on outbound volume: it is their turf, it becomes a price war, and it carries the
heavier regulatory burden (§7). Win inbound + verified + premium voice in trust-sensitive verticals, then
expand outbound into accounts that already trust us.

---

## 3. Voice quality plan

**They do not train voices.** Their Standard ₹5/min vs Premium ₹6.8/min tiers are a vendor's pricing passed
through. Training a neural voice needs 10+ hours of studio audio per voice per language, an ML team and GPUs.
They buy good voices. So should we.

### Why ours sounds worse today

| Channel | Voice | Telugu quality |
|---|---|---|
| Web test widget | `te-IN-ShrutiNeural`, `ta-IN-PallaviNeural` | good — native voices |
| **Real phone calls** | **Gemini Live, `voice_name="Kore"`** | poor — an English-first voice attempting Telugu |

Our good Indian voices are on the channel that matters least; an English-centric voice is on the channel
that matters most. That is the bug.

Behind it is an architecture trade:

- **Outpero**: cascaded (STT → LLM → dedicated Indian TTS). Costs latency (their quoted 0.8–1.3s), buys a
  smooth regional voice.
- **Atithi**: native audio end-to-end (Gemini Live speaks directly). Buys latency (~0.1–0.5s), costs voice
  quality in Indian languages.

For selling in Telugu and Tamil markets, **voice quality beats half a second.** Customers hear a wrong accent
immediately; they do not notice 500 ms.

### The fix — hybrid routing (recommended)

- **English / Hinglish** → keep **Gemini Live native**. Stay the fastest.
- **Telugu / Tamil / Hindi** → **cascaded** through a dedicated Indian TTS.

This gives Outpero-grade regional voices *and* keeps our latency advantage in English — better than either
of us offers today. `tts.py` was built for exactly this swap ("To switch to Sarvam voices, rewrite ONLY this
file").

### Provider shortlist (decide by listening, not by reading)

| Provider | Why |
|---|---|
| **Sarvam AI (Bulbul)** | Indian, purpose-built for Indian languages. First to try for Telugu/Tamil. |
| **ElevenLabs** | Best naturalness + voice cloning. Most expensive. |
| **Cartesia (Sonic)** | Built for realtime agents — lowest added latency. |
| **Smallest.ai (Waves)** | Indian, low latency, Indian languages. |
| **Azure Speech** | The paid, official version of the edge-tts we already use. |

**Action:** build a voice A/B harness that speaks the *same* Telugu sentence through every provider we hold a
key for, saves them side by side, and let both founders pick by ear. Cheaper than any opinion.

### Signature voice = cloning, not training

ElevenLabs, Cartesia and Sarvam clone a voice from ~30 seconds to a few minutes of clean audio. That is how
we get a distinctive Atithi voice in hours, not months.

> **Only clone a voice we have explicit written permission to use** — a hired voice actor, or one of us.
> Never a celebrity, a YouTube clip, or anyone who has not agreed, in writing.

Fine-tuning our own TTS only makes sense later, when vendor per-minute cost exceeds training cost.

---

## 4. What changes in the product (and what does not)

### Does not change
Agent core, `proof.py`, scheduling/availability, booking integrity, dashboard, auth/multi-tenancy,
telephony bridge, tests and evals. This is the asset.

### Changes
1. **Voice routing** — hybrid per §3.
2. **Pricing + billing** — usage-based credits, see §5. This is a real module, not a config tweak.
3. **Self-serve signup** — sign up, get free minutes, onboard yourself, no founder in the loop.
4. **Positioning surface** — landing page, the demo video, the proof story front and centre.

### Adds (in priority order)
1. Call recordings (audio) + playback in the dashboard
2. Structured lead extraction (intent, budget, requirement, next step) + sentiment
3. Outbound calling + CSV bulk campaigns with retry schedules
4. Caller memory across calls
5. CRM webhooks / post-call payloads
6. WhatsApp Business templates (leave the sandbox)
7. Voice selection (Standard/Premium) exposed to the owner
8. More languages toward parity (7)

Nothing here requires rewriting the engine. All of it hangs off what exists.

---

## 5. Pricing and unit economics

### The trap in today's pricing

Flat **₹1,999/month** against **per-minute costs** (telephony + model) is dangerous. A clinic doing
300 calls × 2 min = **600 minutes**. If our true cost is even ₹3/min, that is ₹1,800 of cost against ₹1,999
of revenue. **One busy client and we lose money on them.** Outpero's usage-based model protects them from
exactly this; ours does not.

### Step zero: measure the real cost per minute

Nothing below is decidable until this table is filled with **measured** numbers from one real metered call.

| Line item | Source | ₹/min (measured) |
|---|---|---|
| Inbound telephony | Twilio / Exotel / Plivo invoice | ___ |
| Outbound telephony | provider invoice | ___ |
| Model (Gemini Live audio in + out) | AI Studio billing | ___ |
| TTS (cascaded path only) | Sarvam / ElevenLabs | ___ |
| STT (cascaded path only) | provider | ___ |
| **Total cost per minute** | | **___** |

**Pricing rule: sell at ≥ 3× measured cost per minute.** Below 3× there is no room for free trials, failed
calls, support and GST.

### Proposed structure (platform fee + included minutes + overage)

Subscription covers the number, dashboard and support; per-minute covers variable cost with margin; included
minutes make it feel like a package instead of a meter.

| Plan | Monthly | Included | Overage | Channels |
|---|---|---|---|---|
| **Trial** | ₹0 | 60 min | — | 1 |
| **Clinic** | ₹1,499 | 300 min | ₹4.5/min | 1 |
| **Growth** | ₹3,999 | 1,000 min | ₹4/min | 3 |
| **Premium voice** | add-on | — | +₹1.5/min | — |
| **Extra channel** | ₹649/mo | — | — | +1 |

Notes:
- Mirror their friction-removers: **no setup fee, no lock-in, free credits to start, prepaid, never expiring.**
- Match **₹649/channel** — it is the market anchor and it maps cleanly to our concurrency limit.
- All prices exclude 18% GST. Say so, like they do.
- **Validate before committing.** These numbers are a starting hypothesis, not a result.

### Revenue milestones

| Stage | Customers | Avg/month | MRR | What it proves |
|---|---|---|---|---|
| Pilot | 3 (free) | ₹0 | ₹0 | It survives real callers |
| First money | 5 | ₹1,500 | ₹7.5k | Someone will pay |
| Signal | 20 | ₹2,000 | ₹40k | Repeatable sale |
| Real | 50 | ₹2,500 | ₹1.25L | A business |
| Scale | 200 | ₹2,500 | ₹5L | Raise or run profitably |

The only milestone that matters right now is **"First money."** Everything in this document is in service of it.

---

## 6. Scale ("maximum power output")

- **Concurrency is the hard ceiling** — concurrent Live sessions on our model tier. Outpero monetises this as
  ₹649/channel; we should too. Enforce per-business channel caps and sell more.
- **Leave files for a database.** SQLite + CSV is right for 2 demo clients, wrong for 50 businesses with
  thousands of calls. Postgres before scale.
- **Outbound needs a real job queue** with retry schedules and per-number rate limits (`callbacks.py` is the seed).
- **Run `bench_load.py`** and publish the measured concurrent-call ceiling internally before selling channels.

---

## 7. Risks

1. **Outbound calling is regulated in India.** TRAI's commercial-communication rules (DND registries,
   telemarketer registration, DLT) govern unsolicited commercial calls. Inbound reception carries little of
   this; **bulk outbound carries a lot**, and it may require the registered business entity we do not have
   yet. **Verify with someone who knows Indian telecom compliance before building outbound.** This is a
   flagged risk, not legal advice.
2. **DPDP Act / personal data.** We store patient names, phone numbers and recordings indefinitely in plain
   files. A retention policy, a delete path and consent in the greeting are required before a real pilot.
   Already open in `TODOS.md`.
3. **Flat pricing margin risk** — §5.
4. **Two founders, one fork.** `Saireddy21072007/atithi` is a fork of `kaushalrog/atithi`. Decide which repo
   is canonical and write down who owns what, while it is still easy.
5. **Competing on their home turf.** Outpero is Hyderabad-based and Telugu-first. Our edge must be position
   and trust, not geography or features.

---

## 8. Sequence

**Now (before any new feature):**
1. Measure true cost per minute (§5, step zero).
2. Voice A/B harness → pick the Telugu/Tamil provider by ear.
3. Decide §1 positioning as founders. Write the answer at the top of this file.

**Next (commercial machinery):**
4. Usage-based pricing + credits.
5. Self-serve signup with free minutes.
6. Call recordings + structured lead extraction.

**Then (platform width):**
7. Hybrid voice routing live on the phone path.
8. Outbound + CSV campaigns (after the §7.1 compliance check).
9. Caller memory, webhooks, WhatsApp templates.

**Then deploy, and sell.**

---

## 9. Open questions for the founders

1. Does the voxcheck bet in `PRODUCT.md` stay paused? This document assumes the receptionist is the business
   and the proof check is its weapon, not a separate free product.
2. Who owns go-to-market (selling, outreach) vs build? Two engineers both building is why there are zero
   customers at 110 commits.
3. Flat-with-included-minutes, or pure usage like Outpero?
4. Which vertical first — dental, diagnostics, or multi-speciality clinics?
