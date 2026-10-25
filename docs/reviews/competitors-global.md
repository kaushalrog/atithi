# Global Voice-AI Agent Platform Market — Competitive Baseline for Atithi

**Date checked: 2026-10-25.** All prices USD unless noted. Every figure below carries an evidence
label. Nothing here is invented; where I could not reach a primary source I say "unverified".

**Evidence labels**
- **[Vendor]** — fetched from the company's own pricing page or official docs on 2026-10-25.
- **[Listing]** — third-party aggregator, review site, or competitor blog. Often stale or self-serving.
- **[News]** — trade press.
- **[Paper]** — academic.
- **[Inference]** — my own arithmetic or reasoning, flagged as such.

**Known bias warning:** this market is saturated with SEO comparison blogs written by competitors
(Ringg, Ringly, CloudTalk, Lindy, HappyRobot, Telnyx, Dasha, Emitrr, Trillet all publish "X pricing"
pages about rivals). I pulled primary vendor pages wherever possible and down-weighted the rest.

---

## 1. FEATURE BASELINE — what every serious product ships in 2026

I verified the following against **Vapi's full docs index** [Vendor, `docs.vapi.ai/llms.txt`],
**Retell's pricing/feature page** [Vendor], **ElevenLabs Agents docs** [Vendor],
**Deepgram Voice Agent pricing** [Vendor], **LiveKit pricing** [Vendor], **Cartesia pricing**
[Vendor], **Synthflow enterprise page** [Vendor], and **Sarvam's voice-agent docs** [Vendor].

### Table stakes — present on essentially every serious platform

| Capability | Evidence |
|---|---|
| **Tool / function calling to external systems** | Vapi "Tool integration"; Retell "Webhooks and API Access"; ElevenLabs tools incl. transfer-to-number. [Vendor] |
| **Knowledge base + RAG** | Vapi "Knowledge bases", "Query tool", "Custom knowledge base", "Knowledge Bases V2" API. Retell sells it as a priced add-on (+$0.005/min, $8/KB/mo after 10 free). ElevenLabs accepts PDF/Word/txt/MD/HTML/EPUB up to 20 MB, plus URLs and pasted text. [Vendor] |
| **Warm AND blind/cold transfer to a human** | Vapi has separate docs for "Configure warm transfer modes", "Configure blind transfer modes", "Dynamic call transfers", "Handoff tool". ElevenLabs transfer-to-number defaults to a conference transfer with the AI dropping out, with SIP REFER as the alternative. Bland prices transfer minutes separately ($0.04–0.05/min). [Vendor] |
| **Interruption / barge-in + turn detection** | Universal. Vapi exposes endpointing and interruption models even when running OpenAI Realtime. Sarvam lists "handling of interruptions". [Vendor] |
| **Call recording, transcripts, logs** | Vapi "Call recording, logging and transcribing" plus S3 / GCS / Cloudflare R2 / Azure Blob / Supabase destinations. Retell "Call Analytics and Transcripts". [Vendor] |
| **Analytics + structured post-call extraction + scorecards** | Vapi "Call analysis", "Structured outputs", "Scorecard quickstart", "Boards quickstart", "Monitoring quickstart", Analytics Queries API. Sarvam "call logs, analytics, and custom boards". [Vendor] |
| **Agent testing / simulation / evals** | Vapi "Simulations overview", "Configure an AI tester", "Evals quickstart", "Plan test coverage". Retell lists "Simulation Testing" on the free tier. Sarvam "simulated test calls against scripted scenarios". **This is now baseline, not premium.** [Vendor] |
| **Number provisioning** | Vapi includes 1–10 numbers by plan. Retell $2.00/mo per number. LiveKit 1 free US local, then $1.00/mo; toll-free $2.00/mo. Goodcall includes a local number on every plan. Cartesia includes 1–10 numbers by plan. [Vendor] |
| **SIP trunking / BYO carrier** | Vapi has seven SIP doc pages incl. Twilio and Telnyx. ElevenLabs ships a SIP trunking integration. Retell: "No Charge for Sip Trunking/Custom Telephony". Deepgram and Cartesia assume BYO. [Vendor] |
| **Outbound campaigns / batch calling** | Vapi "Campaigns overview", "Campaign contact data", "Campaign scheduling and lifecycle", "Campaign webhooks", "Campaign voicemail and call screening". Retell "Batch Call +$0.005/dial". ElevenLabs batch calls. Sarvam outbound campaigns. [Vendor] |
| **Voicemail detection** | Vapi "Voicemail Detection" + "Voicemail tool". Sarvam lists voicemail detection. Retell bills voicemail "only for the time the AI agent is active". [Vendor] |
| **Webhooks + named CRM/calendar integrations** | Vapi ships connectors for GoHighLevel, Google Calendar, Google Sheets, Slack, n8n, Make, Sympana, plus "Server URLs", "Server events", "Server authentication", "Webhook logs", "Phone Number Hooks". [Vendor] |
| **Multi-language** | ElevenLabs "5,000+ voices across 31 languages". Vapi has "Multilingual support" docs plus multilingual agent and squad examples. Sarvam: 11 Indian languages + English, incl. code-mixed speech. [Vendor] |
| **Concurrency as an explicit, metered dimension** | Every platform. Vapi 4/10/30 by tier, +$10/line/mo. Retell 20 free then $8/concurrency/mo. ElevenLabs 4→40 by tier with 3x "burst" at 2x price. LiveKit 5/20/up-to-600. [Vendor] |
| **Compliance modes** | Vapi publishes dedicated docs for HIPAA, PCI, GDPR, SOC 2 Type II, Zero Data Retention, EU region/data residency, Recording consent plan, TCPA Consent Guide. Retell Enterprise includes "HIPAA / BAA", RBAC, SSO, custom MSA/DPA. Sarvam: India data residency including PII. [Vendor] |

### Second tier — common but not yet universal

- **PII redaction as a billed feature** — Retell "PII Removal +$0.01/min". [Vendor]
- **Advanced denoising** — Retell +$0.005/min. [Vendor]
- **Branded / verified caller ID** — Retell "Branded Call +$0.10/outbound call"; "Verified Phone Number $10". [Vendor]
- **Multi-agent orchestration** — Vapi "Squads", "Multi-assistant orchestration". [Vendor]
- **Config-as-code / GitOps** — Vapi "CLI Overview", "Config as code (GitOps)", "Agent skills". [Vendor]
- **Policy/safety guardrails as a product** — ElevenLabs Guardrails; Retell "Safety Guardrails +$0.005/min". See §4. [Vendor]
- **Mid-call language switching** — Sarvam lists it explicitly; most Western platforms do not. [Vendor]
- **MCP server for agent authoring** — Sarvam ships one. [Vendor]
- **WhatsApp as a channel** — LiveKit WhatsApp connector; Sarvam "phone, WhatsApp, web, and API". [Vendor]

### What this means for Atithi

Atithi's listed feature set (inbound calls, live availability, booking, lead capture, multi-language)
is **the floor, not a feature list**. Nothing on it is differentiating. The gaps that will be noticed
in a competitive bake-off, judged against the table above:

1. **Warm transfer to a human.** Every competitor has it. For a clinic this is the single most
   requested escape hatch.
2. **Outbound / batch campaigns.** Already on the Stage 4 roadmap — correctly placed.
3. **Agent simulation + evals as a shipped, customer-visible feature.** Atithi has `evals/`
   internally. Competitors expose this to the buyer on the free tier.
4. **Voicemail / answering-machine detection.**
5. **Compliance posture.** No HIPAA equivalent is claimed. For Indian clinics the relevant frame is
   DPDP Act data residency — and **Sarvam already markets "data residency in India, including PII"**
   as a selling point [Vendor]. That is the local compliance axis, and it is a genuine advantage
   Atithi could claim over Vapi/Retell/ElevenLabs (all US-hosted) but currently does not.
6. **Concurrency as a published, metered dimension.** Buyers now expect to see this number.

---

## 2. PRICING — what dominates, and who is cheap vs premium

### The dominant model

**Per-minute usage, metered to the second, with a thin or zero platform fee, and STT/LLM/TTS/telephony
either bundled or passed through at cost.** Three variants:

1. **Unbundled orchestration fee + pass-through** (Vapi, LiveKit, ElevenLabs). Headline rate is small;
   real cost is 1.5–3x it. Vapi $0.05/min hosting; ElevenLabs $0.08/min hosting with "LLM at cost" and
   "no telephony fee". [Vendor]
2. **Bundled per-minute** (Bland, Deepgram Voice Agent, Cartesia Managed Agents). One number covers the
   stack; telephony still separate. [Vendor]
3. **Component-priced with a live estimator** (Retell). Publishes every line item. [Vendor]

**Outside the developer-platform layer, the vertical AI-receptionist products have abandoned
per-minute pricing** in favour of monthly subscription with a non-minute cap — Goodcall meters
**unique customers** and states "No per-minute charges" [Vendor]; Slang.ai charges **per location**
[Vendor]. That is the SMB-facing pricing shape, and it is the one Atithi's buyer will recognise.

### Verified published numbers

#### Developer platforms

**Vapi** [Vendor, vapi.ai/pricing]
- Hosting: **$0.05/min**, pre-paid. Pro tier = "10% of the Vapi hosting fee, with a $999/mo minimum".
- Tiers: No Success Package $0 + usage, **$5 free credits**, 4 concurrent, 1 number, 14-day retention ·
  Core **$29/mo**, 10 concurrent, 5 numbers, 30-day · Pro **$999/mo min**, 30 concurrent, 10 numbers,
  180-day · Premier custom.
- Pass-through shown in its own calculator: Deepgram STT $0.0095–0.0099/min · OpenAI $0.0077–0.0452/min ·
  ElevenLabs voice $0.0146–0.0238/min.
- Transport: Vapi Telephony/SIP, Vapi WebSockets, Daily WebRTC **free**; Twilio inbound $0.008/min,
  outbound $0.014/min; Vonage $0.00814/min; Telnyx $0.0055/min.
- Add-ons: **HIPAA $2,000/mo** · extra concurrency $10/line/mo · extra org $20/mo.
- Vendor's own 1,000 min/mo example: **$82–$129/mo** ($0.082–$0.129/min all-in).

**Retell AI** [Vendor, retellai.com/pricing]
- Headline **$0.07–$0.31/min**, no platform fee, **$10 free credits**, 20 free concurrent calls.
- Components: Retell Voice Infra **$0.055/min** · telephony $0.015/min (free on BYO SIP) ·
  TTS $0.015/min for Retell/Minimax/Fish/Cartesia/OpenAI/Inworld voices, rising to
  ElevenLabs Flash $0.040, Multilingual v2 $0.06, v3 Conversational & v4 Turbo $0.08, v3 & v4 $0.10.
- LLM/min: GPT 5.4 nano $0.0064 · Gemini 3.0 Flash $0.016 · Claude 4.5 Haiku $0.025 · GPT 4.1 $0.045 ·
  GPT 5.6 Terra and Claude 5 Sonnet $0.064 (both marked "Recommended") · GPT 5.4 $0.080/$0.16 ·
  Claude 5.5 Opus $0.128 · GPT 5.5 $0.16/$0.32 · GPT 6 Astra $0.32.
- **Speech-to-speech LLMs** (separate line): GPT Realtime mini **$0.07/min** · GPT Realtime 1.5 and
  GPT Realtime **$0.345/min** · GPT Realtime 2.1 and GPT Realtime 2 **$0.38/min**.
- Vendor's own estimator example: **$0.11/min** = LLM $0.04 + voice infra $0.055 + TTS $0.015 + $0 telephony.
- Add-ons: Knowledge Base +$0.005/min · Batch Call +$0.005/dial · Branded Call +$0.10/outbound ·
  Advanced Denoising +$0.005/min · **Safety Guardrails +$0.005/min** · PII Removal +$0.01/min ·
  **AI Quality Assurance, first 100 min free then $0.10/min** · SMS $0.01/msg.
- Subscriptions: concurrency $8/mo each past 20 · numbers $2.00/mo · KB $8/KB/mo past 10 free ·
  Verified number $10 (page is internally inconsistent on monthly vs one-time) · Retell SMS $20/mo.
- Billing rules: tracked **to the nearest second, no per-call rounding**; billed during silence and
  hold; failed calls not billed; AI billing stops after transfer but telephony continues.
- No HIPAA add-on price published; Enterprise row says "HIPAA / BAA", platform described as "HIPAA-ready".

**Bland AI** [Vendor, bland.ai/pricing]
- Start: **$0.14/min** talk, **$0.05/min** transfer, $0 platform, 100 calls/day, 10 concurrent,
  2 credits + inbound number (described as "$15/mo value"), "No card required".
- Build: **$0.12/min** talk, **$0.04/min** transfer, **$299/mo**, 2,000 calls/day (1,000/hr), 50 concurrent.
- Enterprise: custom, "Contracted to your volume", unlimited daily cap.
- Telephony billed separately (own carrier or Bland's built-in Twilio at pass-through). BYO telephony
  pays **no transfer fees**.
- *Note:* the page does **not** list the $0.015/outbound-attempt and $0.02/SMS charges that
  third-party guides cite — those are **[Listing], unverified**.

**ElevenLabs Agents ("ElevenAgents")** [Vendor, elevenlabs.io/pricing/agents]
- Free $0 / 15 min / 4 concurrent · Starter $6 (first month $1) / 75 min / 6 · Creator $22 ($11) / 275 / 10 ·
  Pro **$99** / 1,238 / 20 · Scale **$299** / 3,738 / 30 / 3 seats · Business **$990** / 12,375 / 40 /
  10 seats + 10 pro voice clones · Enterprise custom.
- **Additional minutes $0.080/min** on every plan. **Burst $0.160/min** — up to 3x the concurrency limit
  at double rate. Text messages $0.003 each.
- **LLM billed "at cost"**; ElevenLabs adds **no telephony fee** (your carrier bills you).
- "Prices exclude all taxes, levies and duties."

**Deepgram Voice Agent API** [Vendor, deepgram.com/pricing] — billed on **websocket connection time**

| Tier | Pay As You Go | Growth |
|---|---|---|
| Standard | **$0.075/min** | $0.068/min |
| Standard – BYO TTS | $0.065/min | $0.051/min |
| Custom – BYO LLM | $0.065/min | $0.059/min |
| Custom – BYO LLM + TTS | **$0.050/min** | **$0.041/min** |
| Advanced | $0.163/min | $0.146/min |
| Advanced – BYO TTS | $0.122/min | $0.110/min |

New accounts get **$200 free credit** (the page does not confirm it applies to Voice Agent usage).

**LiveKit** [Vendor, livekit.com/pricing]
- Build **$0/mo** — 1,000 agent-session min, 5 concurrent, 1 deployment, $2.50 inference credits,
  1 free US local number, 50 US inbound min, 1,000 third-party SIP min, 5,000 WebRTC min.
- Ship **from $50/mo** — 5,000 min then $0.01/min, 20 concurrent, 2 deployments, $5 credits.
- Scale **from $500/mo** — 50,000 min then $0.01/min, up to 600 concurrent, 4 deployments, $50 credits.
- Enterprise custom.
- Calculator default for a phone call: agent session $0.0100 + telephony $0.0100 + LLM $0.0014 +
  STT $0.0075 + TTS $0.0090 + observability $0.0100 = **$0.0479/min**.
- Sample inference: GPT-5 nano $0.0002/min · GPT-4o mini $0.0006 · Deepgram Nova-3 STT $0.0048 ·
  AssemblyAI Universal-Streaming $0.0025 · Cartesia Sonic 3 TTS $0.0300 · Deepgram Aura-2 $0.0180.
- Telephony: US local number $1.00/mo after the free one, inbound $0.01/min; toll-free $2.00/mo,
  $0.02/min; third-party SIP $0.004/min (Ship) or $0.003/min (Scale) past the included block.
- Server and Agents framework are **Apache 2.0 / self-hostable** [Listing].

**Cartesia** [Vendor, cartesia.ai/pricing]
- Free $0 / 20K credits / 8 agent concurrent / 1 number · Pro **$5** / 100K / 12 / 3 ·
  Startup **$49** / 1.25M / 20 / 5 · Scale **$299** / 8M / 60 / 10 · Enterprise custom.
- **Managed Agents call duration: $0.06/min on every priced plan.** Telephony $0.014/min on a
  Cartesia-provided number.
- Credit overage: Pro $65/1M · Startup $45/1M · Scale $38/1M. ("1 credit per character" — [Listing].)
- *Correction to common belief:* there is no "Line" product on the page; the voice-agent offering
  is called **Managed Agents**.

**Synthflow** [Vendor, synthflow.ai/pricing] — **has moved fully upmarket.** The pricing page now
publishes **one tier only: "Enterprise contracts start at $30,000 annually."** No per-minute rate,
no included minutes, no free trial, no self-serve plan. HIPAA appears only as a footer trust badge.
This is a notable 2026 market event: Synthflow used to be the SMB-friendly no-code option.

#### Model/API layer (what the platforms resell)

**OpenAI** [Vendor, developers.openai.com/api/docs/pricing] — per 1M tokens unless noted
- `gpt-realtime-2.1`: audio **$32.00 in / $64.00 out**, cached in $0.40; text $4.00/$24.00.
- `gpt-realtime-2.1-mini`: audio **$10.00 / $20.00**, cached $0.30; text $0.60/$2.40.
- `gpt-realtime-2`, `gpt-realtime-1.5`, `gpt-realtime`: audio $32.00/$64.00. `gpt-realtime-mini`: $10/$20.
- Per-minute: `gpt-realtime-translate` $0.034/min · `gpt-live-transcribe` $0.017 ·
  `gpt-realtime-whisper` $0.017 · `gpt-transcribe` $0.0045 · `gpt-4o-transcribe` $0.006 ·
  `gpt-4o-mini-transcribe` $0.003 · Whisper $0.006.
- **`gpt-live-1`: $0.05 per minute**, "billed per second, without rounding up to a whole minute";
  backend model and tool usage billed separately. This is OpenAI selling a hosted voice-agent
  *session* at the same headline price as Vapi's entire orchestration layer.

**Google Gemini Live** [Vendor, ai.google.dev/gemini-api/docs/pricing, page states last updated 2026-10-22]
- `gemini-3.8-live`, `gemini-3.8-live-extended-thinking`, `gemini-3.1-flash-live-preview`:
  **Free tier — "Free of charge" for both input and output.** Paid: input $0.75 text, **$3.00 or
  $0.005/min audio**, $1.00 or $0.002/min image/video; output $4.50 text, **$12.00 or $0.018/min audio**.
  Grounding with Google Search: "Supported".
- `gemini-3.5-live-translate-preview`: free tier free; paid audio $3.50 (~$0.0053/min) in,
  $21.00 (~$0.0315/min) out; footnote gives an effective ~**$0.0368/min**.
- `gemini-2.5-flash-native-audio-preview-12-2025` (**the family Atithi is built on**): free tier free;
  paid input $0.50 text / $3.00 audio-video, output $2.00 text / $12.00 audio.
- `gemini-3.5-transcribe-live`: free tier free; paid in $3.50 (~$0.005/min), out $21.00 (~$0.004/min).

**Microsoft Azure Voice Live API** — structure confirmed, **dollar figures unverified**. Azure's Speech
pricing pages state that "Voice Live pricing tiers are determined by the LLM models selected by
developers", that some options bill per million tokens including a "Voice Live Lite" tier and a
"Voice Live BYO" option with separate audio input/output rates, that avatar output is charged through
the Text to Speech Avatar interactive-realtime service, and that custom speech/voice training and
hosting bill separately. **Every dollar amount in the cached tables rendered as "$-", so I cannot
report Azure numbers. Treat Azure per-minute pricing as unverified.**

#### Vertical AI receptionists (the layer Atithi actually competes in)

**Goodcall** [Vendor, goodcall.com/pricing] — **the cleanest comparable to Atithi**
- Starter **$79/mo**, 100 unique customers/mo, overage **79¢ each**, ~150 calls/mo, 5 workers,
  1 external tool, ~100 test runs, 1 team member, 30-day call history.
- Growth **$129/mo**, 500 unique customers, overage **26¢**, ~750 calls, 10 workers, 5 tools,
  5x AI usage, 5 members, 90-day history.
- Scale **$299/mo**, 2,000 unique customers, overage **15¢**, ~3,000 calls, 20 workers, 15 tools,
  20x AI usage, 10 members, unlimited history.
- Enterprise custom, with onboarding and an SLA.
- **"No per-minute charges."** Cap counts a unique phone number once per month. Local number included
  on every plan, or forward an existing one. No conventional trial — a free demo agent, "you pay only
  when you connect a number." AI-usage top-ups in $5 increments.

**Slang.ai** [Vendor, slang.ai/pricing] — Core **"Starting at $399 per location"**, Premium
**"Starting at $599 per location"**, Enterprise "Custom Pricing". The page does **not** state the
billing period or any included call volume. Core includes "Full Reservation Integrations";
"Bilingual Support" appears in the feature lists; an "A-La-Carte Products" section names "Private
Events" with no price. No free trial mentioned. — The $99/mo bilingual add-on, $199/mo Tripleseat
add-on, and $379/$539 annual rates are **[Listing], unverified**.

**[Listing] — unverified, third-party only:**
- **Rosie** $49 (250 min) / $149 (1,000 min) / $299 (2,000 min).
- **Dialzara** $29 (60 min) / $99 (220) / $199 (500) / $349 (1,000); overage $0.35–$0.48/min;
  call transfer reportedly requires the $99 tier.
- **Smith.ai** human-staffed $292.50 (30 calls) / $532.50 (60) / $975 (120), per-call overage
  $10.50/$9.50/$7.50; AI plans from $95/mo, with one source citing an AI-first Pro at $385.
- **Ruby** priced by minute: $250 (50 min) / $395 (100) / $720 (200) / $1,725 (500); AI features
  reportedly included in every plan; sources conflict ($245 vs $250 for 50 min).
- **Thoughtly** entry plan "Flex" from **$500/mo**, 10 concurrent, voice + SMS + email + workflows
  on every tier; Scale and Enterprise quote-only. An older source cites $0.09/min, which conflicts.
- **Numa** publishes no pricing. Reported: 1,300+ dealerships US/Canada, $55M raised incl. Google,
  acquired Ficus April 2026; an **Appointment Agent where dealers pay only for appointments fully
  booked by AI** [News, digitaldealer.com, Jan 2025] — that outcome-based pricing idea is worth
  noting. Third-party estimate $200–$400/mo single-rooftop, $500–$1,500 at scale.
- **Sindarin** — no published price found. Unverified.

#### India — the real competitive floor for Atithi

**Sarvam AI** [Vendor, docs.sarvam.ai/voice-agents]
- **Pay as you go ₹3.50/min · Pro ₹3.25 · Growth ₹3.15 · Business ₹3.00 (coming soon) ·
  Enterprise custom** for committed volume of 2 lakh min/mo or more. Telephony billed separately.
- 11 Indian languages + English — Hindi, Tamil, **Telugu**, Bengali, Marathi, Gujarati, Kannada,
  Malayalam, Punjabi, Odia, Assamese — "including code-mixed speech, alphanumerics, and proper nouns".
- Own models: Saaras v4 (STT), `sarvam-105b-conversations`, Bulbul v3/v4 (TTS).
- **"Data residency in India, including PII."**
- Handles interruptions, **mid-call language switching**, voicemail detection, hold, long silences.
- Simulated test calls against scripted scenarios; outbound campaigns; call logs, analytics, custom
  boards; MCP server for Claude/Cursor/VS Code; phone, WhatsApp, web, API.
- No latency figures published.

**[Inference]** ₹3.50/min at roughly ₹88/USD ≈ **$0.040/min** — below every US platform's all-in rate
and below Vapi's hosting fee alone. **Sarvam, not Vapi or Retell, is Atithi's pricing anchor.**

**[Listing], unverified:** Bolna ₹0.75–₹1.40/min; Bolti flat ₹6/min with a free 50-minute trial.

### Cheapest → premium (verified published rates only)

| Rank | Platform | Rate | Note |
|---|---|---|---|
| 1 | **Google Gemini Live free tier** | **$0.00** | Free of charge, in and out. Rate-limited; not an SLA. [Vendor] |
| 2 | Sarvam (India) | ~$0.040/min | ₹3.50 PAYG, all-in orchestration + Indian-language models. [Vendor] |
| 3 | LiveKit (calculator default) | $0.0479/min | Plus $0/$50/$500 platform fee. [Vendor] |
| 4 | Deepgram BYO LLM+TTS | $0.050/min ($0.041 Growth) | [Vendor] |
| 4= | OpenAI `gpt-live-1` | $0.050/min | Backend model + tools extra. [Vendor] |
| 4= | Vapi hosting | $0.050/min | Providers and telephony on top → $0.082–$0.129 all-in. [Vendor] |
| 7 | Cartesia Managed Agents | $0.060/min | +$0.014/min telephony. [Vendor] |
| 8 | Retell floor | $0.070/min | Realistic config $0.11/min. [Vendor] |
| 9 | Deepgram Standard | $0.075/min | [Vendor] |
| 10 | ElevenLabs | $0.080/min | LLM at cost on top; burst $0.160. [Vendor] |
| 11 | Bland | $0.120–$0.140/min | Bundled; telephony separate. [Vendor] |
| — | **Premium / enterprise-only** | | Synthflow **$30,000/yr minimum**; Vapi Pro $999/mo min + $2,000/mo HIPAA; ElevenLabs Business $990/mo; Thoughtly $500/mo [Listing]; Slang.ai $399–$599/location [Vendor]. |

**Free tiers that matter:** Gemini Live (free of charge) · Deepgram $200 credit · LiveKit Build (1,000
agent-session min + a free number) · ElevenLabs Free (15 min) · Retell $10 credit + 20 free concurrent ·
Vapi $5 credit · Bland Start (no card required) · Cartesia Free (20K credits + 1 number). [All Vendor]

### Unit-economics read for Atithi

**[Inference]** On Gemini 3.8 Live paid rates ($0.005/min audio in, $0.018/min audio out), a one-minute
call where each side speaks ~30 s costs roughly **$0.0115/min of model**, plus Twilio India telephony.
That is genuinely below every managed platform's floor, and roughly a quarter of Sarvam's rate. The
free tier makes pilots cost ~nothing. **This is a real, defensible cost advantage — more defensible
than the proof check** (see §4). But it is a *supplier* advantage, not a product moat: any competitor
can adopt Gemini Live. Price on the value of a captured booking, not on cost-plus.

---

## 3. LATENCY — is sub-second normal or exceptional?

**Short answer: sub-second end-to-end is exceptional and, on independently measured full-turn
numbers, essentially unachieved. Atithi's 0.1–0.5 s is almost certainly measuring a narrower
segment than what a caller experiences, and should not go into marketing until re-measured.**

### What vendors advertise

- **Vapi** [Vendor, vapi.ai/blog/speech-latency]: "Vapi.ai achieves industry-leading sub-500ms
  response times." It defines the metric as "End-to-end delay = response_play_start – utterance_start"
  and sets a **target** of "p50 < 500 ms, p95 < 800 ms". The post publishes **no measured p50/p95,
  no sample sizes, no test conditions** — it is a target, not a result.
- **Retell**: ~600 ms "industry-leading" turn time [Listing citing Retell docs]. Retell's own pricing
  page advertises **no latency figure at all** [Vendor].
- **Deepgram** [Vendor]: no numeric latency for Voice Agent API. Qualitative only — "without delays",
  and Flux STT described as "ultra-low latency" with no figure.
- **Cartesia, LiveKit, ElevenLabs, Synthflow, Sarvam** [Vendor pricing pages]: **no advertised
  latency numbers.**

**Finding: most serious platforms have stopped publishing latency numbers.** Only Vapi makes a
headline claim, and it labels it a target. This is a meaningful signal — the market learned that
latency claims get benchmarked and embarrassed.

### What independent benchmarks measured

Aggregated by Telnyx [Listing — Telnyx is a competitor aggregating four third-party tests; the
underlying tests are independent, the selection and framing are not]:

**Openbenchmarks** — caller-side time to first audio byte, calls through 2026-08-01, median / p95:
Telnyx 1,296 / 1,856 ms · ElevenLabs 1,424 / 1,768 · Bland 1,520 / 2,248 · Vapi 1,558 / 2,008 ·
Retell 1,740 / 2,259.

**Cekura v1** — agent-layer mean response time, last updated 2026-09-29, 8 configurations, 246 calls each:
ElevenLabs 1.27 s · GPT Realtime 1.58 s · Telnyx 1.82 s · Pipecat 1.97 s · Retell 2.21 s ·
LiveKit 2.59 s · **Gemini Live 3.05 s** · Vapi 3.08 s. (A separate Cekura board of nine live
production agents reported medians of 2.38–3.76 s. 41 of 246 Vapi test calls failed to connect.)

**Tested Media** — voice-to-voice, 500 production calls per platform, March 2026, median / p95:
Retell 680 / 920 ms · Vapi 720 / 1,050 ms · Bland 850 / 1,180 ms. (Detection method undisclosed.)

**TECHSY** — carrier-leg round-trip only, 120 outbound calls per carrier, 2026-06-06 to 06-08, p50 / p95:
Telnyx 71 / 118 ms (setup 380 ms) · Twilio 89 / 161 ms (setup 470 ms) · Vonage 94 / 152 ms (510 ms).

**Component-level** — Coval independent TTS benchmark, data captured 2026-05-04, P50 time to first
audio: Gradium 155 ms · Cartesia Sonic-3 188 ms · ElevenLabs Turbo v2.5 264 ms [Listing].

### What "good" is, per the most neutral source

**Coval's latency guide** [Vendor, coval.ai] defines turn latency as "the delay between when a user
finishes speaking and when the AI agent begins responding", measured per turn, and publishes targets:
- General conversation: **natural < 1 s · acceptable < 2 s · poor > 3 s**
- Real-time conversational AI: target **< 1 s**, acceptable < 1.5 s
- Consumer customer service: target **p95 < 2 s**, acceptable < 3 s
- Critical (emergency): target < 1.5 s, acceptable < 2 s

Typical component ranges it gives: streaming STT 200–500 ms after speech ends · fast LLM 400–800 ms ·
fast TTS 200–400 ms to first audio. Architecture totals: **cascaded 1,400–2,600 ms ·
speech-to-speech 900–2,000 ms · hybrid 800–1,500 ms simple / 1,500–3,000 ms complex.**

### Verdict for Atithi — read this carefully

1. **Sub-second is exceptional.** Only one of four independent benchmarks (Tested Media) put *any*
   platform under 1 s, at 680–850 ms median. Openbenchmarks and Cekura put everyone at 1.3–3.1 s.
2. **Outpero's 0.8–1.3 s claim is unremarkable — it sits in the normal-to-good band.** It is not a
   weak claim and should not be dismissed; it is roughly where the best independently measured
   platforms actually land. It is also a *credible-sounding* range, which matters in a sales
   conversation.
3. **Atithi's 0.1–0.5 s is below every independently measured platform number in this market, on any
   metric except the carrier leg alone.** The most direct check: **Cekura measured Gemini Live — the
   same model family Atithi runs — at 3.05 s mean at the agent layer.** A 0.1–0.5 s figure on the same
   underlying model is a ~6–30x discrepancy. The overwhelmingly likely explanation is that Atithi is
   measuring **model time-to-first-audio-token off the Live API socket**, not utterance-end to
   first-audio-at-the-caller's-ear. The caller's number must additionally include: Twilio PSTN carrier
   leg (~71–94 ms p50 one-way per TECHSY), mulaw 8k ↔ PCM 16k/24k conversion, websocket bridge hops,
   jitter buffer, and server-side VAD endpointing delay — and endpointing alone typically dominates
   (Vapi's default `onNoPunctuationSeconds` of 1.5 s is cited as a major latency sink [Listing]).
4. **Action:** before any demo or marketing use, re-measure as **utterance-end → first audio audible
   at the caller's handset, p50 and p95, over real PSTN calls, n ≥ 100.** Publish p50 *and* p95.
   If the honest number lands at 0.6–0.9 s p50, that is still best-in-class against Openbenchmarks
   and Cekura and is a *defensible* claim. A 0.1 s claim will be disbelieved by any technical buyer
   and will cost more credibility than it buys. Note also that Vapi — the one vendor making a
   sub-500 ms claim — was measured at 1,558 ms and 3.08 s by two independent benchmarks. That is the
   reputational outcome to avoid.
5. **Latency and the proof check are in direct tension.** See §4 — every pre-speech verification
   mechanism in the market costs 200 ms to 3 s.

---

## 4. TRUST / VERIFICATION — how defensible is the "proof check"?

This was the most important question, so I searched it hardest: vendor guardrail docs, QA-vendor
guides, voice-agent-architecture posts, and academic results. **Conclusion up front:**

> **No vendor I could find sells "the agent cannot lie."** The specific mechanism Atithi describes —
> comparing the agent's spoken action-claim ("you're booked") against the actual persisted booking
> record *before the caller hears it* — **is not shipped as a named product feature by any platform
> or receptionist product I could verify.** It is, however, a **well-known, publicly documented
> failure mode with a publicly documented remedy**, and three adjacent things *are* sold: policy
> guardrails that block output pre-speech, deterministic action gating, and post-call hallucination
> QA. So the gap is real but narrow, the idea is not secret, and the defensibility is **in execution
> and productization, not in the concept.**

### Who sells what — named, verified

**1. ElevenLabs — "Guardrails"** [Vendor, elevenlabs.io/docs/agents-platform/best-practices/guardrails]
The most concrete shipped pre-speech blocking mechanism in the market. Four guardrail types:
- **Focus** — "reinforces your agent's system prompt", keeps it on-topic. Explicitly *reinforces
  instructions rather than checking facts.*
- **Manipulation** — prompt injection and instruction-override detection on **user input**; can end
  conversations. Latency impact: "No effect."
- **Content** — "Flags and prevents inappropriate content in agent responses" (politically sensitive,
  sexually explicit, violent).
- **Custom** — "LLM-based rules that let you define your own blocking criteria using natural language
  prompts."

It "independently evaluates every agent reply in real time against your configured policies".
Two modes: **streaming** — "the agent response may begin before the guardrail triggers" (for voice, a
short portion of audio may play before a block ends the call), adds no latency; **blocking** — "the
agent only responds after the guardrails have been validated", and **"typically adds 200–500 ms of
extra latency."** Exit strategies: `end_call` in either mode; `retry` (up to 3 attempts) **blocking only**.

**Critically: the page does not claim guardrails verify factual claims or tool results against a
source of truth. Custom guardrails are model-based checks against a natural-language prompt. No
comparison against external data or tool outputs is described.** So ElevenLabs ships the *delivery
mechanism* (pre-speech blocking with retry) but not the *verification* Atithi describes.

**2. Retell AI — "Safety Guardrails" +$0.005/min and "AI Quality Assurance" $0.10/min after 100 free
minutes** [Vendor, retellai.com/pricing — these are published line items]. **What they actually check
is undocumented on any page I could reach** (`docs.retellai.com/features/guardrails` returns 404). A
Retell community forum post [Listing, unofficial] describes configuring prohibited topics, response
length limits, and content filtering — i.e. policy, not factual verification. **Whether either
add-on verifies tool results: unverified.** Worth noting commercially: **Retell has proven buyers
will pay a per-minute premium for trust features.**

**3. Replicant — "deterministic checkpoints"** [Vendor blog, replicant.com]. Conceptually the closest
published approach, and the one Atithi should study:
- Code, not the LLM, enforces rules *before* a workflow starts. An ineligible order "never enters the
  workflow", and the LLM is told it "cannot" act. The post's framing: this **"turns our LLM's
  'should not' into a 'cannot'."**
- Required actions are code-triggered, so "compliance becomes the responsibility of code and not of
  prompt engineering."
- Sensitive values are never shown to the LLM: **"You can't leak what you have never seen."**
- Plus a **separate guardrail LLM** checking the talker LLM's output for hallucinations before it
  reaches the caller, with re-prompting on detection. Figure caption: guardrails catch "hallucinations
  or unsafe responses before they reach the caller."
- **Limits:** the post never specifies what facts the guardrail LLM checks against beyond "known facts
  and capabilities", makes **no quantitative claims** ("exponentially reduce the likelihood" is the
  actual language), and the guardrail layer is itself a probabilistic model. Only the deterministic
  checks are described as guaranteeing anything.

**4. Uniphore / Jacada — multi-layer guardrails** [Vendor engineering blog]. The most complete
published architecture, and the source of the hard latency numbers Atithi needs:
- Three checkpoints: **user input** (content safety, topic adherence, jailbreak), **tool calls**, and
  **agent output**.
- **Tool-call validation in four levels: tool existence · parameter names · workflow state (via a DAG
  of the conversation flow) · parameter values**, with semantic value checks applied selectively to
  high-stakes fields (account IDs, financial amounts, medical codes). Failed checks re-prompt the LLM;
  repeated failures escalate to a human.
- **Output: factuality checks compare RAG answers against retrieved chunks**, with retries and human
  escalation.
- Named components: `InputSafetyGuardrail` and `InputJailbreakGuardrail` as REST classifier services
  called concurrently with the LLM; NeMo Guardrails (NVIDIA `nemoguard-jailbreak-detect`) as default
  engine, mmBERT for multilingual.
- **Latency budget, measured:** deterministic tool checks (existence, param names, syntax)
  "in under a millisecond" · input classifiers (67M DistilBERT / 307M mmBERT) **40–50 ms** ·
  semantic parameter validation via LLM "hundreds of milliseconds" · large (8B+) LLM safety checkers
  **~600 ms or more** · **output buffering "adds 1–3 seconds of latency before the user hears
  anything."**
- Their own verdict: buffering "guarantees that the guardrail sees the full output" but streaming
  output is **"the hardest problem"** and **"an open problem."**

**5. Dilr Voice** [Vendor blog] — the closest *marketing language* to Atithi's: "the response is
validated against an approved knowledge base or **system of record** before it is spoken", and "an
answer that cannot be grounded is not delivered as fact." **But:** no implementation detail, no latency
figures, the post mixes present-tense product description with 2026 best-practice advice so shipped
status is unconfirmed, and **it never mentions tool or function-call results at all** — only a
knowledge base or system of record for *answers*, not for *actions taken*. **Unverified as a product.**

**6. Hamming — post-call hallucination detection and tool-call testing** [Vendor guides]. Hamming does
**not** gate speech; it detects after the fact. But its guides **name Atithi's exact failure mode in
print**, which is the single most important competitive fact here:

> "The agent can say 'your appointment is booked' while the webhook payload is missing a timezone,
> the client tool was never registered, or the downstream system wrote the record under the wrong
> customer."

> "A successful tool response is not the same as a correct calendar event, CRM case, refund request,
> or account update."

Its review rubric fails a run when a "Spoken confirmation disagrees with the tool result" or when a
"Transcript passes but no durable evidence exists". Its launch checklist requires "Tool failures
produce safe caller-facing responses instead of false confirmations", and its FAQ lists confirming
"success after a failed tool result" as a **release blocker**. Its hallucination guide prescribes
"Log tool input, output, and spoken claim together", emits a `voice.hallucination.detected` event
with claim, source, `supportDecision` (e.g. "contradicted"), severity, detector method and confidence,
routes by severity tier, converts confirmed failures into regression tests, and warns "Do not report
hallucination rate without detection coverage." Its sample event includes `"heardByCaller": true` —
confirming detection runs **after** the caller heard it. Compliance: SOC 2 Type II and HIPAA [Listing].

**7. The surrounding QA/eval market** [Listing]: **Coval** (simulation-led, runs a public open STT
benchmark, CI/CD regression), **Cekura** (ex-Vocera; pre-production testing *and* production
monitoring; Developer tier reportedly $30/mo; claimed 2,000+ concurrency), plus Bluejay, Maxim AI,
Roark, Future AGI. Vapi and Retell both ship their own simulation/eval tooling [Vendor].

**8. Also documented, by non-vendors, as the exact recipe** [Listing]: gate the word "confirmed"
behind a durable record — "A caller hears 'confirmed' only after the calendar adapter returns a
durable event identifier and the system records the result"; "Post-call sync verification — confirms
the event exists in the calendar after creation; retries if the API call timed out"; "pass tool
results to the model as structured data so values are not paraphrased"; treat any write action as
needing an explicit confirmation turn; and gate irreversible tool calls on explicit caller
confirmation. One source notes the practical constraint: "once speech starts, it cannot be retracted",
and that a fast embedding-similarity check fits a real-time turn while an LLM grader does not.

### Defensibility assessment — honest

**What is genuinely in Atithi's favour**
- **Nobody has productized it under a name a buyer can repeat.** The mechanism exists as blog advice
  and QA tooling, not as a shipped, demo-able, customer-visible platform feature. Naming it, showing
  it on screen, and putting the record ID in the dashboard is real product work that nobody in the
  receptionist tier has done.
- **It is *action* verification, not *answer* grounding.** Everything else on the market grounds
  answers against a knowledge base (ElevenLabs Custom guardrails, Uniphore's RAG-chunk factuality,
  Dilr's "system of record"). Verifying that a **write actually persisted** before claiming it is a
  different and narrower check — and it is the one that matters for a booking business.
- **It is cheap and fast when scoped to actions.** Uniphore's own numbers say deterministic checks
  run "in under a millisecond" and only *semantic/LLM* checks cost hundreds of ms. Verifying "did
  `book_appointment` return a booking ID that exists on disk?" is a deterministic check, not an LLM
  call. Atithi's version should cost ~0 ms, not 200–500 ms.
- **Retell has proved buyers pay for trust line-items** (+$0.005/min guardrails, $0.10/min QA) [Vendor].
- **It is the right *sales* story for Indian clinics**, where one false "you're booked" burns the
  client's reputation with their own patient — exactly the reliability priority in Atithi's charter.

**What is not defensible**
- **It is not a technology moat.** It is a design pattern, publicly and freely documented by Hamming,
  Deskcaller, Evalgent, Uniphore and Replicant. Any competent team can implement it in a sprint.
  Patent/secrecy is not available.
- **"The agent cannot lie" is an absolute claim, and the market already treats absolutes as a red
  flag.** One 2026 vendor ranking states plainly that no platform is immune to hallucination, and
  that a vendor promising "zero hallucinations" has told you something about its honesty rather than
  its architecture [Listing]. An Arcade webinar makes the same point: prompt-based guardrails are
  "useful signals, but never guarantees" [Listing]. **Making the absolute claim will cost credibility
  with exactly the technical buyers who could validate it.**
- **It is narrow.** It covers confirmations of actions the agent took. It does **not** cover wrong
  prices, invented policies, wrong addresses, misheard phone numbers, or hallucinated doctor
  availability — all of which embarrass a clinic just as badly. A buyer who hears "it cannot lie"
  and then catches a wrong price has caught Atithi overclaiming.
- **It can be trivially matched as a bullet point.** Any competitor can add "verified bookings" to a
  pricing page next quarter.
- **It collides with the latency claim.** Every pre-speech verification mechanism on the market costs
  latency: ElevenLabs blocking 200–500 ms; Uniphore output buffering 1–3 s; LLM-based checkers 600 ms+.
  If Atithi's proof check runs pre-speech on a speech-to-speech model — where audio starts streaming
  immediately and there is no text buffer to hold — it is architecturally the *hardest* place to do
  this. Uniphore calls streaming output verification "an open problem." **Atithi cannot claim both
  0.1–0.5 s and pre-speech verification without explaining how.** That is the first question a
  technical buyer or investor will ask.

**Recommended positioning** [Inference]
1. Drop "the agent cannot lie." Use a mechanical, falsifiable claim: **"A confirmation is only spoken
   after the booking exists, with an ID. If the write fails, the caller is told the truth."** That is
   verifiable, demo-able, and survives scrutiny.
2. **Demo the failure path, not the happy path.** Kill the booking backend mid-call and let the
   prospect hear the agent say "I couldn't complete that — let me take your number." No competitor
   demos this. It is far more persuasive than any latency figure, and it is the one thing a clinic
   owner will instantly understand.
3. **Ship the receipt.** Every call record shows the spoken claim next to the booking ID it was gated
   on. Hamming's own schema is a free blueprint: claim · source · `supportDecision` · severity ·
   `heardByCaller`. Make it visible in the owner's dashboard. The *audit trail* is harder to copy
   than the check.
4. **Widen it over time** to prices, timings and policies read from the client YAML — that is where
   it becomes a system rather than a feature, and where it stops being a one-sprint copy.
5. **Treat it as a wedge, not a moat.** Expect it to be copied within two quarters of getting
   traction. Compound it with the things that are harder to copy: Indian-language quality,
   India data residency, Gemini-Live cost structure, and distribution into Indian SMBs.

---

## 5. ARCHITECTURE — speech-to-speech vs cascaded

**The industry has not picked one. Cascaded (STT→LLM→TTS) remains the production default for
tool-heavy and regulated work; speech-to-speech is now offered as a first-class *option* on nearly
every major platform, and is priced as a premium.**

### Verified evidence that both are mainstream

- **Retell publishes a dedicated "Speech-to-speech LLMs" price line** alongside its cascaded LLM list:
  GPT Realtime mini $0.07/min · GPT Realtime 1.5 and GPT Realtime $0.345/min · GPT Realtime 2.1 and
  GPT Realtime 2 $0.38/min [Vendor]. **[Inference]** Against its own cascaded estimator example of
  $0.11/min, full speech-to-speech costs roughly **3.5x** — and its $0.055/min voice-infrastructure
  fee still applies. S2S is sold as the expensive option.
- **Vapi ships a dedicated OpenAI Realtime integration** and describes it as a native model taking
  audio in and returning audio out, unlike its usual transcriber→model→voice chain. Vapi's
  orchestration layer (endpointing, interruption models) is retained. **Notably, the docs state
  Knowledge Bases are not supported with the Realtime API**, and realtime voices are limited to
  OpenAI's set [Vendor].
- **OpenAI** sells both the raw realtime models and a hosted session product, `gpt-live-1` at
  $0.05/min billed per second [Vendor].
- **Google** ships native-audio Live models with a **free tier** and per-minute audio equivalents
  ($0.005/min in, $0.018/min out on 3.8 Live), plus "Grounding with Google Search: Supported" [Vendor].
- **Microsoft** structures Voice Live pricing by the LLM the developer selects, with a "Voice Live
  Lite" tier and a "Voice Live BYO" option — i.e. explicitly supports swapping the brain, which is a
  cascaded-style affordance on a realtime product [Vendor; dollar figures unverified].
- **Deepgram, LiveKit and Cartesia** price STT, LLM and TTS as separate metered lines — pure cascaded
  economics, with BYO-component discounts (Deepgram BYO LLM+TTS drops from $0.075 to $0.050/min) [Vendor].
- **Sarvam** runs its own cascaded stack end to end (Saaras v4 STT + `sarvam-105b-conversations` +
  Bulbul v3/v4 TTS) and still delivers interruption handling and mid-call language switching [Vendor].
  **This is the important counterexample for Atithi: you do not need native audio to get barge-in or
  language switching.**

### Stated tradeoffs [Listing — multiple 2026 analyses — plus Vendor docs where noted]

**Speech-to-speech wins:**
- **Latency.** Coval's ranges: cascaded 1,400–2,600 ms total vs S2S 900–2,000 ms vs hybrid
  800–1,500 ms (simple) [Vendor, coval.ai].
- **Paralinguistics.** Tone, hesitation, laughter and emphasis survive, where cascaded "gets flattened
  into plain text before the LLM sees it".
- Fewer moving parts, no transcription error cascade.

**Cascaded wins:**
- **Observability and audit.** Each stage produces traces and transcripts. S2S exposes little
  intermediate text, so teams add a parallel transcription layer. One analysis concludes "compliance
  needs and tool-use requirements decide the winner more often than raw speed does."
- **Component swappability.** The LLM stays replaceable; BYO discounts are real money (Deepgram,
  Retell, Vapi all price BYO lower) [Vendor].
- **Mature tool calling.** "Tool calling is mature in cascaded systems and newer, with edge cases, in
  S2S." Corroborated by Google's own developer forum: reports of function calling returning nothing
  with no error on 2.0 Live models, and WebSocket 1008/1011 disconnects and random closures after
  sending tool responses, late 2025 through March 2026. Google's responses point to newer native-audio
  models and say 3.x "fixed most bugs and errors" [Vendor forum + Vendor docs]. Google's 3.8 Live page
  lists function calling and async calls as supported, with **non-blocking now the default** and
  blocking available for backward compatibility [Vendor].
- **Knowledge base / RAG support.** Vapi's docs: Knowledge Bases are not supported with the Realtime
  API [Vendor]. This is the concrete cost of going native-audio on a major platform.
- **Cost.** 3.5x cheaper on Retell's own price list [Vendor + Inference].

**Middle ground:** hybrid designs (audio-aware LLM in, TTS out) are described as the emerging pattern
and post the best simple-query latency band in Coval's table.

### Implications for Atithi

1. **Being on native audio is a legitimate, current architectural choice** — Google, OpenAI, Microsoft
   and Retell all sell it. It is not a student shortcut.
2. **But it is the harder place to build the proof check**, for exactly the reason Uniphore calls
   streaming output verification "an open problem": there is no text buffer to hold while you verify.
   Atithi needs a clear answer to "where exactly does the check sit, and what does the caller hear
   while it runs?" The cheapest honest answer: the check is **deterministic and local** (does the
   booking row exist with an ID?), runs in ~0 ms, and gates the *tool result handed back to the model*
   rather than the audio — so the model is never in a position to claim success, because it never
   received a success. **That is the Replicant "should not → cannot" pattern, and it is both faster and
   more defensible than output buffering.** Worth checking whether `agent.py` already works this way;
   if so, say so precisely, because it is a stronger claim than a post-hoc check.
3. **Google's Live API is the free-tier cost advantage and the reliability risk at once.** The
   documented function-calling and WebSocket failures are directly load-bearing for a booking product.
   The CLAUDE.md principle of wrapping all provider code in `llm.py` is the right hedge — keep a
   cascaded fallback path (Sarvam proves cascaded can deliver barge-in and language switching for
   Indian languages at ~$0.04/min) so a Live API regression does not take the product down.
4. **The free tier is not an SLA.** No published rate limits or availability guarantee. Do not price a
   paid pilot against $0 model cost.

---

## Companies checked, and status

| Company | Status | Evidence |
|---|---|---|
| Vapi | Active, verified pricing + full docs index | [Vendor] |
| Retell AI | Active, most transparent pricing in market | [Vendor] |
| Bland AI | Active, verified tiers | [Vendor] |
| Synthflow | Active but **enterprise-only now — $30k/yr minimum**, no self-serve pricing | [Vendor] |
| ElevenLabs Agents ("ElevenAgents") | Active, verified pricing + Guardrails docs | [Vendor] |
| Deepgram Voice Agent API | Active, verified pricing | [Vendor] |
| LiveKit Agents | Active, verified pricing; Apache 2.0 self-hostable | [Vendor] / [Listing] |
| Cartesia | Active; voice agents are "Managed Agents", $0.06/min | [Vendor] |
| OpenAI | Realtime models + `gpt-live-1` $0.05/min | [Vendor] |
| Google Gemini Live | Native audio, **free tier**, paid per-minute equivalents published | [Vendor] |
| Microsoft Azure Voice Live | Active; **pricing figures unverified** (cached tables rendered "$-") | [Vendor, partial] |
| Goodcall | Active, verified pricing; per-unique-customer model | [Vendor] |
| Slang.ai | Active, verified $399/$599 per location; billing period not stated | [Vendor] |
| Sarvam AI (India) | Active, verified ₹3.00–3.50/min, 11 Indian languages, India data residency | [Vendor] |
| Rosie, Dialzara, Smith.ai, Ruby, Thoughtly, Numa, Sindarin | Active; **all pricing [Listing]/unverified** | [Listing] |
| **PlayAI / PlayHT** | **Likely defunct as a standalone platform.** Reported acquired by Meta July 2025, team absorbed, play.ht / play.ai wound down. Conflicting 2026 tier claims exist. **Unverified — do not benchmark against it.** | [Listing] |
| **Air.ai** | **Treat as defunct.** Reported FTC suit Aug 2025; March 2026 settlement with an $18M judgment and a permanent ban on the founders marketing business opportunities; a review site calls the platform inactive with no roadmap or support channel. **No FTC primary source or company statement found — unverified, but strongly corroborated. Do not use as a competitive benchmark.** | [Listing] |

**Also surfaced, not on the original list, worth tracking:** Telnyx (carrier + voice agent platform,
fastest carrier leg measured), Pipecat (open-source orchestration, 1.97 s Cekura), Gradium (fastest
TTS TTFA measured, 155 ms P50), Replicant (the deterministic-guardrail story), Uniphore/Jacada,
Dilr Voice, Lorikeet, Hamming, Coval, Cekura, Bluejay, Maxim AI, Roark, Future AGI, Bolna, Bolti,
Ringg, Toma, Loman (restaurant), Hostie, Maple Voice.

## What I could not verify

- **Azure Voice Live API dollar figures** — structure confirmed, every price rendered as "$-".
- **What Retell's "Safety Guardrails" (+$0.005/min) and "AI Quality Assurance" ($0.10/min) actually
  check** — the docs URL 404s; only an unofficial community post describes them.
- **Dilr Voice's "validated against a system of record before it is spoken"** as a shipped feature
  rather than a recommendation.
- **PlayAI's and Air.ai's current status** from primary sources (no company statement, no FTC release).
- **Slang.ai's billing period and included call volume** — not stated on its own pricing page.
- Pricing for Rosie, Dialzara, Smith.ai, Ruby, Thoughtly, Numa, Sindarin, Bolna — third-party only.
- **Cekura's and Openbenchmarks' raw leaderboards** — read only via Telnyx's aggregation (a competitor).
- Any independent benchmark of **tool-calling accuracy** on native-audio models. None found.
