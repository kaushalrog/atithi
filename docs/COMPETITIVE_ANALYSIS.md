# Competitive analysis: voice-agent testing and reliability

**As of:** 2026-10-14. Research was web search only. No product was signed up for, trialled, or contacted.
**Companion docs:** `docs/PRODUCT.md` (what we build), `docs/designs/claim-vs-records-checker.md` (approved design).

## How to read this

Every claim below has one of these evidence labels:
- **Vendor**: written by a company that sells in this market, often about its own ranking. Weak.
- **Listing**: a third-party directory or aggregator, usually repeating the project's own description. Weak to moderate.
- **Paper**: a research preprint. Moderate. Not peer-reviewed unless stated.
- **Anecdote**: one person's post. Weak.
- **Hypothesis**: our own inference. Not evidence.

**Nothing here is independently verified.** Prices and features change often. Check the vendor's own site before quoting any of it to anyone.

## 1. The market in one paragraph

Voice-agent testing is crowded. Most tools work by **simulation**: synthetic callers phone your agent, and a scorer (often an LLM) grades the conversation. Others focus on **production observability**: latency, transcription quality and failed function calls on live traffic. Pricing ranges from about $30/month developer tiers to sales-led enterprise contracts. Several free and open-source options exist. *(Vendor, Listing; sources in §5.)*

## 2. Who's there

| Tool | What it does (as described) | Price signal | Evidence |
|---|---|---|---|
| Cekura (formerly Vocera) | Testing and monitoring across the call lifecycle; simulation, production monitoring, CI integration | Developer plan listed at $30/month with a 7-day trial | Vendor [1][2][3] |
| Bluejay | Simulated phone calls with "digital human" personas across speech, ASR, LLM and TTS; then live monitoring | Not public, sales-led | Vendor [4], Listing [5] |
| Coval | Whole-call evaluation; simulation across many scenarios | Not found | Vendor lists [1][5] |
| Hamming AI | High-volume automated call simulation and QA | Not found | Vendor lists [1][5] |
| Roark | Production call replay: failed calls become test cases | Consumption-based, minimum monthly spend | Vendor lists [5][6] |
| Evalion | Human-in-the-loop testing plus caller simulation | Not public | Vendor lists [5] |
| Cyara | Enterprise testing of IVR, conversational AI and agentic workflows | Not public | Vendor lists [5] |
| VoiceRun | Voice runtime plus observability | $0.015/min per layer, $0.030/min full platform, plus storage | Vendor [7] |
| Vapi Test Suites | Automated tests built into the Vapi platform | Part of Vapi | Vendor lists [5] |
| Maxim AI, Braintrust | General LLM eval/observability, extended to voice | Braintrust Pro from $249/month | Vendor lists [5][6] |
| Arize Phoenix / AX | General LLM observability | Phoenix free OSS; AX Pro $50/month | Vendor [8] |
| **LangWatch** | Open source, self-hostable; voice simulation with noise and interruption injection | Free; paid tiers from $34/month in one comparison | Listing [5] |
| **Egma** | Open source (MIT). Simulation testing, monitoring, evaluation; personas, tool mocking, pass/fail thresholds; LiveKit and Retell support | Free | Listing [9] |
| **simulate-sdk** | Open source (Apache-2.0). Python SDK for synthetic voice interactions in CI | Free; ~59 GitHub stars per one listing | Listing [10] |
| **EVA-Bench** (ServiceNow research) | Benchmark: simulated spoken conversations, Accuracy and Experience scores, accent and noise perturbations; 213 scenarios, 12 systems, none above 0.5 on both | Free (research) | Paper [11] |

**Adjacent, not competitors: AI receptionists sold to Indian clinics.** These are Open (open.cx), Edesy, CareVoice AI, VaaniYantra, Saral AI and Anvevoice. They are VoxAgent's original market and potential *users* of a checker, not rivals to it. *(Vendor pages and one Anecdote [12]–[15].)*

## 3. What the failure evidence says

These sources describe the failure class the checker targets. All of them are Vendor or Anecdote evidence:
- **Claiming an action without the tool.** In one simulated call, an agent said it had updated an address without calling the tool. [16]
- **Hallucinated availability.** A booking bot suggested times from 2021 and failed bookings for lack of verification. [17]
- **Ungrounded promises** about pricing and availability. [18]
- **The Air Canada case.** A tribunal held the airline to its chatbot's wrong bereavement-fare policy. [19]

  This is a widely reported legal case. We cite it here only as an illustration via [19]. Before quoting it externally, read the primary tribunal decision.
- **Hard numbers.** The only hard number found was a 0.34% hallucination-related complaint rate. The source calls it a secondary compilation, so it is weak evidence. [19]

## 4. Where VoxAgent's checker sits (hypotheses, not facts)

| Question | Answer | Status |
|---|---|---|
| Does anyone already check "agent said X, records say Y"? | Probably partly. Production observability tools track function-call failures [6], and Roark replays failed calls [5]. We found **no source** describing a check of spoken claims against the business's own booking records. Absence in a web search is not proof of absence. | Hypothesis |
| Is ours unique? | **No claim of uniqueness.** Several tools detect related failures. | Decision |
| What's different about ours? | It's deterministic and free, runs offline on logs the builder already has, needs no simulation minutes or API key, and every finding cites the records row. | Design intent, unproven |
| Why could it lose? | Builders may already be fine with a $30/month simulator. Simulators can add a records assertion. Builders may not have exportable records. Heuristic claim detection may be too noisy. | Risks to test |
| Who might want it? | Solo builders and small agencies running action-taking agents for SMBs, especially at zero budget. **Today only the founder.** | Hypothesis; demand test in PRODUCT.md |

## 5. Sources

Search date 2026-10-14. Labels as in "How to read this".

1. Cekura, "5 Best Voice Agent Testing Platforms (2026)". https://www.cekura.ai/discover/voice-agent-testing-platforms (Vendor)
2. Cekura, "9 Best AI Voice Testing Platforms in 2026". https://www.cekura.ai/blogs/best-ai-voice-testing-platforms (Vendor)
3. Cekura home page. https://www.cekura.ai/ (Vendor). The $30/month developer plan figure came from the 2026-10-14 search summary of the observability/pricing sources; confirm it on Cekura's pricing page before use.
4. Bluejay, "Top Voice AI Testing Platforms for 2026". https://resources.getbluejay.ai/blog/listicle/top-voice-ai-testing-platforms-2026-7d4577 (Vendor)
5. Speechmatics, "De-risk your voice agent: The 11 best voice agent testing platforms in 2026". https://www.speechmatics.com/company/articles-and-news/de-risk-your-voice-agent-11-best-voice-agent-testing-platforms (Vendor); also Confident AI. https://www.confident-ai.com/knowledge-base/compare/best-voice-ai-evaluation-and-observability-tools-2026 (Vendor)
6. Cekura, "7 AI Voice Agent Testing Tools: What Passed and What Failed". https://www.cekura.ai/blogs/ai-voice-agent-testing-tools (Vendor)
7. VoiceRun, "9 Best Voice Observability Platforms For Production Agents In 2026". https://voicerun.com/announcements/best-voice-observability/ (Vendor)
8. Arize, "14 best AI agent observability tools in 2026". https://arize.com/blog/best-ai-observability-tools-for-autonomous-agents-in-2026/ (Vendor)
9. Egma, via Voice AI Space listing. https://www.voiceaispace.com/knowledge/repo/0d3a7395-bb40-451c-97ae-c38211c846fa (Listing)
10. simulate-sdk, Enterprise DNA directory. https://enterprisedna.co/directories/open-source/simulate-sdk (Listing)
11. EVA-Bench, arXiv 2605.13841 (May 2026). https://huggingface.co/papers/2605.13841 (Paper, preprint)
12. Open, "AI receptionist India". https://www.open.cx/voice/ai-receptionist-india (Vendor)
13. Edesy, Hyderabad AI receptionist. https://edesy.in/ai-receptionist/in/hyderabad (Vendor)
14. Indie Hackers, "Built an AI voice receptionist for my dad's dental clinic". https://www.indiehackers.com/post/built-an-ai-voice-receptionist-for-my-dads-dental-clinic-40-more-bookings-80e2c4a830 (Anecdote)
15. CareVoice AI. https://carevoice.duckdns.org/ (Vendor, unverified domain)
16. SoftwareSeni, "When Voice Agents Go Wrong". https://www.softwareseni.com/when-voice-agents-go-wrong-production-failure-modes-and-how-to-prevent-them/ (Vendor)
17. GrowwStacks, reliable voice agent lead generation. https://growwstacks.com/blog/how-to-build-reliable-voice-agent-lead-generation (Vendor)
18. Future AGI customer case. https://futureagi.com/customers/voice-agent-quality/ (Vendor)
19. Suprmind, "Voice AI hallucinations". https://suprmind.ai/hub/insights/voice-ai-hallucinations.md (Vendor); SignalWire, "Why voice AI fails". https://signalwire.com/blogs/developers/why-voice-ai-fails (Vendor)

## 6. What would change this analysis

- **A builder's own words.** Any builder in the Assignment who names a tool they already use for this would rewrite §4.
- **Hands-on trials.** A trial of Cekura's or LangWatch's free tier showing they already check claims against records would mean we compete on price and offline use only. That would be weaker.
- **Primary sources.** The tribunal decision for the Air Canada case, and vendors' own pricing pages.
