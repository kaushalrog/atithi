# Review round — 2026-10-25

Five parallel reviews of Atithi: two on the market, three on the product.
Full reports are in this folder. This page is the part you act on.

| Report | What it covers |
|---|---|
| [competitors-india.md](competitors-india.md) | 10 direct Indian rivals, table stakes, pricing, the distribution threat |
| [competitors-global.md](competitors-global.md) | Global platform baseline, pricing, latency reality, S2S vs cascaded |
| [capability-matrix.md](capability-matrix.md) | What our code actually does vs Outpero, line by line, plus doc overclaims |
| [security-audit.md](security-audit.md) | 2 Critical, 5 High, 11 Medium, 7 Low |
| [customer-readiness.md](customer-readiness.md) | 8 blockers between here and a clinic owner using it |

Everything is cited to a file:line or a dated source. Vendor marketing is
labelled as such — treat it as weak evidence.

---

## Already fixed in this round

- **Critical — a live credential was in git.** `access_key: VX-84KQ2N` was
  committed in `clients/demo_clinic.yaml` and printed in `README.md`. That
  tenant owns a real Twilio number, is the fallback for unmapped inbound
  calls, and has no `billing:` block, so the code never expired — and it was
  accepted for **writes**. Both codes are rotated, the literal is out of the
  README, and tests now read the code from config instead of hardcoding it.
- **Critical — password reset was a platform takeover path.** No role check
  plus a 24-bit code plus no throttle meant a stranger could reset the *admin*
  account, which can read every business and place calls. Admin accounts can
  no longer be reset at all; codes are now 128-bit.
- **Critical overclaim — the latency number.** `docs/STRATEGY.md` claimed
  "~0.1–0.5s on a real call". That was wrong. It came from `bench_load.py`,
  which drives **fake** providers with a hardcoded 250 ms sleep and whose own
  header says never to quote it as call latency. Corrected.
- **The README promised Indian neural voices on the phone.** It does not
  happen: a call uses one Gemini prebuilt voice. Corrected, and the unwired
  routing policy in `voices.py` is now marked as not-yet-wired.

---

## The three things that change the plan

**1. Outpero is not the competition — there are at least ten, and one is
Reliance.** Direct rivals already selling to Indian clinics: ConnectAI
(₹800/mo + ₹4/min), Pluxo, VaniAgent, CallMissed, HuskyVoice, Vyora (₹799/mo),
Tabbly (₹4.5/min), Bolti, and Outpero — which also has an inbound product, so
the overlap is bigger than we assumed. The dangerous one is **Jio Haptik**,
selling SMB agents at ₹3–5 per conversation through **Interakt's 50,000+ SMB
base**. We cannot win a distribution fight with Reliance. We win on depth in
a vertical they will not tune for.

**2. Our latency advantage probably does not exist.** Independent 2026
benchmarks put every platform at 1.3–3.1s voice-to-voice and measured
**Gemini Live itself at ~3.05s**. Meanwhile Indian rivals advertise sub-300ms
(Gnani <200ms, Bolna/Tabbly <300ms). Before anyone quotes a number, measure
utterance-end → audible-at-handset, p50 and p95, over 100+ real calls.

**3. The proof check is still genuinely ours — but say it carefully.** No
vendor sells pre-speech verification of a spoken claim against the record.
ElevenLabs Guardrails blocks pre-speech but explicitly does not check facts;
Hamming names our exact failure mode in print but detects it *post-call*.
Drop any absolute "cannot lie" phrasing (the market reads "zero
hallucinations" as a red flag). Say: *"a confirmation is only spoken after the
booking exists."* Demo the failure path, not the happy path.

---

## What to do next, in order

**Before a pilot — security (from `security-audit.md`):**
1. Per-IP and per-email rate limits on `/api/auth/login`, `/api/auth/reset`,
   `/api/portal/login` and the admin key. Already a P2 TODO; it is P0.
2. Make business codes read-only — require a bearer token for `PUT settings`,
   cancel, questions and leads endpoints.
3. Stop trusting caller ID as identity: it is spoofable, it is concatenated
   into the **system** prompt, and `memory.py` now volunteers a named
   customer's appointments on it alone. Gate memory behind something the
   caller proves.
4. Restrict who the platform may dial — a spoofed international caller ID
   turns missed-call callbacks into dialling an attacker's premium number.
5. Make `billing._is_active` fail **closed** for a config with no billing
   block, so no tenant is ever permanently free.

**Highest value per unit of work (from `capability-matrix.md`):**
1. **Wire `plans.py` in — four call sites.** It is written and tested and not
   imported anywhere. It unblocks margin safety, free-credit signup, and
   selling concurrency as channels all at once.
2. **Call recordings + playback.** Table stakes; the audio already passes
   through one class. Pair it with the DPDP delete path.
3. **One post-call extraction pass** → intent / budget / requirement /
   next_step / sentiment, on the existing background queue. This is what turns
   the dashboard from a log into something worth a monthly fee.
4. **Per-business post-call webhook** — ~30 lines, converts "we don't
   integrate" into "we post the call to your system".
5. **Fix the Telugu/Tamil phone voice.** Ranked fifth only on effort; it is
   the one gap a customer hears in the first sentence.

**Non-negotiable table stakes we lack (from `competitors-india.md`):**
WhatsApp is **not optional** in India — every direct rival has it, one is
WhatsApp-first. Mid-sentence code-mixed language switching is now an
expectation, not a feature.

**Before a Telugu pilot specifically:** the phone voice fix above is a
blocker, not a nice-to-have.

---

## Open questions these reviews did not settle

1. Does the voxcheck bet in `PRODUCT.md` stay paused? These reviews assume the
   receptionist is the business and the proof check is its weapon.
2. Who owns selling? Two engineers both building is why there are zero
   customers at 110+ commits.
3. Which vertical first — dental, diagnostics, or multi-speciality?
4. Do we fight on price (rivals are at ₹799–800/mo and ₹4–4.5/min) or on
   verified-and-safe at a premium? Pricing in `docs/STRATEGY.md` §5 assumed
   only Outpero; it needs redoing against this set.
