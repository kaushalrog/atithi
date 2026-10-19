"""perf.py — how long things take, measured where they happen.

WHY this exists: the performance audit (docs/PERFORMANCE_AUDIT.md) had to
build a load harness to learn where a caller's wait came from, because the
code itself recorded nothing. A real pilot can't run that harness against
Gemini and Twilio — so the code has to measure itself. This module is that
measurement, and nothing else: stdlib only, no disk, no network.

    with perf.span("tool", call=agent.perf_id, tool="book_appointment"):
        ...                              # timed with a monotonic clock
    perf.event("timeout.model_connect")  # a counter
    perf.gauge("calls.active", 2)        # a current value
    perf.snapshot()                      # p50/p95/p99 per span, for /api/admin/perf

PRIVACY: spans carry a short random id per conversation (`call`) and a few
labels from a fixed allowlist — never message text, names, phone numbers,
Twilio SIDs or keys. A label outside the allowlist is dropped (and counted)
in production; in test mode it raises, so a test catches the leak.

MEMORY is fixed: each span name keeps its last 512 durations, and the number
of names, events and gauges is capped. A busy server can run for months.

An optional sink (see set_sink) receives one dict per finished span. storage
registers one when VOXAGENT_PERF_LOG is set, so the disk writes live with all
the other disk writes, on a background thread.
"""

import asyncio
import collections
import contextlib
import datetime as dt
import os
import threading
import time

ALLOWED_LABELS = frozenset({"tool", "channel", "round", "rounds", "outcome", "status"})
SAMPLES_PER_SPAN = 512
MAX_NAMES = 64            # distinct span / event / gauge names, each
LOOP_SAMPLE_S = 0.25      # how often the event-loop lag monitor wakes

_lock = threading.Lock()
_spans: dict[str, dict] = {}
_events: dict[str, int] = {}
_gauges: dict[str, float] = {}
_dropped = {"names": 0, "labels": 0}
_sink = None


def _strict() -> bool:
    return os.getenv("VOXAGENT_ENV", "").strip().lower() == "test"


def _clean_labels(labels: dict) -> dict:
    bad = [k for k in labels if k not in ALLOWED_LABELS]
    if bad:
        if _strict():
            raise ValueError(f"perf label(s) not allowed: {bad}")
        with _lock:
            _dropped["labels"] += 1
        labels = {k: v for k, v in labels.items() if k in ALLOWED_LABELS}
    return {k: str(v)[:40] for k, v in labels.items()}


def record(name: str, ms: float, ok: bool = True, call: str | None = None,
           log: bool = True, **labels):
    """Store one finished measurement. Never raises in production.
    log=False keeps it out of the JSONL sink (high-rate samples)."""
    labels = _clean_labels(labels)
    with _lock:
        entry = _spans.get(name)
        if entry is None:
            if len(_spans) >= MAX_NAMES:
                _dropped["names"] += 1
                return
            entry = _spans[name] = {"count": 0, "errors": 0,
                                    "ms": collections.deque(maxlen=SAMPLES_PER_SPAN)}
        entry["count"] += 1
        entry["errors"] += 0 if ok else 1
        entry["ms"].append(ms)
        sink = _sink if log else None
    if sink is not None:
        try:
            sink({"ts": dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds"),
                  "name": name, "ms": round(ms, 2), "ok": ok, "call": call, "labels": labels})
        except Exception:
            pass   # a broken log must never break a call


@contextlib.contextmanager
def span(name: str, call: str | None = None, **labels):
    """Time the block. An exception inside counts as an error and re-raises."""
    t0 = time.perf_counter()
    ok = True
    try:
        yield
    except BaseException:
        ok = False
        raise
    finally:
        record(name, (time.perf_counter() - t0) * 1000, ok, call, **labels)


def event(name: str, n: int = 1):
    """Count something that happened: an error, a timeout, a cancellation."""
    with _lock:
        if name not in _events and len(_events) >= MAX_NAMES:
            _dropped["names"] += 1
            return
        _events[name] = _events.get(name, 0) + n


def gauge(name: str, value: float):
    """Set a current value (active calls, queue depth)."""
    with _lock:
        if name not in _gauges and len(_gauges) >= MAX_NAMES:
            _dropped["names"] += 1
            return
        _gauges[name] = value


def _pct(sorted_ms: list[float], q: float) -> float:
    return round(sorted_ms[min(len(sorted_ms) - 1, int(q * len(sorted_ms)))], 2)


def snapshot() -> dict:
    """Everything measured so far, as plain JSON-ready numbers."""
    with _lock:
        # Copy under the lock, sort outside it: the event loop records into
        # this store, so an admin poll must never hold the lock for a sort.
        spans = {n: (e["count"], e["errors"], list(e["ms"])) for n, e in _spans.items()}
        events, gauges, dropped = dict(_events), dict(_gauges), dict(_dropped)
    out = {}
    for name, (count, errors, ms) in sorted(spans.items()):
        ms.sort()
        out[name] = {"count": count, "errors": errors, "samples": len(ms)}
        if ms:
            out[name].update(p50=_pct(ms, 0.50), p95=_pct(ms, 0.95),
                             p99=_pct(ms, 0.99), max=round(ms[-1], 2))
    return {"spans": out, "events": events, "gauges": gauges, "dropped": dropped,
            "window": f"last {SAMPLES_PER_SPAN} samples per span"}


def set_sink(fn):
    """Receive every finished span (fn(dict)). None turns it off."""
    global _sink
    _sink = fn


def reset():
    """Forget everything (tests)."""
    with _lock:
        _spans.clear()
        _events.clear()
        _gauges.clear()
        _dropped.update(names=0, labels=0)


# ---- event-loop lag ---------------------------------------------------------------

_monitors: dict[int, asyncio.Task] = {}   # id(loop) -> its monitor task


async def _watch_loop(period: float):
    """Sleep `period`, see how late we woke. Lateness = time the loop spent on
    something that didn't yield — every live call on this loop felt it."""
    while True:
        t0 = time.perf_counter()
        await asyncio.sleep(period)
        # Four samples a second for the life of the server: kept in memory
        # for /api/admin/perf, never written to the JSONL log, where it would
        # roll real call spans out of the 20 MB file within hours.
        record("loop.lag", max(0.0, (time.perf_counter() - t0 - period) * 1000), log=False)


def ensure_loop_monitor(period: float = LOOP_SAMPLE_S):
    """Start ONE lag monitor for the running event loop (idempotent).

    Called when a streaming call starts; the task lives as long as the loop,
    so there is never more than one per loop — not one per call."""
    loop = asyncio.get_running_loop()
    # Forget monitors of loops that are gone: an id() can be reused by a new
    # loop, and a dead loop's task never reports done.
    for key, task in list(_monitors.items()):
        if task.done() or task.get_loop().is_closed():
            del _monitors[key]
    task = _monitors.get(id(loop))
    if task is None or task.get_loop() is not loop:
        _monitors[id(loop)] = loop.create_task(_watch_loop(period))
