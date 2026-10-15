# Metrics

**Date:** 2026-10-14. Every number below is a **target** unless it has a "measured" date and a command. Nothing is measured yet for the checker, because it doesn't exist yet.

## 1. Checker quality (measured on fixtures, offline, $0)

| Metric | Definition | Target | How measured |
|---|---|---|---|
| Recall | Injected faults detected ÷ injected faults. Each fault trace carries one labelled fault and its expected check. | ≥ 90% overall, and every MVP check detects at least one of its own faults | pytest over `fixtures/faults/*.json`; the run reports per-check counts |
| False positives | Findings on traces that contain no fault. `unverifiable` and `ambiguous` results are listed but are not findings. | ≤ 1 across ≥ 20 clean traces | pytest over `fixtures/clean/*.json` |
| Input handling | A malformed trace is rejected with a clear error. The adversarial trace's instructions are not followed, and its HTML renders inertly. | All pass | pytest (pass/fail, not part of recall) |
| Heuristic share | The share of findings from heuristic checks (2b, 4, 5) vs exact checks | Reported, no target | Run summary. Watch it on real logs: a high heuristic share means a noisy checker |
| Run cost | API spend to run the checks and tests | $0 | No network calls in the check path; tests run with no key |
| Time to first report | `git clone` → report on the sample trace, following README steps | ≤ 10 min | Timed by the founder on a clean machine before outreach |

**Fault fixture plan** (minimum, from the design doc):

| Fault | Check that must catch it |
|---|---|
| R1 double booking | 3 |
| R2 booking on an already-confirmed slot | 2a |
| R4 confirmed booking with no logged action | 4 |
| Tool success but record missing | 1 |
| Spoken time contradicts the booking | 5 |
| Incomplete task | 6 |
| Missing required field | 6 |
| 3 more variants | one each for checks 1, 4 and 5 |

## 2. Demand (the real test)

| Metric | Definition | Target / rule |
|---|---|---|
| Builders contacted | Distinct builders sent the Assignment question | ≥ 10 by day 3 |
| Substantive replies | Replies that answer the question, not "cool" or "interesting" | ≥ 5 by day 10 |
| Pain reports | Substantive replies describing a claim-vs-records failure in the last month | ≥ 1, else kill or rethink |
| Outside runs | Builders who ran the checker on their own logs | ≥ 1 within the run window, which means success |

Record exact words in a private notes file outside the repo. Never commit builders' data (see the personal-data rules in the design doc).

## 3. Receptionist metrics to fix (audit M1, M2)

The portal's headline numbers are currently wrong for phone calls. Both bugs reproduce on the hardened branch (`python docs/audit_repro.py`: R3, R4).

| Metric | Today | After the event log |
|---|---|---|
| Call → booking conversion | A substring `book_appointment` in the transcript, so failed attempts count. Measured: 1 call, 0 bookings, 100%. | The share of calls with task outcome `booked` (a successful book action with a matched record) |
| Turn count | A phone call's caller-id line is counted as a user turn | Caller and agent turns from the trace only |
| Tool evidence on phone/live calls | Missing (M2) | Every action logged with type, args, ok and result |

The event log **enables** these fixes. The dashboard change itself is a separate, scheduled task in the Phase 2 plan.

## 4. Guardrails that must not regress

| Metric | Current | Rule | Command |
|---|---|---|---|
| Hot-path latency | `bench.py` with 300 bookings: build agent 0.09 ms, availability 0.09 ms, dashboard 0.25 ms (measured 2026-10-14, commit `2d432c1`) | Event-log append adds no disk I/O on the caller-to-answer path. bench.py gains an append measurement | `python bench.py` |
| Test suite | 152 passed (measured 2026-10-14, Python 3.13 and 3.11) | Stays green | `python -m pytest tests -q` |
| Real data writes in tests | Guarded (`VOXAGENT_ENV=test` raises) | Checker tests use temp dirs and synthetic fixtures only | pytest |

## 5. Unit economics (CLAUDE.md priority 3)

Not measured. The checker is $0 by design. Per-conversation cost of the receptionist (Gemini tokens and minutes, Twilio minutes) is still unknown and still needed before pricing. The event log should record token and minute counts per call when the provider exposes them, so this becomes measurable. That's a Phase 2 item, not MVP.
