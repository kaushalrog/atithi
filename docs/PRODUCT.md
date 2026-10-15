# VoxAgent product direction (Phase 1)

**Date:** 2026-10-14. **Status:** direction approved by the founder via `/office-hours`. A `/plan-ceo-review` follows.
**Full design:** `docs/designs/claim-vs-records-checker.md`. **Market:** `docs/COMPETITIVE_ANALYSIS.md`. **Measures:** `docs/METRICS.md`.

## The one-sentence bet

Action-taking voice agents fail in ways a transcript can't show. The agent **says** "you're booked" while the system **did** something else. A free, offline checker that compares claims with tool results and the business's records will catch failures that scripted evals and transcript reading miss.

## Facts vs hypotheses

| Statement | Status | Evidence |
|---|---|---|
| VoxAgent had 4 client-hurting bugs that lived in system state: double-booking (H2), Sheet bookings invisible to availability (H3), a conversion metric counting failures (M1), and phone calls dropping tool calls (M2). | **Fact** | `docs/AUDIT.md`, reproduced by `docs/audit_repro.py` (R1–R4) |
| The founder's 10 scripted evals plus transcript reading missed all four. | **Fact** | Audit; the evals were in place when the bugs were found |
| Three of the four (R1, R2, R4) are detectable from one call's trace plus the records. R3 is not. | **Design claim**, to be proven on fixtures | Design doc, Success Criteria |
| Other builders hit the same failure class. | **Hypothesis** | Vendor-only evidence (COMPETITIVE_ANALYSIS §3) |
| Other builders would use a free checker for it. | **Hypothesis**, the main risk | **No outside evidence.** Only the founder's pain |
| No existing tool does exactly this. | **Unverified.** Not claimed | A web search found none, which proves nothing |

## User

- **First user:** a solo builder or small agency running voice agents that **take actions** (book, reschedule, record leads) for small businesses such as clinics and salons. They get blamed when the agent misleads a customer.
- **Named instances today:** one, the founder. Finding person #2 is the first job, before platform work.

## What we build first (MVP)

A command-line checker, run as `python -m <module> check trace.json --records bookings.csv`. It works like this:
1. It validates a call trace in a neutral JSON format: turns, actions with a normalised type and success flag, timestamps and timezone.
2. It runs **6 checks**:
   - record mismatch
   - slot not available (2a exact, 2b heuristic)
   - double booking
   - claim without action
   - spoken time differs
   - incomplete task

   Each check is labelled exact or heuristic, and each finding cites the transcript line, the action and the record row.
3. It prints findings and a task outcome. It saves a run as JSON and writes one static, escaped HTML report.
4. `compare` diffs two runs.
5. Fixtures run in CI with no API key.

**Step zero:** VoxAgent emits a structured per-call event log. This fixes audit gap M2 and gives the checker real traces. Events are appended in memory and written once at call end, so the caller hears no added latency.

## Measurable MVP outcome

All targets, none of them results yet. Definitions are in `docs/METRICS.md`.
- **Recall:** ≥ 90% of injected faults across ≥ 10 single-fault traces, with every MVP check catching its own.
- **False positives:** ≤ 1 across ≥ 20 clean traces.
- **Cost:** $0 to run the checks and the tests.
- **Onboarding:** ≤ 10 minutes from `git clone` to a report on the sample case.
- **Demand:** at least 1 outside builder runs it on their own logs within the run window after the day-10 checkpoint. There is an explicit kill rule (below).

## Demand test and kill rule

1. **Day 1:** send one question to at least 10 builders (all contacted by day 3):

   > "In the last month, did your agent tell a caller something was booked or done that wasn't? How did you find out?"

2. **Day 10:** apply the checkpoint, in order:
   1. **Under 5 substantive replies:** 7 more days of outreach only, then one re-check. Still under 5 means **kill**.
   2. **0 report the failure:** **kill or rethink.** Stop building and re-run office hours.
   3. **Pain reported, and a builder runs it within 4 days:** **success.**
   4. **Pain, but no run:** fix the stated blocker and allow one more 7-day window, then re-run office hours on the wedge.

## Non-goals (MVP)

- Live telephony work, real calls, or contacting real people automatically.
- Multilingual claim detection. The MVP is English-only; Telugu and Hindi are a known limitation.
- Synthetic-caller simulation (voice or LLM). Hand-written fault traces are test fixtures, not simulated callers.
- An LLM judge as ground truth. It's optional and labelled, and deferred anyway.
- A dashboard, hosted service, accounts, or a side-by-side comparison page.
- Checks 7–9 (prices, repeated questions, corrections). They come after demand is validated.
- Outside-platform adapters before a builder names their platform.
- Claims of uniqueness.

## What happens to the receptionist

It stays, unchanged in behaviour, and becomes the **testbed**. It's the first source of real traces, and the place the event log and checks prove themselves. The receptionist roadmap (Stage 4 multilingual voices, outbound campaigns) is paused until the demand checkpoint, unless the founder decides otherwise. Why: a solo builder can't run two products, and the checkpoint decides which one gets the time.

## Open decisions for the founder

1. **GitHub remote by day 7.** This is needed for CI and for sharing. It's a founder action; I won't create it.
2. **Outreach.** The founder sends the Assignment messages. I don't contact anyone.
3. **The receptionist pause** above. Confirm it or override it in `/plan-ceo-review`.
