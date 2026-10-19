"""bench_load.py — offline load and failure-injection benchmark.

    python bench_load.py                 # quick suite, prints a table
    python bench_load.py --suite full    # every scenario at 1/2/5/10 sessions
    python bench_load.py --suite full --out results.json
    python bench_load.py --scenario phone_book --sessions 5    # one scenario

WHAT IT MEASURES. The real VoxAgent code (ReceptionistAgent, TwilioBridge,
TurnRecorder, server.chat, storage, scheduling) driven by FAKE providers: a
scripted model for the text/web channel and a simulated Gemini Live session
for phone calls. Model "thinking time" is a fixed, known sleep, so anything
above it is VoxAgent's own overhead or a stall it caused. These numbers say
nothing about real Gemini/Twilio/Google latency. Never quote them as call
latency.

SAFETY. Every storage path is redirected to a fresh temp folder BEFORE the
app modules are imported, test mode is on (any write to a real data file
raises), and the run refuses to start if a path still points into the repo.
No network, no API key, no real calls. Each scenario runs in its own
subprocess so CPU and peak-memory numbers are per scenario.
"""

import argparse
import asyncio
import base64
import datetime as dt
import json
import os
import platform
import resource
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent

# ---- isolation: must happen before importing anything that touches storage --------
os.environ["VOXAGENT_ENV"] = "test"
os.environ["SHEET_ID"] = ""
os.environ.setdefault("GEMINI_API_KEY", "offline-benchmark-no-network")
sys.path.insert(0, str(REPO))
_TMP = Path(tempfile.mkdtemp(prefix="voxagent_bench_load_"))

import storage  # noqa: E402

storage.BOOKINGS_DB = _TMP / "bookings.db"
storage.BOOKINGS_CSV = _TMP / "bookings.csv"
storage.LEADS_CSV = _TMP / "leads.csv"
storage.CALLS_DIR = _TMP / "calls"
storage.clear_caches()
for _p in (storage.BOOKINGS_DB, storage.BOOKINGS_CSV, storage.LEADS_CSV, storage.CALLS_DIR):
    if REPO in _p.resolve().parents and _TMP not in _p.resolve().parents:
        raise SystemExit(f"refusing to run: {_p} points into the repository")

import scheduling  # noqa: E402
from agent import ReceptionistAgent  # noqa: E402
from telephony import TwilioBridge  # noqa: E402

CLIENT = "demo_clinic"
MULAW_20MS = base64.b64encode(b"\xff" * 160).decode()      # 20 ms of 8 kHz silence
PCM_20MS_24K = b"\x00\x00" * 480                             # 20 ms of 24 kHz PCM


# ---- small helpers ----------------------------------------------------------------

def pct(values, q):
    """q-th percentile (0-100) by nearest rank; None for no data."""
    if not values:
        return None
    ordered = sorted(values)
    k = max(0, min(len(ordered) - 1, round(q / 100 * (len(ordered) - 1))))
    return ordered[k]


def summary(values, scale=1000.0):
    """p50/p95/p99/max in milliseconds (values in seconds)."""
    if not values:
        return {"n": 0}
    return {"n": len(values), "p50": round(pct(values, 50) * scale, 2),
            "p95": round(pct(values, 95) * scale, 2), "p99": round(pct(values, 99) * scale, 2),
            "max": round(max(values) * scale, 2)}


def open_slots(count):
    """`count` distinct (date, time) slots that are free in the temp database."""
    config = storage.read_client_config(CLIENT)
    slots = scheduling.available_slots(config, storage.booked_pairs(CLIENT))
    out = [(d, t) for d in sorted(slots) for t in slots[d]]
    if len(out) < count:
        raise SystemExit(f"demo_clinic only has {len(out)} open slots; need {count}")
    return out[:count]


def peak_rss_mb():
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return round(rss / (1024 * 1024) if platform.system() == "Darwin" else rss / 1024, 1)


# ---- failure injection ------------------------------------------------------------

class FakeWorksheet:
    """Stands in for a gspread worksheet: append_row takes `delay` seconds
    (a slow or stalled Google API) or raises."""

    def __init__(self, delay=0.0, fail=False):
        self.delay, self.fail, self.rows = delay, fail, 0

    def append_row(self, row):
        time.sleep(self.delay)
        if self.fail:
            raise ConnectionError("Sheets API unavailable (injected)")
        self.rows += 1


def inject(kind):
    """Apply one failure mode. Returns a cleanup function."""
    undo = []
    if kind in ("sheets_slow", "sheets_stall", "sheets_down"):
        delay = {"sheets_slow": 1.0, "sheets_stall": 8.0, "sheets_down": 0.0}[kind]
        sheet = FakeWorksheet(delay=delay, fail=(kind == "sheets_down"))
        real_target, real_handle = storage._sheets_target, storage._sheet_handle
        storage._sheets_target = lambda quiet=False: ("fake-creds.json", "fake-sheet")
        storage._sheet_handle = lambda *a: sheet
        undo.append(lambda: (setattr(storage, "_sheets_target", real_target),
                             setattr(storage, "_sheet_handle", real_handle)))
    elif kind == "slow_db":
        # Something else (another process, an export, a slow disk) holds the
        # database write lock 450 ms out of every 500 ms, so a booking almost
        # always has to wait for it (as it would behind a long write).
        stop = threading.Event()

        def holder():
            import sqlite3
            conn = sqlite3.connect(storage.BOOKINGS_DB, timeout=10, isolation_level=None)
            while not stop.is_set():
                conn.execute("BEGIN IMMEDIATE")
                time.sleep(0.45)
                conn.execute("COMMIT")
                time.sleep(0.05)
            conn.close()
        storage._bookings_db()        # create the schema before the holder starts
        threading.Thread(target=holder, daemon=True).start()
        undo.append(stop.set)
    return lambda: [u() for u in undo]


# ---- the simulated phone call -----------------------------------------------------

class SimLive:
    """A scripted Gemini Live session. Per turn: the caller speaks for
    `speak_s`, the model optionally calls a tool and WAITS for its result,
    "thinks" for `model_s` (a fixed sleep), then streams `audio_chunks` 20 ms
    audio chunks paced in real time. Marks when the caller stopped speaking so
    the harness can measure time to first audio."""

    def __init__(self, turns, model_s, marks, drop_at=None, interrupt=False):
        self.turns, self.model_s, self.marks = turns, model_s, marks
        self.drop_at, self.interrupt = drop_at, interrupt
        self.results = asyncio.Queue()

    async def send_audio(self, chunk):
        pass

    async def send_text(self, text):
        pass

    async def send_tool_results(self, results):
        self.results.put_nowait(results)

    async def close(self):
        pass

    async def events(self):
        for i, turn in enumerate(self.turns):
            await asyncio.sleep(turn["speak_s"])
            yield {"type": "user_text", "text": turn["say"]}
            if self.drop_at == i:
                raise ConnectionError("Live session dropped (injected)")
            self.marks.append(("speech_end", time.perf_counter()))
            if turn.get("tool"):
                yield {"type": "tool_calls", "calls": [dict(turn["tool"], id=f"t{i}")]}
                await self.results.get()
            await asyncio.sleep(self.model_s)
            for k in range(turn["audio_chunks"]):
                yield {"type": "audio", "data": PCM_20MS_24K}
                if self.interrupt and k == 2:
                    yield {"type": "interrupted"}
                    break
                await asyncio.sleep(0.02)
            yield {"type": "agent_text", "text": turn["reply"]}
            yield {"type": "turn_complete"}
        self.marks.append(("script_done", time.perf_counter()))


async def loop_lag_monitor(samples, stop, period=0.01):
    """How late the event loop wakes a 10 ms timer: the stall every live call
    on this process feels at that moment."""
    while not stop.is_set():
        t0 = time.perf_counter()
        await asyncio.sleep(period)
        samples.append(max(0.0, time.perf_counter() - t0 - period))


async def one_call(n, turns, model_s, result, drop_at=None, interrupt=False, patience_s=3.0):
    """One phone call, wired like telephony.twilio_stream: a 20 ms inbound
    media feeder (read_twilio) plus the Gemini pump task, then finish() on a
    worker thread. The call ends when EITHER side does (twilio_stream waits
    FIRST_COMPLETED): a pump that stops on its own makes our side hang up
    (counted as server_hangups). The simulated caller hangs up after
    `patience_s` of silence while waiting for a reply (silent_hangups).
    Keep this in step with twilio_stream; tests/test_telephony.py drives the
    real handler."""
    agent = ReceptionistAgent(CLIENT, llm=object())
    marks, sent = [], []

    async def send_json(msg):
        if msg.get("event") == "media":
            sent.append(time.perf_counter())

    live = SimLive(turns, model_s, marks, drop_at=drop_at, interrupt=interrupt)
    bridge = TwilioBridge(agent, live, send_json, caller=f"+9198765{n:05d}",
                          call_sid=f"CA{n:032d}")
    await bridge.handle_twilio({"event": "start", "start": {"streamSid": f"MZ{n}"}})
    pump = asyncio.create_task(bridge.pump_gemini())
    lateness, started = [], time.perf_counter()
    k, silent_since, hung_up_silent, server_hung_up = 0, None, False, False
    while True:
        k += 1
        due = started + k * 0.02
        await asyncio.sleep(max(0.0, due - time.perf_counter()))
        lateness.append(max(0.0, time.perf_counter() - due))
        await bridge.handle_twilio({"event": "media", "media": {"payload": MULAW_20MS}})
        if any(m[0] == "script_done" for m in marks):
            break
        if pump.done():                 # the model side ended: our side hangs up now
            server_hung_up = True
            break
        waiting = marks and marks[-1][0] == "speech_end" and (not sent or sent[-1] < marks[-1][1])
        if waiting:
            silent_since = silent_since or time.perf_counter()
            if time.perf_counter() - silent_since > patience_s:
                hung_up_silent = True
                break
        else:
            silent_since = None
    pump.cancel()
    await asyncio.gather(pump, return_exceptions=True)
    t0 = time.perf_counter()
    try:
        await asyncio.to_thread(bridge.finish)
        finish_ok = True
    except Exception:
        finish_ok = False
    result["finish_s"].append(time.perf_counter() - t0)
    result["feeder_lateness_s"].extend(lateness)
    # time to first audio after each caller utterance, minus nothing: the
    # model's scripted think time (model_s) is reported alongside it.
    ends = [t for name, t in marks if name == "speech_end"]
    for i, end in enumerate(ends):
        nxt = ends[i + 1] if i + 1 < len(ends) else float("inf")
        first = next((s for s in sent if end <= s < nxt), None)
        if first is not None:
            result["ttfa_s"].append(first - end)
    # Gaps INSIDE one reply only: the pause between two turns is the caller
    # talking, not a glitch.
    gaps = [b - a for a, b in zip(sent, sent[1:]) if not any(a < e <= b for e in ends)]
    result["audio_gaps_over_60ms"] += sum(1 for g in gaps if g > 0.06)
    result["max_audio_gap_s"].append(max(gaps) if gaps else 0.0)
    result["silent_hangups"] += int(hung_up_silent)
    result["server_hangups"] += int(server_hung_up)
    result["calls_ok"] += int(finish_ok and not hung_up_silent and not server_hung_up)


def phone_script(kind, slots, n_turns):
    turns = []
    for i in range(n_turns):
        tool = None
        if kind == "avail":
            tool = {"name": "check_availability", "args": {"date": slots[0][0]}}
        elif kind == "book" and i == n_turns - 1:
            d, t = slots.pop(0)
            tool = {"name": "book_appointment", "args": {
                "customer_name": "Bench", "phone": "9876543210", "service": "Cleaning",
                "date": d, "time": t}}
        turns.append({"speak_s": 0.3, "say": f"caller line {i}", "tool": tool,
                      "audio_chunks": 15, "reply": f"agent reply {i}"})
    return turns


def run_phone(sessions, kind, failure, n_turns=4, model_s=0.25):
    slots = open_slots(sessions + 2)
    undo = inject(failure)
    result = {"ttfa_s": [], "feeder_lateness_s": [], "finish_s": [], "audio_gaps_over_60ms": 0,
              "max_audio_gap_s": [], "silent_hangups": 0, "server_hangups": 0, "calls_ok": 0}
    lag = []

    async def main():
        stop = asyncio.Event()
        monitor = asyncio.create_task(loop_lag_monitor(lag, stop))
        await asyncio.gather(*[
            one_call(n, phone_script(kind, slots, n_turns), model_s, result,
                     drop_at=(1 if failure == "model_drop" else None),
                     interrupt=(failure == "interrupt"))
            for n in range(sessions)])
        stop.set()
        await monitor

    cpu0, t0 = time.process_time(), time.perf_counter()
    asyncio.run(main())
    wall = time.perf_counter() - t0
    undo()
    booked = len([b for b in storage.read_bookings(CLIENT) if b["status"] == "confirmed"])
    return {"model_think_ms": model_s * 1000, "ttfa_ms": summary(result["ttfa_s"]),
            "inbound_frame_lateness_ms": summary(result["feeder_lateness_s"]),
            "event_loop_lag_ms": summary(lag), "finish_ms": summary(result["finish_s"]),
            "audio_gaps_over_60ms": result["audio_gaps_over_60ms"],
            "max_audio_gap_ms": round(max(result["max_audio_gap_s"] or [0]) * 1000, 1),
            "silent_hangups": result["silent_hangups"], "server_hangups": result["server_hangups"],
            "calls_ok": result["calls_ok"],
            "calls": sessions, "bookings_confirmed": booked,
            "turns_per_s": round(sessions * n_turns / wall, 2), "wall_s": round(wall, 2),
            "cpu_s": round(time.process_time() - cpu0, 2)}


# ---- the simulated web test call (portal /api/chat) -----------------------------------

class SleepyLLM:
    """Scripted model: each call takes `model_s` (like a real network round
    trip). `fail_every`: every Nth call raises a timeout instead."""

    def __init__(self, responses, model_s, fail_every=0):
        self.responses, self.model_s, self.fail_every = list(responses), model_s, fail_every
        self.calls, self.lock = 0, threading.Lock()
        self.spent_s = 0.0    # ACTUAL time inside send() (sleep overshoots by ~4 ms on macOS)

    def send(self, messages, tools=None):
        t0 = time.perf_counter()
        try:
            return self._send(messages)
        finally:
            with self.lock:
                self.spent_s += time.perf_counter() - t0

    def _send(self, messages):
        time.sleep(self.model_s)
        with self.lock:
            self.calls += 1
            self.sent_chars = len(json.dumps(messages, default=str))
            if self.fail_every and self.calls % self.fail_every == 0:
                raise TimeoutError("model request timed out (injected)")
            return self.responses.pop(0) if self.responses else {"text": "ok", "tool_calls": []}


def web_responses(kind, slots, n_turns):
    out = []
    for i in range(n_turns):
        if kind == "avail":
            out += [{"text": None, "tool_calls": [{"name": "check_availability",
                                                   "args": {"date": slots[0][0]}}]},
                    {"text": "We have slots.", "tool_calls": []}]
        elif kind == "book" and i == n_turns - 1:
            d, t = slots.pop(0)
            out += [{"text": None, "tool_calls": [{"name": "book_appointment", "args": {
                "customer_name": "Bench", "phone": "9876543210", "service": "Cleaning",
                "date": d, "time": t}}]}, {"text": "You're booked!", "tool_calls": []}]
        else:
            out += [{"text": "Happy to help.", "tool_calls": []}]
    return out


def new_web_session(llm):
    import server
    sid = f"bench{len(server.sessions)}{time.perf_counter_ns()}"
    now = dt.datetime.now()
    server.sessions[sid] = {"agent": ReceptionistAgent(CLIENT, llm=llm), "client_id": CLIENT,
                            "call_id": now.strftime("%Y%m%d_%H%M%S_") + sid[-6:],
                            "started": now, "last_activity": now, "lock": threading.Lock()}
    return sid


def run_web(sessions, kind, failure, n_turns=4, model_s=0.15):
    import server
    slots = open_slots(sessions + 2)
    undo = inject(failure)
    fail_every = 3 if failure == "model_timeout" else 0
    latencies, rounds, model_time, degraded, errors = [], [], [], 0, 0
    lock = threading.Lock()
    sids = [new_web_session(SleepyLLM(web_responses(kind, slots, n_turns), model_s, fail_every))
            for _ in range(sessions)]

    def worker(sid):
        nonlocal degraded, errors
        llm = server.sessions[sid]["agent"].llm
        for i in range(n_turns):
            before, spent_before = llm.calls, llm.spent_s
            t0 = time.perf_counter()
            try:
                out = server.chat(server.ChatRequest(session_id=sid, message=f"turn {i}"))
            except Exception:
                with lock:
                    errors += 1
                continue
            with lock:
                latencies.append(time.perf_counter() - t0)
                rounds.append(llm.calls - before)
                model_time.append(llm.spent_s - spent_before)
                degraded += int(bool(out.get("degraded")))

    t0, cpu0 = time.perf_counter(), time.process_time()
    threads = [threading.Thread(target=worker, args=(s,)) for s in sids]
    [t.start() for t in threads]
    [t.join() for t in threads]
    wall = time.perf_counter() - t0
    undo()
    # VoxAgent's own time per turn: wall time minus time spent inside the fake model.
    overhead = [lat - m for lat, m in zip(latencies, model_time)]
    booked = len([b for b in storage.read_bookings(CLIENT) if b["status"] == "confirmed"])
    return {"model_round_trip_ms": model_s * 1000, "turn_latency_ms": summary(latencies),
            "overhead_beyond_model_ms": summary(overhead),
            "model_rounds_per_turn": {"mean": round(statistics.mean(rounds), 2) if rounds else None,
                                      "max": max(rounds) if rounds else None},
            "degraded_replies": degraded, "errors": errors, "sessions": sessions,
            "bookings_confirmed": booked, "turns_per_s": round(len(latencies) / wall, 2),
            "wall_s": round(wall, 2), "cpu_s": round(time.process_time() - cpu0, 2)}


# ---- focused scenarios ------------------------------------------------------------------

def run_double_submit(runs=20, *_):
    """Two requests on ONE session at the same moment (double-click, two tabs),
    `runs` times. Checks that every tool-call entry is still followed by its
    results, and counts what the second request got back."""
    import server
    from fastapi import HTTPException
    broken_runs = broken_pairs = 0
    statuses = {}
    for _ in range(runs):
        responses = []
        for _ in range(2):
            responses += [{"text": None, "tool_calls": [{"name": "check_availability",
                                                         "args": {"date": open_slots(1)[0][0]}}]},
                          {"text": "Slots.", "tool_calls": []}]
        sid = new_web_session(SleepyLLM(responses, 0.02))
        barrier = threading.Barrier(2)

        def go():
            barrier.wait()
            try:
                server.chat(server.ChatRequest(session_id=sid, message="slots?"))
                code = 200
            except HTTPException as e:
                code = e.status_code
            statuses[code] = statuses.get(code, 0) + 1
        threads = [threading.Thread(target=go) for _ in range(2)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        history = server.sessions.pop(sid)["agent"].history
        broken = 0
        for i, m in enumerate(history):
            if m["role"] == "assistant" and m.get("tool_calls"):
                following = history[i + 1:i + 1 + len(m["tool_calls"])]
                if [x["role"] for x in following] != ["tool"] * len(m["tool_calls"]):
                    broken += 1
        broken_runs += int(broken > 0)
        broken_pairs += broken
    return {"runs": runs, "runs_with_broken_history": broken_runs,
            "broken_tool_pairs": broken_pairs,
            "responses_by_status": {str(k): v for k, v in sorted(statuses.items())}}


def run_booking_race(sessions, *_):
    """`sessions` callers book the SAME slot at the same instant."""
    d, t = open_slots(1)[0]
    barrier = threading.Barrier(sessions)
    results = []

    def go(n):
        agent = ReceptionistAgent(CLIENT, llm=object())
        barrier.wait()
        results.append(agent.run_tool({"name": "book_appointment", "args": {
            "customer_name": f"C{n}", "phone": "9876543210", "service": "x",
            "date": d, "time": t}})["result"].get("status"))
    threads = [threading.Thread(target=go, args=(n,)) for n in range(sessions)]
    [x.start() for x in threads]
    [x.join() for x in threads]
    rows = [b for b in storage.read_bookings(CLIENT)
            if b["date"] == d and b["time"] == t and b["status"] == "confirmed"]
    return {"confirmed_replies": results.count("confirmed"), "failed_replies": results.count("failed"),
            "confirmed_rows": len(rows)}


def run_long_history(turns, *_):
    """Cost of one web turn when the conversation is already `turns` long."""
    import server
    sid = new_web_session(SleepyLLM([{"text": "ok", "tool_calls": []}], 0.0))
    agent = server.sessions[sid]["agent"]
    d = open_slots(1)[0][0]
    for i in range(turns):
        agent.history.append({"role": "user", "text": f"question number {i} " * 4, "at": agent.now()})
        if i % 5 == 0:
            agent.history.append(agent.tool_call_entry([{"name": "check_availability", "args": {"date": d}}]))
            agent.history.append(agent.run_tool({"name": "check_availability", "args": {"date": d}}))
        agent.history.append({"role": "assistant", "text": f"answer number {i} " * 6, "at": agent.now()})
    t0 = time.perf_counter()
    server.chat(server.ChatRequest(session_id=sid, message="one more"))
    turn_s = time.perf_counter() - t0
    t1 = time.perf_counter()
    storage.log_call_from_agent(agent, "web-test", server.sessions[sid]["started"],
                                call_id=server.sessions[sid]["call_id"])
    log_s = time.perf_counter() - t1
    trace = storage.CALLS_DIR / CLIENT / "traces" / f"{server.sessions[sid]['call_id']}.json"
    return {"history_turns": turns, "history_entries": len(agent.history),
            "turn_ms_excl_model": round(turn_s * 1000, 2), "log_and_trace_ms": round(log_s * 1000, 2),
            "model_request_chars": agent.llm.sent_chars, "trace_kb": round(trace.stat().st_size / 1024, 1)}


def run_dashboard(n_calls, *_):
    """Dashboard work for a business with `n_calls` saved calls: cold (first
    request after start) and warm (cached), plus the ETag check."""
    import billing
    import server
    folder = storage.CALLS_DIR / CLIENT
    folder.mkdir(parents=True, exist_ok=True)
    transcript = "Customer: hello\nAgent: hi there, how can I help?\n" * 8
    for i in range(n_calls):
        (folder / f"c{i:06d}.json").write_text(json.dumps({
            "call_id": f"c{i:06d}", "client_id": CLIENT, "channel": "phone",
            "started": "2026-10-01T10:00:00", "ended": "2026-10-01T10:02:00", "seconds": 120,
            "turns": 4, "transcript": transcript + ("book_appointment" if i % 4 == 0 else "")}))

    def work():
        calls = storage.read_call_logs(CLIENT)
        bookings = storage.read_bookings(CLIENT)
        leads = storage.read_leads(CLIENT)
        server._stats_from(calls, bookings, leads)
        billing.status(CLIENT)
        return calls[:server.DASHBOARD_CALL_LIMIT]

    storage.clear_caches()
    t0 = time.perf_counter()
    work()
    cold = time.perf_counter() - t0
    warm = []
    for _ in range(20):
        t1 = time.perf_counter()
        work()
        warm.append(time.perf_counter() - t1)
    etag = []
    for _ in range(50):
        t2 = time.perf_counter()
        storage.data_version(CLIENT)
        etag.append(time.perf_counter() - t2)
    return {"calls_on_disk": n_calls, "cold_ms": round(cold * 1000, 2),
            "warm_ms": summary(warm), "etag_check_ms": summary(etag)}


SCENARIOS = {
    "phone_avail": lambda n: run_phone(n, "avail", None),
    "phone_book": lambda n: run_phone(n, "book", None),
    "phone_book_sheets_slow": lambda n: run_phone(n, "book", "sheets_slow"),
    "phone_book_sheets_stall": lambda n: run_phone(n, "book", "sheets_stall"),
    "phone_book_sheets_down": lambda n: run_phone(n, "book", "sheets_down"),
    "phone_book_slow_db": lambda n: run_phone(n, "book", "slow_db"),
    "phone_model_drop": lambda n: run_phone(n, "avail", "model_drop"),
    "phone_interrupt": lambda n: run_phone(n, "avail", "interrupt"),
    "web_avail": lambda n: run_web(n, "avail", None),
    "web_book": lambda n: run_web(n, "book", None),
    "web_book_sheets_slow": lambda n: run_web(n, "book", "sheets_slow"),
    "web_model_timeout": lambda n: run_web(n, "avail", "model_timeout"),
    "web_double_submit": run_double_submit,
    "booking_race": run_booking_race,
    "long_history": run_long_history,
    "dashboard": run_dashboard,
}

SUITES = {
    "quick": [("phone_avail", 5), ("phone_book", 5), ("phone_book_sheets_slow", 2),
              ("phone_model_drop", 1), ("web_avail", 5), ("web_double_submit", 20),
              ("booking_race", 10), ("long_history", 200), ("dashboard", 1000)],
    "full": [(s, n) for s in ("phone_avail", "phone_book", "phone_interrupt", "web_avail", "web_book")
             for n in (1, 2, 5, 10)]
    + [(s, n) for s in ("phone_book_sheets_slow", "phone_book_sheets_down", "phone_book_slow_db",
                        "web_book_sheets_slow", "web_model_timeout") for n in (1, 5)]
    + [("phone_book_sheets_stall", 2), ("phone_model_drop", 1), ("phone_model_drop", 5),
       ("web_double_submit", 1000), ("booking_race", 10), ("booking_race", 50)]
    + [("long_history", n) for n in (20, 200, 800)]
    + [("dashboard", n) for n in (100, 1000, 5000)],
}


def run_one(name, n):
    data = SCENARIOS[name](n)
    data.update(scenario=name, param=n, peak_rss_mb=peak_rss_mb(), python=platform.python_version())
    return data


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--scenario", choices=sorted(SCENARIOS))
    ap.add_argument("--sessions", type=int, default=1, help="sessions / calls / size parameter")
    ap.add_argument("--suite", choices=sorted(SUITES), default="quick")
    ap.add_argument("--out", help="write all results as JSON here")
    args = ap.parse_args()
    if args.scenario:
        print(json.dumps(run_one(args.scenario, args.sessions)))
        return
    results = []
    for name, n in SUITES[args.suite]:
        proc = subprocess.run([sys.executable, __file__, "--scenario", name, "--sessions", str(n)],
                              capture_output=True, text=True, timeout=600)
        # The result is the last JSON line: agent.py prints booking lines
        # before it, and storage's shutdown report can print after it.
        line = next((ln for ln in reversed(proc.stdout.splitlines()) if ln.startswith("{")), "{}")
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            data = {"scenario": name, "param": n, "error": (proc.stderr or proc.stdout)[-400:]}
        results.append(data)
        print(f"{name:<26} n={n:<4} " + json.dumps({k: v for k, v in data.items()
              if k not in ("scenario", "param", "python")}))
    if args.out:
        Path(args.out).write_text(json.dumps({"machine": {"python": platform.python_version(),
                                                          "platform": platform.platform(),
                                                          "cpus": os.cpu_count()},
                                              "results": results}, indent=1))


if __name__ == "__main__":
    main()
