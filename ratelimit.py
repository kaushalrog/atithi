"""ratelimit.py — slow down anyone guessing credentials.

WHY (audit RT-3, 2026-10-21): business codes were checked with no limit at
all; 1,500 wrong guesses took 2 seconds. A code opens a business's bookings,
customers' phone numbers and transcripts, so guessing must be slow.

The rule: an address that fails to sign in MAX_FAILURES times within
WINDOW_S is refused (HTTP 429) until its oldest failure ages out. Correct
credentials are refused too while blocked, otherwise a guesser could keep
going and simply watch for the one answer that isn't a 429.

Memory is bounded: at most MAX_KEYS addresses are tracked; the stalest are
dropped first. Stdlib only, one lock, safe across FastAPI's worker threads.
"""

import threading
import time
from collections import OrderedDict, deque

MAX_FAILURES = 10
WINDOW_S = 15 * 60
MAX_KEYS = 10_000


class FailureLimiter:
    def __init__(self, max_failures: int = MAX_FAILURES, window_s: float = WINDOW_S,
                 max_keys: int = MAX_KEYS, clock=time.monotonic):
        self.max_failures, self.window_s, self.max_keys = max_failures, window_s, max_keys
        self._clock = clock
        self._fails: "OrderedDict[str, deque[float]]" = OrderedDict()
        self._lock = threading.Lock()

    def _recent(self, key: str, now: float) -> deque | None:
        q = self._fails.get(key)
        if q is None:
            return None
        while q and now - q[0] >= self.window_s:
            q.popleft()
        if not q:
            del self._fails[key]
            return None
        return q

    def retry_after(self, key: str) -> int:
        """Seconds until `key` may try again; 0 if it isn't blocked."""
        now = self._clock()
        with self._lock:
            q = self._recent(key, now)
            if q is None or len(q) < self.max_failures:
                return 0
            return max(1, int(self.window_s - (now - q[0])) + 1)

    def fail(self, key: str):
        now = self._clock()
        with self._lock:
            q = self._recent(key, now)
            if q is None:
                q = self._fails[key] = deque(maxlen=self.max_failures)
            q.append(now)
            self._fails.move_to_end(key)
            while len(self._fails) > self.max_keys:
                self._fails.popitem(last=False)

    def clear(self):
        with self._lock:
            self._fails.clear()
