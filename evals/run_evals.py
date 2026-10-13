"""Conversation-quality evals — the quality gate before any demo or deploy.

tests/ proves the plumbing works; THIS proves the agent behaves: doesn't invent
prices, books only real slots after confirmation, captures leads, answers Telugu
in Telugu, and never breaks character. Run it after any prompt/model change:

    .venv\\Scripts\\python evals\\run_evals.py

Uses the real Gemini API (~30 requests; a few minutes on the free tier).
Storage is redirected to a scratch folder, so real bookings/leads are untouched.
Note: LLM output varies — one flaky failure means "read the transcript",
repeated failure means "fix the prompt". This is a thermometer, not a unit test.
"""

import datetime as dt
import json
import re
import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import scheduling  # noqa: E402
import storage  # noqa: E402
from agent import ReceptionistAgent  # noqa: E402
from llm import QuotaExhausted  # noqa: E402


def build_context(client_id: str = "demo_clinic") -> dict:
    """Resolve the {placeholders} scenarios use for dates and times.

    Scenarios used to name a literal date ("9th July"). It went stale, and the
    suite then measured nothing about booking. Asking the live schedule for a
    genuinely open day keeps every run meaningful.
    """
    config = storage.read_client_config(client_id) or {}
    slots = scheduling.available_slots(config, set())
    today = dt.date.today().isoformat()
    for date in sorted(slots):
        if date > today and "16:00" in slots[date]:
            day = dt.date.fromisoformat(date)
            return {
                "date_iso": date,
                "date_spoken": f"{day.strftime('%A')} {day.day} {day.strftime('%B')}",
                "open_time_spoken": "4 PM",
                "open_time_24": "16:00",
                "closed_time_spoken": "2 PM",   # between the morning and evening ranges
            }
    raise SystemExit(f"{client_id} has no open day with a 16:00 slot — check its schedule")


def fill(value, context: dict):
    """Substitute {placeholders} through a scenario's strings."""
    if isinstance(value, str):
        return value.format(**context)
    if isinstance(value, list):
        return [fill(v, context) for v in value]
    if isinstance(value, dict):
        return {k: fill(v, context) for k, v in value.items()}
    return value

TELUGU = re.compile(r"[ఀ-౿]")

# No reply, in any scenario, may ever contain these.
GLOBAL_FORBIDDEN = ["language model", "as an ai", "i am an ai", "i'm an ai", "chatbot"]


def run_scenario(scenario: dict, workdir: Path) -> tuple[list, list]:
    # Fresh, isolated storage per scenario so counts are deterministic.
    sdir = workdir / scenario["name"]
    sdir.mkdir(parents=True, exist_ok=True)
    storage.BOOKINGS_CSV = sdir / "bookings.csv"
    storage.LEADS_CSV = sdir / "leads.csv"
    storage.CALLS_DIR = sdir / "calls"
    storage.clear_caches()   # each scenario starts from clean, isolated data

    agent = ReceptionistAgent(scenario.get("client", "demo_clinic"))
    replies = [agent.chat(turn) for turn in scenario["turns"]]
    tools_used = [
        call["name"]
        for msg in agent.history
        if msg["role"] == "assistant"
        for call in (msg.get("tool_calls") or [])
    ]
    return evaluate(scenario.get("checks", {}), replies, tools_used, agent), replies


def evaluate(checks: dict, replies: list[str], tools_used: list[str], agent) -> list:
    joined = "\n".join(replies).lower()
    results = []

    def check(name, ok, detail=""):
        results.append({"check": name, "ok": bool(ok), "detail": detail})

    for name, arg in checks.items():
        if name == "reply_contains_any":
            check(name, any(a.lower() in joined for a in arg), f"wanted one of {arg}")
        elif name == "reply_not_contains":
            found = [a for a in arg if a.lower() in joined]
            check(name, not found, f"found {found}" if found else "")
        elif name == "tools_called":
            missing = [t for t in arg if t not in tools_used]
            check(name, not missing, f"missing {missing}, used {tools_used}" if missing else "")
        elif name == "tools_not_called":
            wrongly = [t for t in arg if t in tools_used]
            check(name, not wrongly, f"called {wrongly}" if wrongly else "")
        elif name == "bookings":
            rows = storage.read_bookings(agent.client_id)
            check(name, len(rows) == arg, f"expected {arg}, got {len(rows)}")
        elif name == "booking_time":
            rows = storage.read_bookings(agent.client_id)
            times = [r["time"] for r in rows]
            check(name, arg in times, f"expected {arg}, got {times}")
        elif name == "leads":
            rows = storage.read_leads(agent.client_id)
            check(name, len(rows) == arg, f"expected {arg}, got {len(rows)}")
        elif name == "reply_in_telugu":
            check(name, bool(TELUGU.search(replies[-1])) == arg, f"last reply: {replies[-1][:80]}")
        else:
            check(name, False, "unknown check type")

    forbidden = [p for p in GLOBAL_FORBIDDEN if p in joined]
    check("never_breaks_character", not forbidden, f"said {forbidden}" if forbidden else "")
    return results


def main():
    scenarios = yaml.safe_load((ROOT / "evals" / "scenarios.yaml").read_text(encoding="utf-8"))
    context = build_context()
    scenarios = [fill(s, context) for s in scenarios]
    print(f"\n(booking scenarios target {context['date_spoken']} at "
          f"{context['open_time_spoken']})")
    # Targeted rerun (saves scarce free-tier quota):
    #   python evals\run_evals.py booking_happy_path telugu_customer
    if len(sys.argv) > 1:
        wanted = set(sys.argv[1:])
        scenarios = [s for s in scenarios if s["name"] in wanted]
    workdir = Path(tempfile.mkdtemp(prefix="voxagent_evals_"))
    report = {"ran_at": dt.datetime.now().isoformat(timespec="seconds"), "scenarios": []}
    passed_scenarios = 0

    print(f"\nVoxAgent conversation evals — {len(scenarios)} scenarios\n" + "=" * 60)
    for scenario in scenarios:
        try:
            results, replies = run_scenario(scenario, workdir)
        except QuotaExhausted:
            print("ABORTED: the API key's DAILY free-tier quota is exhausted.")
            print("Upgrade to the paid tier (ai.google.dev -> billing) or rerun tomorrow;")
            print("finished scenarios above are still valid.")
            break
        except Exception as e:
            results = [{"check": "scenario_crashed", "ok": False, "detail": f"{type(e).__name__}: {e}"}]
            replies = []
        ok = all(r["ok"] for r in results)
        passed_scenarios += ok
        print(f"{'PASS' if ok else 'FAIL':4}  {scenario['name']}")
        for r in results:
            if not r["ok"]:
                print(f"      ✗ {r['check']}: {r['detail']}")
        if not ok and replies:
            print(f"      agent said: {replies[-1][:150]!r}")
        report["scenarios"].append(
            {"name": scenario["name"], "passed": ok, "checks": results, "replies": replies}
        )

    print("=" * 60)
    print(f"RESULT: {passed_scenarios}/{len(scenarios)} scenarios passed")
    out_dir = ROOT / "evals" / "results"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / f"{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Full report: {out_path}")
    sys.exit(0 if passed_scenarios == len(scenarios) else 1)


if __name__ == "__main__":
    main()
