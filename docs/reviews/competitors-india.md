# Atithi — Indian Competitor Landscape: AI Voice Agents / AI Receptionists for SMBs

**All web research conducted 2026-10-25.** Prices and features change fast in this category — re-check before any pitch deck or pricing decision.

## Evidence labels used throughout

| Label | Meaning | Strength |
|---|---|---|
| **[Vendor]** | The company's own website / marketing | Weak. Self-interested, often inconsistent page-to-page |
| **[Listing]** | Third-party directory or comparison page (often itself a vendor's SEO page) | Weak-to-medium. Note who published it |
| **[News]** | Independent press / trade publication | Medium-to-strong |
| **[Inference]** | My own reasoning from the above | Explicitly my judgement, not a fact |

A recurring problem: **most "Top 10 AI Voice Agents in India" pages are published by vendors who rank themselves #1.** I have labelled these as [Listing] and named the publisher every time.

---

## Part 1 — Corrections and failures to verify

Before the profiles, the hygiene items. Four of the names in the brief did not survive verification.

### Could NOT verify — do not cite these

| Name | What I actually found | Status |
|---|---|---|
| **VaaniYantra** | The only page matching this exact name is served from a raw IP-based host (`34.138.86.231.sslip.io`) with no real domain, claiming an AI phone agent for Indian businesses, 10 Indian languages, Gemini Live backend, $49/mo and $199/mo plans [Vendor]. No company registration, no press, no proper domain. | **Unverified.** Possibly a demo deployment or abandoned project. Do not treat as a competitor. |
| **CareVoice AI** | A hackathon submission on lablab.ai (AssemblyAI Voice Agent Hackathon) — a dental-clinic voice receptionist wired to n8n + Google Calendar/Sheets. Listed ~24 days before checking. [Listing] | **Not a company.** A student/hackathon project. Notably, it is architecturally similar to Atithi. |
| **Saral AI** | Zero relevant results. | **Unverified / does not exist** in this category under that name. |
| **MantraAssist** | Built In lists it as **United States**, 205 employees, founded 2025. Latka lists founded 2013, ~$1K revenue. One directory says bootstrapped; the *same site's* profile says "$15M from Impanix Capital." [Listing, contradictory] | **Not an Indian competitor.** The $15M figure is unverified and self-contradicted. Ignore. |

### Name collisions worth knowing

- **"Vaani"** is heavily overloaded. There are at least three distinct entities: **Vaani AI Research** (Bengaluru, $400K pre-seed led by Venture Catalysts, developer APIs/SDKs for multilingual voice agents [News]); **Vaani Labs** (Maharashtra, voice agents over phone/web/WhatsApp, claims 40+ languages [Listing]); and **VaniAgent** (Solvea Technologies Pvt. Ltd., a real direct competitor — profiled below). Do not conflate them.
- **AnveVoice** (`anvevoice.app`, Anveshana Futurecorp Pvt Ltd) is a **website voice widget, not a phone line.** Its own copy describes navigating and filling forms on a site. Pricing: Free $0 / Growth $39 / Scale $129 per month [Vendor]. It ranks heavily for "AI receptionist" SEO terms but is not an inbound telephony competitor. **Adjacent, not direct.**

### Correction to the brief's Outpero profile

I verified outpero.com directly [Vendor, 2026-10-25]. The brief's numbers hold up, with two material corrections:

- **Outpero is not outbound-only.** "Inbound" is one of its three named products ("answers your number", 24/7). The brief describes it as "OUTBOUND speed-to-lead," which understates the overlap with Atithi.
- **Location is not stated on the site.** The only city mentioned is Noida, in a demo. The "Hyderabad" attribution in the brief is **unverified** from the website.
- Confirmed pricing: Standard **₹5/min**, Premium **₹6.8/min**, Custom **as low as ₹3.5/min** at high volume, business number **₹649/month**, 50 free credits, no setup fee, 1 credit = ₹1, credits never expire, GST excluded.
- Confirmed **7 languages**: Hindi, Telugu, Tamil, Kannada, Malayalam, Marathi, English.
- New detail: Outpero is **supported by the Sarvam AI and Cartesia startup programmes** [Vendor] — i.e. it is a thin orchestration layer on Indian/US model infrastructure, not a model builder. Claims "5,000+ businesses" [Vendor, unverified].
- Features: mid-call WhatsApp send, Google Calendar booking, CRM fetch, human transfer, caller memory, auto-retry, **DLT-registered numbers and built-in consent checks**, Meta Lead Ads / Google Sheets / HubSpot / Zoho / webhooks.
- **No hallucination-safety or booking-verification claim anywhere on the site.**

---

## Part 2 — Direct competitor profiles (inbound AI receptionist, Indian SMB)

These are the companies competing for the same customer and the same budget line as Atithi.

### ConnectAI (`connectai.care`) — the closest thing to a direct rival for clinics

- **What they sell** [Vendor]: A full clinic software suite, not just a receptionist. Named agents: **Dhanwantri** (WhatsApp AI receptionist — books, takes Razorpay payment, sends reminders, requests reviews), **Disha** (practice manager the doctor messages for schedules/revenue), **Rohan** (re-engages lapsed patients), **Kavya** (pre-visit intake, post-visit instructions, Day-3 check-ins with escalation on high pain), plus a separate **AI Voice Receptionist** that answers and places calls.
- **Target**: Doctors and clinics only, across ~20 specialties (dental, derm, gynae, GP, ortho, paeds, ENT, cardio, physio, psych, fertility, Ayurveda/Homeopathy). Also hospitals, pharmacies, labs.
- **Languages** [Vendor]: Demo offers English, Hindi, Bengali, Tamil, Telugu, Marathi, Kannada, Gujarati, Malayalam, Punjabi, Odia (11). The page does **not** confirm the agents operate in all of these — only the demo picker does. Worth probing.
- **Pricing (public, specific — rare in this market)** [Vendor]:
  - AI Voice Receptionist: **₹800/month standalone**, or **₹499/month** as a Suite add-on, **plus ₹4/min** (8 credits)
  - AI Clinic Management Software: **₹500/clinic/month** + ₹100 per extra doctor (base = 1+1+1 seats)
  - AI Clinic Automation Suite: **₹2,499/month** all-in-one
  - GMB Profile Optimization: **₹1,999 one-time**
  - Self-serve entry from **₹1,499**
- **Inbound/outbound**: Both. Inbound via WhatsApp + phone; outbound reminders, follow-ups, re-engagement, review requests.
- **Notable**: WhatsApp-first rather than phone-first. Heavy **Google Business Profile / GMB / local SEO** bundling — they sell *patient acquisition*, not just call answering. `aarogya.care` + GMB Reserve integration. Razorpay payments in-flow. Free lead-gen tools (GMB audit, missed-patient calculator).
- **Size/funding**: Not stated. **Client counters on the site render as placeholders ("0+ clinics")** — treat all traction claims as unverified.
- **Verification/hallucination claims**: **None.**
- **[Inference] Why this one matters most**: ConnectAI has published the clearest clinic-specific price anchor in the market (₹800/mo + ₹4/min) and bundles the thing clinics actually want — more patients via Google — around the receptionist. Atithi will be compared to this bundle, not to a standalone receptionist.

### Pluxo (`pluxo.ai`) — Clevora AI Private Limited, Bengaluru

- **What they sell** [Vendor]: Voice AI for Indian healthcare. AI receptionist answering phone *and* WhatsApp, booking into real doctor slots, collecting payment via **UPI link**.
- **Target**: Clinics (dental, eye, heart, home care), hospitals, labs/diagnostics, pharmacies, drug helplines, health programmes, insurers.
- **Languages** [Vendor]: **11** — Bengali, English, Gujarati, Hindi, Kannada, Malayalam, Marathi, Odia, Punjabi, Tamil, Telugu. Switches to match caller.
- **Pricing**: Not on the homepage; separate /pricing page. Free clinic preview + free missed-call/front-desk calculator.
- **Inbound/outbound**: Both. Inbound 24/7 phone + WhatsApp; outbound callback on ad-form leads "within minutes", follow-ups, reminders.
- **Notable**: Integrations with **HIMS/EMR/CRM where API access exists**, Google Calendar, WhatsApp Business, Google Business Profile. Drafts review replies for owner approval. Hands off to staff on WhatsApp when stuck **and logs the unanswered question so the owner answers it once** — a nice knowledge-capture loop. Dashboard with transcripts, bookings, missed-call tracking. Also sells website + Google profile help ("Get Found").
- **Size/funding**: "Made in Bengaluru", Clevora AI Private Limited. No founders or funding named.
- **Verification/hallucination claims** [Vendor]: The **closest any Indian vendor gets**, but still weak: bookings sync to connected calendars and blocked slots stay unavailable, which they say **prevents double-booking**; and the AI "says so rather than guessing" when it lacks an answer, handing off to the team. **This is calendar-state hygiene plus a refusal instruction — not verification of a spoken claim against the booking record.**
- **[Inference]** Pluxo is the most feature-complete direct competitor I found: same vertical, same languages including Telugu, same UPI/WhatsApp expectations, and a real Pvt Ltd behind it. Atithi should assume Pluxo is the benchmark demo a clinic has already seen.

### VaniAgent (`vaniagent.com`) — Solvea Technologies Pvt. Ltd.

- **What they sell** [Vendor]: "Human-like AI voice calls for Indian businesses." AI receptionist as the lead use case: answers calls, books/requests appointments, answers FAQs, recovers missed calls, hands off to staff.
- **Target** [Vendor]: **Clinics and diagnostic centers, salons and wellness centers, consultants and local professionals, coaching and education centers, real estate and local services.** This is *almost exactly* Atithi's stated vertical list.
- **Languages**: Hindi, English, Hinglish confirmed on the page. A sibling article references Tamil and Bengali but the page does not confirm them. **Telugu not confirmed.**
- **Pricing**: Links to a pricing page; **no figures on the pages I read.**
- **Inbound/outbound**: Both; inbound-led (after-hours, overflow), outbound for missed-call callbacks.
- **Size/funding**: Indian (+91 contact, Pvt Ltd in footer). No HQ, headcount, or founding date stated.
- **Verification/hallucination claims**: None as product features. **Notably**, their own blog states as *general best practice* that you should confirm only system-verified actions, escalate sensitive calls, and keep FAQs approved — i.e. **they are publishing the idea without claiming to implement it.**
- **[Inference]** Vertical overlap with Atithi is the highest of any vendor found. Weakest on verified language depth. The fact that they blog the proof-check principle but don't productize it is a direct opening for Atithi.

### CallMissed (`callmissed.com`) — Pune, founded 2026 (per site structured data)

- **What they sell** [Vendor]: AI agent platform **+ CRM** for Indian businesses. Voice, WhatsApp, SMS and email agents that answer/book/follow up, all writing to **one customer record**. Also a support desk, "Social Studio" content tool, and developer APIs (LLM, STT, TTS, image gen, retrieval, web search).
- **Target** [Vendor]: Indian SMBs losing customers to unanswered phones; after-hours callers. Named verticals: **clinics and healthcare**, retail/D2C, transport and logistics, CA and tax firms, hospitality and travel ("all 10 industries" linked).
- **Languages** [Vendor]: **22 scheduled Indian languages** — the broadest Indian-language claim among the self-serve players — including Hindi, Bengali, Marathi, Tamil, Telugu, Urdu, Malayalam, Sanskrit, Manipuri. Claims mid-conversation language switching.
- **Pricing** [Vendor]: **Free tier of 1,000 non-expiring credits, no card.** Paid = per minute of connected call at the rate of the model you choose, plus per-model-call for WhatsApp/SMS/email. Site structured data exposes an INR range of **0–20,000 across four offers** but no tier names or per-tier prices are shown. Their own blog elsewhere quotes **Standard ₹4/min, Expressive ₹5/min, Best-latency ₹6/min, phone carriage billed separately** [Vendor].
- **Inbound/outbound**: **Inbound-led** — answering missed calls and after-hours contacts is the core pitch. Outbound for sales, collections/renewals, campaigns.
- **Notable**: Answers on first ring; detects language mid-sentence; handles interruption/turn-taking; books appointments and callbacks; processes refunds/order lookups; human transfer with context. **"Agents get specific tools rather than unlimited access"** — a real least-privilege design statement. WhatsApp Business (incl. WhatsApp calling), Instagram, Messenger, email, SMS, CRM, support desk, calendars, webhooks, OpenAI-compatible API.
- **Verification/hallucination claims** [Vendor]: One narrow grounding claim, **scoped only to WhatsApp**: *"WhatsApp replies are grounded in the documents you upload, not in whatever the model happens to believe."* There is an "Agent testing & quality" product listed with no detail. **No voice-side grounding claim, no accuracy guarantee, no booking-record verification.**
- **[Inference]** CallMissed is Atithi's most strategically dangerous direct competitor: same inbound/missed-call wedge, more languages, free tier, and a CRM to create switching costs. But the grounding claim stops at WhatsApp text — the voice path, which is where phantom bookings happen, is uncovered.

### Vyora AI (`vyora.ai`) — clearest self-serve price ladder

- **What they sell** [Vendor]: No-code AI voice agents for Indian SMBs; build an agent from a plain-text description; campaign builder for bulk outbound.
- **Pricing (fully public)** [Vendor]: **₹0 free plan (50 credits)**, plans from **₹799/month**, Business **₹3,449/month**. Credits don't expire; fixed monthly, "no surprise bills."
- **Languages** [Vendor]: **11** — English, Hindi, Tamil, Telugu, Kannada, Marathi, Bengali, Gujarati, Malayalam, Punjabi, Odia. (A rival listing says 8 — inconsistent.)
- **Inbound/outbound**: Both ("outbound and inbound AI calling").
- **Honest limits they publish**: **Voice-first only — no WhatsApp inbox, no chatbot.** Business plan can pass call results to an external WhatsApp provider. [Vendor]
- **Verification/hallucination claims**: None.
- **[Inference]** Note the structural mirror to Outpero: **free tier of exactly 50 credits**, then a flat monthly. The 50-free-credits-then-subscription pattern is becoming the standard Indian SMB acquisition funnel. Atithi should expect to match it.

### HuskyVoice AI (`huskyvoice.ai`)

- **What they sell** [Vendor]: Voice AI receptionist for clinics in India. Answers patient calls, identifies intent, books or routes appointments, escalates urgent calls, sends follow-ups, syncs summaries to clinic systems.
- **Languages** [Vendor]: English, Hindi, Hinglish + "configured Indian regional languages" (vague). A third-party listing claims 30+ including Telugu/Tamil/Kannada [Listing, MyOperator].
- **Pricing**: Not on their own page. MyOperator's comparison lists **₹39,990 base tier**, with the body text saying "/year" while the table gives no period — **ambiguous, verify directly** [Listing].
- **Inbound/outbound**: Primarily **inbound**.
- **Notable**: 24/7; booking or routing where scheduling is connected; human handoff and urgent escalation on approved rules; WhatsApp/SMS/email/callback/reminder follow-ups; structured call summaries; calendars, clinic CRMs, APIs, webhooks, Google Sheets; configurable retention + RBAC; **data residency in India, US or EU**. Phone numbers listed for India, US, UK, Australia.
- **Explicit scope limit** [Vendor]: *"supports administrative call workflows and does not provide medical advice"* — a good clinical-safety boundary statement Atithi should copy.
- **Verification/hallucination claims**: **None** — no booking verification, no double-booking prevention, no hallucination safety.

### Tabbly (`tabbly.io`) — Tabbly Labs

- **Pricing (public)** [Vendor]: **₹4.5/min pay-as-you-go**, no card; **₹3/min** for large committed Enterprise volumes; free trial with "$10 credits". Billed **by the second**.
- **Languages** [Vendor]: 50+, Indian ones listed first (Hindi, Tamil, Telugu, Kannada, Marathi, Bengali, Gujarati).
- **Inbound/outbound**: Both — explicitly sells an "AI receptionist" for inbound plus bulk outbound campaigns and an outbound cold caller.
- **Notable**: No-code builder; **unlimited concurrency**; recordings, transcription, AI scoring; n8n/Make/Zapier; custom API calls mid-conversation; **live scheduling with write-back to customer systems**; sub-300ms latency claim; India/USA data residency; model switching per conversation; self-learning from call history. Phone numbers in 50+ countries. Named customers include Swiggy, Vedantu, PlanetSpark, Cityflo, Alvarez & Marsal [Vendor, unverified].
- **Verification/hallucination claims**: **None.** Says agents can book slots and write back to systems, but describes no verification of the result.
- **[Inference]** Tabbly's ₹3/min at volume is the aggressive end of the self-serve price floor and undercuts Outpero's ₹3.5/min floor.

### Bolti — the flat-rate price anchor

- **Pricing** [Listing, MyOperator + a second source citing it]: **flat ₹6/min, free 50-minute trial, no monthly minimum.** Claims 80+ languages incl. Hindi, Tamil, Telugu. Targeted at developers/technical teams.
- I could not independently verify from Bolti's own site in this pass — **treat as [Listing]-grade only**.

### Caller Digital (`caller.digital`) — Noida, outcome-priced

- **What they sell** [Vendor]: "AI call automation" for Indian enterprises; voice plus chat, WhatsApp, email. Headline: **"Pay Per Outcome, Not Per Minute."**
- **Pricing**: No figures on the homepage; it says it *starts* per-minute and moves to outcome-based at scale, "No Setup Cost" [Vendor]. MyOperator's comparison lists **₹5–25 per connected call or outcome** [Listing].
- **Target**: Real Estate, Retail/E-com, Healthcare, BFSI, Insurance, EdTech, Telecom, Hospitality, Logistics, Travel, Manufacturing, Quick-Commerce. MyOperator characterises it as D2C and NBFC [Listing].
- **Languages**: Hindi, Hinglish + "13 regional languages" in the headline; other sections say "10+" — **internally inconsistent** [Vendor].
- **Inbound/outbound**: **Mostly outbound** (lead follow-up, reminders, COD confirmation, EMI reminders, abandoned cart, CSAT/NPS). FAQ claims inbound too.
- **Notable**: UPI link delivery during calls; escalation to live agents; shared conversation context across channels; Zoho/Salesforce/HubSpot/LeadSquared. Offices claimed in Noida, Dover DE, and Hamburg. "Trusted by 50+ Indian Enterprises" [Vendor].
- **Compliance claims** [Vendor]: HIPAA, GDPR, SOC 2 Type 2, ISO 27001, "DPDP-aligned, RBI-compliant."
- **Verification/hallucination claims**: **None.** Closest: the AI "flags suspect orders before dispatch." Headline stats (70% conversion lift, 95% reachability, 60% lower CAC) have no methodology — unverified.
- **[Inference]** Adjacent-leaning-direct. Their outcome-pricing positioning is the most interesting commercial idea in the set and the thing most likely to reset buyer expectations.

### Edesy (`edesy.in`) — Edesy Technology Labs Pvt Ltd

- **What they sell** [Vendor]: A sprawling grab-bag — "70+ products, 27 apps": AI phone agent (inbound + outbound, books appointments, qualifies leads), Edesy IVR (keypad menus, visual flow builder, Hindi/English TTS, outbound call API), Gemini Live integration (native audio-to-audio, 30 HD voices), voice cloning from ~60s of audio, voice commerce, CRM, forms, PDF tools, Convo AI omnichannel, Shopify WhatsApp cart recovery, a blog SaaS.
- **Telephony**: **Twilio and Exotel integration** — same architecture class as Atithi.
- **Languages** [Vendor]: **Internally contradictory** — "50+ languages" in one place, "13 languages (10 Indian)" for the Voice AI Platform. Hindi, Tamil, Telugu named.
- **Pricing** [Vendor]: Edesy IVR **₹20 free credit**, no card. Edesy Forms free. Everything else is "Get Free Demo" / "Book demo" — **no published prices.**
- **Target**: E-commerce (Shopify/WooCommerce), healthcare ("HIPAA-compliant voice AI"), real estate, restaurants, appointment-based businesses.
- **Traction claims** [Vendor, unverified]: 500+ active businesses, 2M+ conversations/month, 99.9% uptime SLA, SOC 2.
- **Verification/hallucination claims**: **None.** Only security/compliance badges and vague ROI claims ("reduce costs 70%", "300% efficiency").
- **[Inference]** Breadth without focus. The product-count sprawl and self-contradicting language counts are signals of a thin, SEO-driven operation rather than a focused competitor. Low threat to a focused clinic product, but it occupies search real estate.

### Ringg AI (`ringg.ai`) — Series A, July 2026 [News]

- **What they sell** [Vendor]: AI voice + chat agent platform; one agent deployed across voice calls, chat, WhatsApp, web.
- **Target/verticals** [Vendor]: **Healthcare appointment booking (named customer: Practo)**, ed-tech lead qualification (CollegeVidya), e-commerce cart recovery (Tata1mg), BFSI KYC (Flipkart). Also names CRED, Groww, PharmEasy, PolicyBazaar.
- **Pricing** [Vendor]: **flat "starting at $0.10 per connected minute"** (≈₹8.8/min at ~88 INR/USD) — notably *above* the Indian self-serve band.
- **Languages** [Vendor]: 20+, "SOTA accuracy in all" (vendor claim).
- **Inbound/outbound**: Both; outbound-weighted use cases.
- **Notable**: In-house models (LLM, STT "Parrot", TTS); sub-400ms claim; 120K+ interactions/hour; visual workflow canvas with conditional branching, retries, voicemail detection, API requests; on-prem/private cloud; SOC 2 Type II + ISO 27001 claimed.
- **Traction** [Vendor]: Practo testimonial — **~1,000 appointments booked daily.** This is the strongest third-party-attributed appointment-booking proof point I found in India.
- **Verification/hallucination claims** [Vendor]: **Important nuance — they get closest of any Indian vendor, but in the wrong direction.** Their QA layer **flags hallucinations *after* calls**, citing an example where the agent gave incorrect policy information. That is **post-hoc detection, not pre-confirmation gating.** The FAQ says agents can retrieve account details from a database but does not explain how responses are checked against it.
- **[Inference]** Ringg proves the clinic/appointment use case works at scale in India (Practo), and proves hallucination is a *recognised* problem (they built QA detection for it). They have not closed the loop to blocking a false confirmation before the caller hears it. That gap is precisely Atithi's claim.

### Lower-confidence direct players (thin or SEO-heavy; verify before citing)

| Name | What I found | Confidence |
|---|---|---|
| **Hayati AI Nexus** (`hayatiainexus.com`) | AI receptionist for Indian hospitals; Telugu + Hindi; says accent/phrasing is tuned per region **during pilot**, not promised as unlimited languages day one; **says verbal confirmation is not enough for Indian patients, who expect WhatsApp proof**; checks doctor/department rules before booking [Listing summary] | Medium. **See Part 5 — their "WhatsApp proof" framing is the closest any Indian vendor comes to Atithi's thesis.** |
| **Tele AI Indic** (`teleai.tech`) | Multilingual AI customer care for Indian businesses; healthcare page says AI follows **strict identity-verification protocols before sharing medical information** — that is identity checking before disclosure, **not** booking verification [Listing summary] | Medium |
| **AIOnCalls** (`aioncalls.com`) | "AI Medical Receptionist"; Hindi + English; claims sub-1-minute booking; no hallucination controls described [Listing summary] | Low-medium |
| **Frontiva AI** (`frontivaai.in`) | City-targeted ("AI Receptionist Pune"); notably **admits it does not handle Marathi** while serving Pune, and notes local callers mix Hindi and English [Vendor] | Low. City-SEO play |
| **Zeroic** (`zeroic.in`), **Trikon** (`trikon.tech`), **Vomyra** (`vomyra.com`), **Beside** (`beside.com`) | Appear in search results for Indian AI receptionist / voice agent terms. Trikon advertises **"Flat ₹5/min, All-In"**; Vomyra advertises **₹5/min pay-as-you-go and an unlimited plan from ₹19,999/month** [Listing]. Not independently fetched this pass. | Low — **unverified**, listing-grade only |

---

## Part 3 — Adjacent players (enterprise, infrastructure, or wrong vertical)

These compete for voice-AI budget but not for a ₹1,000-a-month clinic.

### Model / infrastructure layer

| Company | What they sell | Languages | Pricing | Funding / scale |
|---|---|---|---|---|
| **Sarvam AI** | Indic voice/language/document **models and APIs** (TTS, STT, translation, doc digitisation, dubbing) + enterprise agent products. A "Voice Agents" product exists but is undocumented on the site. On-prem / air-gapped / VPC options; forward-deployed engineers. | TTS 11 Indic, STT 12 Indic, translation 23 | API pricing not published | **Series B first close reportedly $234M of a $300M target at ~$1.5B post-money valuation (2026); total raised estimated $41M–$54M before that** [News, sources conflict]. Customers named: Axis Bank, Tata Capital, SBI Life, LIC, Infosys; government work incl. Aadhaar, NABARD, Skill India [Vendor]. |
| **Vobiz** (`vobiz.ai`, Ilaimitado Private Limited / Vobiz Inc.) | **Telephony infrastructure for voice agents** — SIP trunking, numbers in 130+ countries, real-time audio streaming, API call control. Sits *under* Vapi/Retell/LiveKit/Pipecat/ElevenLabs/OpenAI Realtime. | Not stated | Per-minute, not published | Positioned on **governance, compliance, observability** [News, Inc42]. CDRs with **43 fields** (MOS, jitter, packet loss, codec, who hung up and why), PCAP capture. **Crucially: their audit features cover telephony quality and metadata, not whether the agent's statements were correct.** |
| **Bolna** (`bolna.ai`, Whismurwave Inc.) | Voice AI agent platform — no-code playground + developer APIs. Templates: Reminders, Customer Support, Lead Qualification, Announcements. 20+ swappable ASR/LLM/TTS models. | "10+ vernacular Indian languages"; Hinglish, Hindi, Tamil, Telugu named | **₹5.52/min base** per one listing; **~₹5.5/min self-serve, ₹1.75–₹2/min for large enterprise commitments** [News, Inc42]. $5 free signup credits. | **$6.3M seed led by General Catalyst, Jan 2026, with Y Combinator participating** [News]. Customers: Physics Wallah, Spinny, GoKwik, Futwork, Awign. Twilio/Plivo/Vobiz/SIP; n8n/Make/Zapier. India + USA data residency, on-prem. **Explicitly targets enterprises and developers, not SMBs** [News]. |

### Enterprise CX / contact centre

| Company | Position | Languages | Pricing | Funding / scale |
|---|---|---|---|---|
| **Jio Haptik** | Enterprise conversational AI, **now moving down-market**: SMB AI agents via the **Interakt** platform. | **22 Indian languages** | **₹10,000 for ~2,000 conversations; company-stated ₹3–₹5 per conversation** [News, multiple outlets]. Older enterprise estimates ₹25k–₹1L/month, now dated. A third-party review estimates ~$5,000/yr [Listing]. | Reliance-owned. Interakt claims **50,000+ SMBs already** [News]. **This is the single biggest competitive threat by distribution.** |
| **Yellow.ai** (Bitonic Technology Labs) | Enterprise CX agent platform. **Nexus VOX** = voice agents claiming "500+ languages"; Nexus EDGE = desktop/EX agent with **human approval on every action**. | 500+ claimed for voice; 130 / 20+ Indian per listings | Enterprise only. One listing estimates **₹5–20L+ per year** [Listing, Vyora] | **~$102M total raised** [News]. Plans a US IPO 2026–27 per Economic Times [News]. Claims 650+ brands. 15+ LLMs, 150+ integrations. |
| **Gnani.ai** | Enterprise voice AI with **its own full model stack** — Prisma v2.5 (STT), Timbre v3.0 (TTS), Warp v2.0 (speech-to-speech), Evon v3.3 (LLM). Voice biometrics with anti-spoofing/liveness. Agent Assist. | **40+ languages/dialects; 12+ Indian** | Custom / usage- or outcome-based; not published | **$10M Series B led by Aavishkaar Capital with Info Edge Ventures, March 2026**; total raised reported as ~$7.7M or ~$17.7M depending on source [News, conflicting]. Claims 250+ enterprises, 50M+ daily voice interactions, trained on **14M+ hours of telephonic audio**, #1 on Berkeley BFCL v3 and in 8 of 9 Indian languages on Kathbath Noisy 8kHz. **Claims >80% gross margins from owning its own orchestration/denoising/turn-taking stack** [News, Inc42]. |
| **Ozonetel** | Cloud contact-centre platform + Voice AI Agents, Agent Assist, Knowledge AI, call summarisation, dialers, IVR. | "24 vernacular languages" | Not published | Claims 3,500+ business customers, 27 awards [Vendor]. |
| **Exotel** | CPaaS + GenAI voicebot ("Agentic AI for Voice Conversations"). Healthcare appointment scheduling is a named use case. | **Hindi, English, Hinglish** only on the voicebot page | One listing: prepaid bundle **from ₹9,999 for 5 months (~₹2,000/mo) plus usage**; characterised as inbound/IVR-strong and **not suited to outbound conversational AI** [Listing, Vyora] | Not disclosed on the page. |
| **MyOperator** | "Business AI Operator" — AI voice agents, chat agents, WhatsApp automation, call management, managed onboarding with a dedicated AI Agent Manager. | English, Hindi, Hinglish + 9 Indian (their own table marks Tamil/Telugu/Kannada as "Confirm") | Custom quote on their own site; one listing says **~₹10,000/month + ₹20,000 one-time onboarding** [Listing, Vyora] | Claims DPDP-ready and TRAI-compliant; go-live 1–2 weeks [Vendor]. |
| **SquadStack** (`squadstack.ai`) | **Outbound sales** voice agents + **Arth**, its in-house STT. | **9 Indian languages** (Hindi, English, Tamil, Telugu, Kannada, Marathi, Malayalam, Gujarati, Bengali); mid-sentence switching, code-mixed Hinglish | FAQ states **~₹2–₹5/min typical**, plus one-time setup for enterprise; **dialer and telephony included, unlike most vendors** [Vendor] | Claims **5 million+ AI calls daily**, 60+ brands, 6 years operating, trained on 600M+ minutes of Indian contact-centre audio. No funding stated. DND scrubbing before dialing, calling-window enforcement. |
| **Skit.ai** | **Debt collections only.** AI agents named Manager, Collector, Analyst, Auditor, Coach, Scrubber, Tracer. Offices New York + Bangalore. | Hindi, English + "multiple regional languages" for India | Not published; one India case study says **performance-based pricing** | Claims 8 years, 1 billion conversations, $1B+ accounts resolved, 53,000+ creditors across 19+ debt types. No funding stated. **See Part 5 — their "Auditor" agent is the most architecturally relevant thing in this whole report.** |
| **Karta AI** | Inbound voice agents for **bank helplines** — banks, lenders, fintechs, insurers. Bengaluru. | Not captured | Not public | **$3M seed co-led by PeerCapital and Cedar Hill Capital, October 2026** [News]. |
| **Arrowhead** | Financial-services voice AI | — | — | **$3M seed, January 2026** [News] |
| **Vaani AI Research** | Developer APIs/SDKs/models for multilingual voice agents, Bengaluru | — | — | **$400K pre-seed led by Venture Catalysts**; reportedly selected for Google for Startups AI Accelerator 2025 [News]. Founding year reported inconsistently as 2023 or 2024. |

### Acquired / no longer independent

- **Knowlarity** — acquired by **Gupshup** (announced early 2022, price undisclosed). Had cloud telephony, contact-centre automation, AI voice assistants and speech analytics for 6,000+ customers in 65 countries [News].
- **Kaleyra** — acquired by **Tata Communications for $100M** [News]. CPaaS: messaging, voice, video, chatbots.
- **[Inference]** Both are now CPaaS plumbing inside larger groups. Neither is a meaningful competitor to Atithi; both could become distribution channels for someone else's agent.

### Global / not India-specific

- **Open** (`open.cx`, OpenChat Inc.) — AI customer support platform, "Agent 5", claims 77% average automation rate. Voice is one of many channels (web chat, email, WhatsApp, SMS, social, Slack). **Pricing: $0.90 per automated resolution, explicitly no per-seat.** EU data residency (Frankfurt), SOC 2 Type II, ISO 27001, automatic PII/PHI redaction. **No languages stated, no India focus, no verticals named.** [Vendor] **[Inference] This is a support-ticket deflection product, not an Indian SMB receptionist. Adjacent at best — the brief's inclusion of it appears to be a mis-lead.**
- **AnveVoice** — website voice widget (covered in Part 1). $0 / $39 / $129 per month.
- **Newo.ai**, **KaiCalls**, **Synthflow**, **Phonely**, **Zoom AI Receptionist** — US/global inbound receptionist players. Relevant **only** to question 4; see Part 5. (Phonely raised a **$22M Series A at a $100M valuation**, YC-backed [News] — evidence of how much capital is flowing into the inbound-receptionist category globally.)

---

## Part 4 — Answers to questions 1, 2, 3, 5

### Q1. Direct competitors vs adjacent

**DIRECT — same buyer, same budget line, same job (an inbound AI receptionist a clinic/salon owner buys self-serve):**

1. **ConnectAI** (`connectai.care`) — clinics only, published ₹800/mo + ₹4/min, WhatsApp-first, bundled with Google/GMB patient acquisition
2. **Pluxo** (`pluxo.ai`, Clevora AI Pvt Ltd, Bengaluru) — Indian healthcare, 11 languages, UPI, HIMS/EMR integration
3. **VaniAgent** (`vaniagent.com`, Solvea Technologies Pvt Ltd) — clinics + salons + coaching, i.e. Atithi's exact vertical list
4. **CallMissed** (`callmissed.com`, Pune) — inbound missed-call wedge, 22 Indian languages, free tier, bundled CRM
5. **HuskyVoice AI** (`huskyvoice.ai`) — clinics India, inbound-primary, data-residency options
6. **Vyora AI** (`vyora.ai`) — ₹799/mo self-serve, 11 languages, voice-only
7. **Tabbly** (`tabbly.io`) — ₹4.5/min PAYG, explicit "AI receptionist" product
8. **Outpero** — the known rival; **and it has an Inbound product, so the overlap is larger than the brief assumes**
9. **Bolti** — ₹6/min flat (listing-grade only)
10. Lower confidence: Hayati AI Nexus, Tele AI Indic, AIOnCalls, Frontiva, Zeroic, Trikon, Vomyra

**ADJACENT — competes for voice-AI budget but not for this buyer:**

- **Wrong buyer (enterprise-only):** Yellow.ai, Gnani.ai, Ozonetel, Exotel, MyOperator, Karta AI, Arrowhead
- **Wrong job (outbound sales/collections):** SquadStack, Caller Digital, Skit.ai (collections only)
- **Wrong layer (infrastructure Atithi could *buy*, not compete with):** Sarvam AI, Vobiz, Bolna, Vaani AI Research
- **Wrong geography/channel:** Open (open.cx), AnveVoice (website widget), Newo.ai, KaiCalls, Synthflow, Phonely
- **Acquired/absorbed:** Knowlarity (Gupshup), Kaleyra (Tata Communications)

**The one that doesn't fit the categories — and matters most:**

**Jio Haptik.** Enterprise platform, **22 Indian languages**, now selling SMB AI agents at **₹10,000 for 2,000 conversations (₹3–₹5 per conversation)** through **Interakt, which already has 50,000+ SMB customers** [News]. **[Inference] This is the most dangerous entity in this report, and it is not dangerous because of its product — it is dangerous because of its distribution.** Reliance can bundle this with Jio connectivity and push it through an existing SMB base that Atithi would spend years building. Atithi cannot win a distribution fight with Reliance; it has to win on depth in a vertical Reliance won't tune for.

### Q2. Table stakes — features in nearly every competitor

Counting across the direct set, these appear so consistently that their *absence* is disqualifying. Atithi must have all of them:

| Feature | Prevalence | Notes |
|---|---|---|
| **24/7 inbound call answering** | Universal | The entire pitch. Every single vendor leads with it. |
| **Appointment booking into a real calendar** | Universal in the direct set | Google Calendar is the default; clinic-specific players add HIMS/EMR/CRM |
| **Multiple Indian languages with mid-call switching** | Universal | Floor is ~10–11; CallMissed claims 22, Haptik 22. **Mid-sentence/code-mixed switching is now explicitly claimed by CallMissed, SquadStack, Pluxo, Tabbly — it is no longer a feature, it is an expectation.** |
| **Hinglish / code-mixed handling** | Universal | Called out separately from "Hindi" by nearly everyone |
| **WhatsApp integration** (confirmations, reminders, follow-ups, handoff) | Near-universal | **In India this is not optional.** ConnectAI is WhatsApp-*first*. Vyora publishes its lack of a WhatsApp inbox as a known limitation. Hayati states patients expect WhatsApp proof. |
| **Human handoff / escalation with context** | Universal | Every vendor. Usually "transfer with summary" |
| **Call recordings + transcripts + summaries** | Universal | Atithi already has this (`calls/<client_id>/*.json`) |
| **Dashboard with call history and booking log** | Universal | |
| **Barge-in / interruption handling + low latency** | Universal, with a latency arms race | Published claims: Gnani <200ms P95, Bolna <300ms, Tabbly <300ms, Ringg <400ms, Newo 842ms, Outpero 0.8–1.3s. **Sub-300ms is the advertised bar.** |
| **Missed-call / after-hours recovery framing** | Near-universal | The dominant *marketing* frame, not just a feature |
| **CRM / webhook / Zapier-n8n-Make integration** | Near-universal | |
| **Free trial with non-expiring credits** | Near-universal in self-serve | **Outpero 50 credits; Vyora 50 credits; CallMissed 1,000 credits; Bolti 50 free minutes; Tabbly $10; Edesy ₹20.** Non-expiry is explicitly advertised by Outpero, Vyora and CallMissed. |
| **Lead capture when no booking happens** | Common | Atithi has this (`save_lead`) |
| **Compliance badge wall** (SOC 2 / ISO 27001 / HIPAA / GDPR / DPDP) | Near-universal, including by tiny vendors | **[Inference] These badges are being claimed by companies that plainly cannot have earned them. Buyers have learned to discount them — which means they are table stakes to *state* but worthless as differentiation.** |
| **DLT registration / TRAI / consent checks** | Emerging but increasingly named | Outpero (DLT numbers, consent checks), SquadStack (DND scrubbing, calling-window enforcement), MyOperator (TRAI-compliant), Caller Digital (DPDP-aligned). **[Inference] India-specific regulatory plumbing is becoming table stakes and is a real engineering cost Atithi should not discover late.** |

**Things that are NOT yet table stakes (genuine differentiation space):** UPI payment collection in-call (only Pluxo, ConnectAI, Caller Digital), clinic EMR/HIMS write-back (only Pluxo, HuskyVoice), per-region accent tuning (only Hayati), least-privilege tool scoping (only CallMissed states it), and **anything resembling a proof check (nobody — see Part 5).**

### Q3. Pricing models

**Per-minute usage pricing dominates decisively.** Inc42's independent reporting confirms it: *"Usage-based (per-minute) pricing remains the dominant model"*, with outcome-based appearing only in narrow workflows like gig-worker recruitment and surveys, and founders expecting hybrids (base usage fee + outcome incentives) next [News, Inc42].

**Verified per-minute rates (2026-10-25):**

| Vendor | Rate | Evidence |
|---|---|---|
| Tabbly (enterprise volume) | **₹3/min** | Vendor |
| Outpero (custom, high volume) | **₹3.5/min** | Vendor |
| ConnectAI | **₹4/min** (8 credits) | Vendor |
| CallMissed (Standard) | **₹4/min** | Vendor |
| Tabbly (pay-as-you-go) | **₹4.5/min**, billed by the second | Vendor |
| **Outpero (Standard)** | **₹5/min** | Vendor |
| CallMissed (Expressive) | **₹5/min** | Vendor |
| Trikon | ₹5/min "all-in" | Listing |
| Vomyra | ₹5/min PAYG | Listing |
| Bolna (self-serve) | **~₹5.5/min** | **News (Inc42)** |
| Bolna (listed base) | ₹5.52/min | Listing |
| CallMissed (best latency) | **₹6/min** | Vendor |
| Bolti | ₹6/min flat | Listing |
| **Outpero (Premium)** | **₹6.8/min** | Vendor |
| Ringg AI | **$0.10/connected min (≈₹8.8)** | Vendor |
| Bolna (large enterprise commit) | **₹1.75–₹2/min** | **News (Inc42)** |
| SquadStack | **₹2–₹5/min**, telephony + dialer included | Vendor |

**The band: ₹3–₹7/min for self-serve, with a ₹5–₹5.5/min centre of gravity.** Inc42 independently puts the market at ₹2–₹12/min with ₹3–₹6 as the common mid-market band and ~₹5.5/min typical for self-serve [News]. **Atithi's per-minute cost must land under ~₹5 to be credible, and under ~₹3.5 to claim price leadership.**

**Subscription / monthly, where published:**

| Vendor | Monthly | Evidence |
|---|---|---|
| ConnectAI AI Clinic Mgmt Software | **₹500/clinic/mo** + ₹100/extra doctor | Vendor |
| ConnectAI Voice Receptionist (as add-on) | **₹499/mo** + ₹4/min | Vendor |
| **Outpero business number** | **₹649/mo per channel** | Vendor |
| ConnectAI Voice Receptionist (standalone) | **₹800/mo** + ₹4/min | Vendor |
| Vyora (entry) | **₹799/mo** | Vendor |
| ConnectAI Automation Suite | **₹2,499/mo** all-in | Vendor |
| Vyora (Business) | **₹3,449/mo** | Vendor |
| Exotel | ₹9,999 / 5 months (~₹2,000/mo) + usage | Listing |
| MyOperator | ~₹10,000/mo + ₹20,000 one-time onboarding | Listing |
| Vomyra (unlimited) | ₹19,999/mo | Listing |
| HuskyVoice | ₹39,990 base (period ambiguous) | Listing |
| Yellow.ai | ₹5–20L+ **per year** | Listing |

**Per-outcome / per-resolution / per-conversation (the minority model):**

- **Caller Digital: ₹5–25 per connected call or outcome** [Listing] — and "Pay Per Outcome, Not Per Minute" is their entire homepage headline [Vendor]
- **Jio Haptik: ₹10,000 / 2,000 conversations = ₹3–₹5 per conversation** [News]
- **Open (open.cx): $0.90 per automated resolution** [Vendor]
- **Skit.ai: performance-based pricing** in at least one India case study [Vendor]
- Market commentary: ₹8–25 per successful outcome depending on use case [Listing]

**The dominant shape for Atithi's segment is a HYBRID: a small monthly (₹500–₹900) that covers the number/channel, plus per-minute usage (₹4–₹5).** ConnectAI (₹800/mo + ₹4/min) and Outpero (₹649/mo + ₹5/min) have independently converged on almost the same structure. **[Inference] That convergence is the market telling you the right shape. Deviating from it costs you explanation time in every sales call.**

**Critical unit-economics context [News, Inc42]:**
- **Human call centres run ~₹7–₹8/min**, excluding hiring, training and attrition. That is the real ceiling — AI must sit visibly below it.
- Human receptionist salaries for comparison: ~₹19,621/month for salon roles nationally, ~₹38,642/month for clinic roles in Bengaluru [Listing, undated — treat loosely].
- **Gnani claims >80% gross margins** by owning its own orchestration, denoising and turn-taking stack; its CEO says **aggregators often struggle to make money because every layer carries an external cost** [News]. **[Inference] This is the single most important sentence in the report for Atithi's pricing. Atithi is currently an aggregator (Gemini + edge-tts + Twilio). At ₹5/min with four external cost layers, the margin is thin and compresses as competitors with in-house models cut price. Know the per-minute COGS before publishing a price.**
- **~60,000–90,000 connected call minutes for a single use case** is the benchmark one founder cites for the economics to work [News].
- **Hidden costs are the norm**: advertised rates typically exclude telephony carriage, platform fees and setup. One vendor's own analysis says a ₹3/min headline **typically lands at ₹6–₹9 in production** [Listing, Caller Digital]. **[Inference] "All-in, no hidden fees" is an available and credible positioning — Trikon and SquadStack are already reaching for it.**

### Q5. Whitespace — what nobody is doing well

Ordered by how defensible I think each is.

**1. Proof-gated confirmation in the Indian market — open, but narrowing.** See Part 5. No Indian vendor advertises it. The concept is already shipped and marketed in the US. **[Inference] This is a 6–18 month positioning window, not a moat.**

**2. Verifiable outcome reporting to the business owner.** Every vendor shows the owner transcripts and call counts. **Nobody shows the owner a reconciliation: "the agent said 'booked' 47 times this month; 47 rows exist in your register; 0 discrepancies."** [Inference] This is the *commercial* expression of the proof check and it is far more defensible than the engineering, because it is what the owner can actually feel. It converts a technical property into a monthly trust artefact. Atithi already writes one JSON per call and owns the booking store — it has the raw material and nobody else is framing it this way.

**3. Telugu (and non-Hindi South Indian) depth, as opposed to a checkbox.** Telugu appears in long language lists everywhere (Outpero, Pluxo, Vyora, CallMissed, SquadStack, Gnani, Tabbly, ConnectAI), but **only Hayati AI Nexus says anything about per-region accent and phrasing tuning during pilot**, and Frontiva openly admits it cannot do Marathi while selling into Pune. [Inference] The gap between "Telugu is in our list" and "handles Telangana vs coastal Andhra phrasing, and code-mixes with English the way a real receptionist does" is wide, unmeasured by any buyer today, and exactly where a founder-operated product beats a 50-language platform. **Atithi's evals directory is the right instrument; publishing eval results per language would be genuinely novel in this market.**

**4. Honest, published, all-in pricing.** The hidden-fee problem is so widespread that vendors write blog posts about each other's hidden fees. [Inference] A published, GST-inclusive, telephony-included, single-number price would be differentiating — and it is cheap to do.

**5. Clinic-record write-back rather than calendar-only booking.** Only Pluxo and HuskyVoice mention HIMS/EMR/clinic-CRM integration, and Pluxo hedges it with "where API access is available." [Inference] Most competitors book into Google Calendar and stop. A booking that does not reach the system the front desk actually uses is a booking the clinic does not trust — and it is the same failure mode as a hallucinated confirmation, one layer down.

**6. The "second question" problem.** Pluxo is the only vendor I found that **logs the question the agent could not answer so the owner can answer it once**, turning failures into knowledge. [Inference] Everyone else escalates and forgets. This is a cheap, high-retention feature.

**7. Owner-facing operational trust, not badge walls.** Everyone claims SOC 2/ISO/HIPAA, including vendors whose client counters render as "0+". [Inference] The badges are saturated and discounted. What is unoccupied is operational transparency a non-technical owner can verify in thirty seconds: what the agent said, what it did, whether those two things agree.

**Where there is NO whitespace — do not build here:** 24/7 answering, language lists, latency claims, WhatsApp reminders, transcripts, dashboards, human handoff, free trials, CRM webhooks. All saturated.

---

## Part 5 — Q4: Is the "proof check" actually unique?

**This is the question that matters most, so here is the direct answer first.**

> **No. The proof check is not novel, and it is already a shipped, marketed product feature — in the United States. But I found no Indian vendor advertising it, and no vendor anywhere positioning it as their primary differentiator for SMBs. Atithi's differentiator is real as *positioning in the Indian market*, and it is real as *engineering discipline*, but it is not a technical moat and it has a visible shelf life.**

### 5a. The one vendor that advertises exactly this

**KaiCalls** (`kaicalls.com`, operated by **Meet Kai LLC**, © 2026 — US; location not stated on the page). Their reliability guide states their product behaviour directly:

> **"a confirmation is blocked unless the provider proved the action happened."** [Vendor]

Their published architecture is, feature for feature, what Atithi describes as its differentiator:

1. **Proof-gated confirmations** — the agent confirms only after the underlying system returns durable proof: a booking ID, a confirmed calendar write, or a delivery receipt.
2. **Explicit outcome states** — every action resolves to one of *success / needs clarification / unavailable / queued / failed*, and each state maps to fixed phrasing. Unsure or failed actions produce a clarifying question or a message. **Raw system errors are never spoken.**
3. **Constrained call flows** — business-specific information only; out-of-scope questions route to a message or a human.
4. **Per-call evidence** — transcripts, recordings, summaries, AI quality scoring.
5. **Versioned agent changes with rollback** — before/after history, revertible.
6. **Human escalation** — ring-first routing (owner's phone rings before the AI answers).

They also publish a **caution that directly undercuts the naive version of Atithi's claim**: mid-call supervisor/verifier models *"are built on the same model class, so they can be wrong, add latency, or cause awkward corrections."* They explicitly do **not** present an LLM verifier as a KaiCalls feature.

**[Inference] This is the most important finding in the report, and it cuts two ways.** Negatively: someone has already built, shipped and marketed Atithi's differentiator, and written a better explanation of it than Atithi currently has. Positively: **the distinction KaiCalls draws — between a *deterministic* proof gate (check the record, block the confirmation) and an *LLM verifier* (ask a second model if the first was right) — is the correct one, and it is the version Atithi should be building.** Atithi's architecture already favours the deterministic version: tool calls return real validation errors, and `storage.py` owns the booking record. If Atithi's proof check is "read back the row we just wrote, or don't say 'booked'", that is the defensible design. If it is "ask Gemini whether Gemini was telling the truth", KaiCalls has already published why that is weaker.

### 5b. Claims that look like it but are not

| Vendor | What they actually claim | Why it is not a proof check |
|---|---|---|
| **Newo.ai** (US) | KaiCalls links to a comparison titled *"How KaiCalls compares against 'Zero-Hallucination Architecture' claims"* and attributes a zero-hallucination claim to Newo.ai [Listing — and the listing is a competitor's]. **I fetched newo.ai directly and the phrases "zero hallucination" and "Zero-Hallucination Architecture" do NOT appear.** The closest content is a **98.7% intent accuracy** figure with no methodology, and an "Act" step described as *"Integrate, verify, and execute in real time"* — which does not say what is verified or against what. | **Secondhand and unconfirmed.** Do not cite Newo as a zero-hallucination claimant; a competitor said it, their own site does not. |
| **Jio Haptik** | A **July 30, 2026** blog, *"Hallucination in Voice AI Agents."* Claims retrieval-grounded design where responses come only from approved client documentation, retrieval kept separate from the LLM's general knowledge, escalation to a human on low retrieval confidence, admin tools to review responses, and audit logs tracking responses **against source documents**. Describes a *"secondary, low-latency monitoring model that runs concurrently during high-stakes calls"* checking statements against policy guardrails. | **Two gaps.** First, the concurrent auditor is described as a general industry mitigation pattern, **not as a Haptik feature** — Haptik's own platform section lists only three items (RAG guardrails, low-threshold escalation, knowledge governance/audit logs). Second and more important: **grounding against *documents* is not verification against *records*.** Knowing the price list is right does not stop the agent saying "you're booked" when no booking exists. No release dates, version numbers or docs — **thought leadership, not a shipped feature.** |
| **Ringg AI** (India) | QA layer **flags hallucinations after calls**, with a cited example of the agent giving incorrect policy information [Vendor]. | **Post-hoc detection, not pre-confirmation gating.** The caller has already been told the wrong thing. This is the closest any *Indian* vendor comes, and it is on the wrong side of the moment that matters. |
| **Skit.ai** (India/US) | The **Auditor** agent enforces rules **"at the action layer"** so non-compliant outreach is **blocked before it goes out**. Plus guardrails, bias controls, human oversight, FDCPA/TCPA/Reg F alignment, audit trails, opt-out enforcement. The **Tracer** agent validates phone numbers; reconciliation tools are mentioned for data consistency. | **Architecturally the closest analogue in the Indian ecosystem — blocking at the action layer is exactly the right pattern — but it is pointed at regulatory compliance, not at factual booking claims.** Their own test stage mentions only *"accuracy, safety checks"* with no detail. **[Inference] Skit has built the mechanism Atithi wants, for a different purpose, in a different vertical. That is validation that the pattern works, and evidence that nobody has aimed it at appointment booking.** |
| **SquadStack** (India) | The self-improvement layer **cannot modify compliance language, product rules, pricing guardrails or agent identity** — these sit in locked sections. AI + human quality audits across **23 parameters**, dual-layer QA, compliance audit trail. [Vendor] | Good immutability design and serious QA, but **about what the agent is allowed to say, not whether what it said was true.** Never uses the word hallucination. |
| **Pluxo** (India) | Bookings sync to connected calendars and blocked slots stay unavailable, which they say **prevents double-booking**. The AI **"says so rather than guessing"** when it lacks an answer. [Vendor] | **Calendar-state hygiene plus a refusal instruction in the prompt.** Prevents one specific collision; does nothing about a confirmation spoken after a failed write. |
| **CallMissed** (India) | *"WhatsApp replies are grounded in the documents you upload, not in whatever the model happens to believe."* [Vendor] | **Scoped explicitly to WhatsApp text.** No equivalent claim for the voice path — which is where phantom bookings happen. |
| **Hayati AI Nexus** (India) | **"Verbal confirmation is not enough for Indian patients who expect WhatsApp proof."** Checks doctor and department rules before booking. [Listing summary] | **The closest anyone in India comes to articulating Atithi's thesis — and they frame it as a *customer-trust* problem, not a *system-correctness* problem.** Their answer is a WhatsApp receipt (proof *to the patient*), not verification against the record (proof *of the record*). **[Inference] These are complementary, and Atithi should do both: verify the record, then send the receipt. The receipt is what the patient feels; the verification is what makes the receipt true.** |
| **Tele AI Indic** (India) | Strict identity-verification protocols before sharing medical information. [Listing summary] | Identity checking before disclosure. Unrelated. |
| **Synthflow** (global) | Agents *"follow approved knowledge sources to avoid hallucinated responses."* [Vendor] | Generic RAG grounding claim. No gate, no guarantee. |
| **Zoom AI Receptionist** (global) | Confirms bookings in the connected calendar and sends an SMS. [Vendor] | Confirmation *delivery*, not confirmation *gating*. |
| **Yellow.ai** | Nexus EDGE requires **human approval on every action**; "robust guardrails and Responsible AI principles." [Vendor] | Human-in-the-loop is a different (and for a receptionist, unusable) solution. No zero-hallucination claim, no record checking. |
| **Vobiz** (India) | 43-field CDRs, PCAP capture, audit logs, PII redaction. [Vendor] | **Telephony quality and metadata auditing — explicitly not whether the agent's statements were correct.** Worth naming because "observability" sounds adjacent and is not. |
| **Everyone else** — Outpero, ConnectAI, VaniAgent, HuskyVoice, Vyora, Tabbly, Caller Digital, Edesy, Bolna, Gnani, Exotel, Ozonetel, Sarvam, Open, MyOperator, Bolti | **No claim of any kind** about hallucination safety, accuracy guarantees, or verifying agent claims against records. | — |

### 5c. The pattern is being formalised in public

This is the part that sets the clock on Atithi's window.

- **Independent/technical write-ups now describe proof-gating as the correct architecture**, naming the exact failure mode: an agent that says *"You're all booked for Friday at seven"* after the booking API timed out or errored. [Listing]
- A booking-ledger blueprint sets the bar at **a calendar event identifier recorded before the agent says anything is booked**, and warns specifically that **tool-call identifiers show transport success, not that the calendar changed.** [Listing] **[Inference] This is a real engineering trap Atithi should check for in `agent.py` — a 200 OK from a write is not proof the row exists. The proof must be a read-back of the record, not the write's return value.**
- Developer commentary argues the rule **must sit at framework level, not in the prompt**: the tool returns a block message the model cannot override. [Listing]
- **Read-back of important details to the caller before acting** is widely recommended as a cheap guard against ASR errors in names and phone numbers. [Listing]
- OpenAI's realtime-voice guidance (as summarised by a third party) says to treat booking codes, order IDs, account and phone numbers as **high-precision values and confirm the final value before any write action.** [Listing]
- There is an **arXiv preprint titled "Tool Receipts, Not Zero-Knowledge Proofs: Practical Hallucination Detection for AI Agents"** (`arxiv.org/pdf/2603.10060`). **[Inference] When your differentiator has a paper named after it, it is a best practice, not an invention.**
- A second preprint, *"Efficient and Sound Probabilistic Verification for AI Agents"* (`arxiv.org/pdf/2606.20510`), indicates active academic work on agent verification.
- Separately, a **GitHub project by a single developer** (`Varun612/reception-ai`) describes an *"autonomous multi-tenant AI receptionist & appointment booking platform with phone voice studio, Call-to-Chat visual slot picker, multi-click deduplication, and patient telemetry"* [Listing]. **[Inference] This is architecturally very close to Atithi, built by one person, in public, for free. Worth looking at — both as a competitive signal and because multi-click deduplication is a real problem Atithi will hit.**

### 5d. What this means for Atithi — recommendation

**Keep the proof check. Change how you talk about it, and change what you claim.**

1. **Stop calling it unique. Call it *verified*.** "Unique" is falsifiable in one search — a prospect or an investor who finds KaiCalls in five minutes has found you overclaiming, which is a worse outcome than never having claimed it. **"Every booking confirmation is checked against the register before we say it"** is defensible, demonstrable, and does not depend on nobody else doing it.
2. **It is genuinely unclaimed in India.** No Indian vendor advertises it. In a market where ConnectAI's client counter reads "0+", Edesy's language count contradicts itself page to page, and everyone claims SOC 2, **a claim you can demonstrate live on a phone call is worth more than a claim nobody else has made.** That is the asset — demonstrability, not novelty.
3. **Build the deterministic version, not the LLM-verifier version.** KaiCalls has already published why a second model checking the first is weak (same model class, can be wrong, adds latency, awkward mid-call corrections). Atithi's edge is that `storage.py` owns the booking record: **read the row back, then speak.** That is a database read, not an inference call — cheap, fast, and actually sound.
4. **Check for the transport-success trap.** Per the booking-ledger guidance: a successful tool call is not proof of a written record. If `book_appointment` currently returns success based on the write returning without error, that is the exact bug the whole differentiator exists to prevent. **Verify against a read-back.**
5. **Adopt KaiCalls' explicit outcome states.** *success / needs clarification / unavailable / queued / failed*, each mapped to fixed phrasing, with raw errors never spoken aloud. This is published, it is good, and it is free to copy. It also fits Atithi's existing design where tools return errors the model can act on.
6. **Pair it with Hayati's insight.** Verify against the record (correctness), *then* send the WhatsApp receipt (trust). Indian customers expect the receipt; the verification is what makes the receipt honest. Doing one without the other wastes half the value.
7. **Make the monthly reconciliation the commercial artefact.** Nobody shows the owner "47 confirmations spoken, 47 records exist, 0 discrepancies." That turns an engineering property into something a clinic owner can feel every month, and it is the piece of this that is actually hard to copy — because it requires owning the booking store, which the aggregator-shaped competitors do not.
8. **Assume an 6–18 month window.** [Inference] The pattern is in blog posts, developer forums, vendor guides and two arXiv preprints. Haptik is already writing about hallucination in voice agents. Ringg already detects it post-hoc. Someone in India will advertise proof-gating within a year. **Use the window to build the trust artefact and the vertical depth (Telugu, clinic EMR write-back), because those compound and the slogan does not.**

---

## Appendix — Source index

**Fetched directly (vendor sites, 2026-10-25):** open.cx, edesy.in, sarvam.ai, gnani.ai, exotel.com/products/voicebot, ozonetel.com, skit.ai, yellow.ai, caller.digital, callmissed.com, connectai.care, bolna.ai, newo.ai, kaicalls.com/guides/ai-receptionist-reliability, haptik.ai/blog/hallucination-in-voice-ai-agents, huskyvoice.ai/ai-receptionist-clinics-india, pluxo.ai, vaniagent.com, squadstack.ai, ringg.ai, outpero.com, tabbly.io, vobiz.ai

**Comparison/listing pages fetched (note the publisher — each ranks itself):** vyora.ai/best-ai-voice-agent-india (published by Vyora, ranks itself #1), myoperator.com/blog/top-10-voice-ai-agents-india-2026 (published by MyOperator, ranks itself #1)

**Independent reporting used:** inc42.com/features/the-unit-economics-of-indias-voice-ai-boom (per-minute economics, margins, dominant pricing model — the single most useful non-vendor source found); entrackr.com and indianstartupnews.com (Karta AI $3M seed, Vaani AI Research $400K pre-seed); bolna.ai/newsroom (Bolna $6.3M seed, General Catalyst — vendor-published but a funding announcement); analyticsindiamag.com / tecknexus.com / getcoai.com (Jio Haptik ₹10,000 SMB pack); pymnts.com / venturebeat.com / futurumgroup.com (Gupshup–Knowlarity); martechvibe.com / businesswire.com (Tata Communications–Kaleyra, $100M); tracxn.com (30 voice AI startups in India, 17 funded, $87.1M collectively)

**Known-weak sources flagged in-text:** getlatka.com and builtin.com (MantraAssist — mutually contradictory); lablab.ai (CareVoice AI — hackathon); 34.138.86.231.sslip.io (VaaniYantra — raw IP host, unverified)

**Caveats on funding figures:** Sarvam AI and Gnani.ai totals conflict across secondary sources and should be checked against Entrackr, Tracxn, Crunchbase or company announcements before use in any deck. Numbers reported here are labelled with the conflict where it exists.
