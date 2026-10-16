"""bench.py — measure VoxAgent's hot paths. No network, no API quota used.

    .venv\\Scripts\\python bench.py

Run it after touching agent.py, storage.py, auth.py or llm.py. These are the
paths that sit between a caller speaking and the agent answering, so a
regression here is a regression the customer hears.

The numbers that mattered when this was written (median, this laptop):

    path                              before    after
    genai client per conversation     780 ms    0 ms   (shared, built at boot)
    building an agent                 786 ms    0.2 ms
    auth check per API request       0.77 ms    0 ms   (cached)
    client config (YAML parse)       5.72 ms    0.03 ms
    whole dashboard refresh         26.75 ms    1.9 ms
"""

import datetime as dt
import statistics
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import auth  # noqa: E402
import billing  # noqa: E402
import scheduling  # noqa: E402
import storage  # noqa: E402
import telephony  # noqa: E402
from agent import TOOL_SCHEMAS, ReceptionistAgent  # noqa: E402

CLIENT = "demo_clinic"


class FakeLLM:
    """Keeps the benchmark offline: we measure our code, not Google's."""

    def send(self, messages, tools=None):
        return {"text": "ok", "tool_calls": []}


def bench(label, fn, n=30, warmup=3):
    for _ in range(warmup):
        fn()
    times = []
    for _ in range(n):
        t0 = time.perf_counter()
        fn()
        times.append((time.perf_counter() - t0) * 1000)
    median = statistics.median(times)
    p95 = sorted(times)[max(0, int(n * 0.95) - 1)]
    print(f"  {label:<46} {median:8.2f} ms   (p95 {p95:7.2f})")
    return median


def main():
    print("\n=== VoxAgent hot paths ===\n")

    token = auth.issue_token(auth.os.getenv("ADMIN_EMAIL", "bench@local"))["token"] \
        if auth.os.getenv("ADMIN_EMAIL") else None

    if token:
        bench("auth check (every API request)", lambda: auth.user_for_token(token), n=50)

    bench("build an agent (every call / session)",
          lambda: ReceptionistAgent(CLIENT, llm=FakeLLM()))
    bench("client config", lambda: storage.read_client_config(CLIENT))
    bench("call logs", lambda: storage.read_call_logs(CLIENT))
    bench("bookings", lambda: storage.read_bookings(CLIENT))
    bench("billing status", lambda: billing.status(CLIENT))
    bench("phone routing (every inbound call)",
          lambda: telephony.resolve_client("+16592517349"))
    bench("availability for the whole window",
          lambda: scheduling.available_slots(storage.read_client_config(CLIENT),
                                             storage.booked_pairs(CLIENT)))

    def dashboard():
        calls = storage.read_call_logs(CLIENT)
        bookings = storage.read_bookings(CLIENT)
        leads = storage.read_leads(CLIENT)
        billing.status(CLIENT)
        return len(calls) + len(bookings) + len(leads)

    total = bench("whole dashboard refresh", dashboard, n=25)

    # Tool calls and call logging, as every channel now does them. The call
    # log + trace is rewritten after EVERY web-test turn, so it is on the
    # /api/chat path; budget 5 ms (eng review). Written to a temp folder:
    # a benchmark must never touch the business's real call records.
    agent = ReceptionistAgent(CLIENT, llm=FakeLLM())
    day = next(d for d, s in sorted(agent.slots.items()) if s)
    call = {"name": "check_availability", "args": {"date": day}}
    bench("run one tool (every tool call)", lambda: agent.run_tool(call))
    agent.history = [{"role": "user", "text": "any slots?", "at": agent.now()},
                     agent.tool_call_entry([call]), agent.run_tool(call),
                     {"role": "assistant", "text": "Yes.", "at": agent.now()}]
    real_calls_dir = storage.CALLS_DIR
    with tempfile.TemporaryDirectory() as tmp:
        storage.CALLS_DIR = Path(tmp)
        try:
            bench("log a call + trace (every web-test turn)",
                  lambda: storage.log_call_from_agent(agent, "bench", dt.datetime.now(),
                                                      call_id="bench"))
        finally:
            storage.CALLS_DIR = real_calls_dir
    print(f"\n  tool schemas offered per turn: {len(TOOL_SCHEMAS)}")
    print(f"  dashboard server work: {total:.2f} ms\n")


if __name__ == "__main__":
    main()
