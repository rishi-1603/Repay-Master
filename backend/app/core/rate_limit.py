"""In-process sliding-window rate limiter for /auth/login (brute-force mitigation).

## Why NOT Redis here (a deliberate divergence from the sibling projects)

DevTrack and CertiFake both rate-limit through Redis. This project
deliberately does not, and the reason is architectural rather than省事:

  - This API is a **single-process** service backed by a **sqlite file**
    (utils/auth.py). It has no horizontal scaling, no second replica, and no
    existing Redis dependency for anything else.
  - Adding Redis *solely* to hold login counters would mean a new
    infrastructure service, a new failure mode, a new container in compose,
    and a new "what if Redis is down" question -- all to protect one endpoint
    on one process that already fits in a single machine's memory.
  - The repo README set exactly this condition: reuse DevTrack's Redis
    pattern "once this API has its own Redis dependency for something else
    that justifies adding it". That condition is not met, so the honest
    answer is the smaller tool.

This is the "explain when NOT to use a technology" case, and the trade-offs
are real and stated rather than hidden:

  1. **State is per-process.** Run uvicorn with `--workers 4` and each worker
     keeps its own counters, so the effective limit becomes 4x the configured
     one. Correct fix at that point is a shared store (Redis) -- which is
     exactly the condition above becoming true.
  2. **State does not survive a restart.** A redeploy clears counters. An
     attacker cannot trigger that, but it does mean the limit is "per process
     lifetime", not absolute.
  3. **Client IP is the socket peer.** Behind a reverse proxy every request
     appears to come from the proxy, so per-IP limiting would collapse all
     users into one bucket. Reading X-Forwarded-For is NOT done here because
     that header is trivially client-spoofable unless you explicitly trust a
     known proxy hop; doing it naively would let an attacker rotate a header
     and bypass the limit entirely, which is worse than the honest limitation.
     Per-account limiting below still works correctly behind a proxy.

## Memory safety

A limiter keyed by username or IP is a memory-exhaustion vector if the key
space is unbounded: an attacker can send login attempts with millions of
random usernames and grow the dict without limit. So the number of tracked
keys is capped, and the least-recently-active keys are evicted when the cap
is reached. Bounded memory costs a little accuracy under attack -- exactly
the situation where accuracy matters least and staying up matters most.

## Thread safety

`login` is a synchronous `def`, so FastAPI runs it in a threadpool: multiple
login requests genuinely execute concurrently in one process. All state
mutation therefore happens under a lock. Without it, two threads could both
read the same count and both admit a request that should have been rejected
(a check-then-act race), which would silently weaken the limit under load.
"""
import logging
import threading
import time
from collections import OrderedDict, deque

# Stdlib logging directly: unlike the sibling DevTrack project, this repo has
# no app/core/logging.py helper, and standing one up just for this module
# would be unrelated scope creep.
logger = logging.getLogger("repaymaster.rate_limit")

#: Cap on distinct tracked keys. See "Memory safety" above.
MAX_TRACKED_KEYS = 5_000

# Window used by record()/count() when none is supplied. The authoritative
# windows for login live in app/core/config.py and are passed to peek().
_DEFAULT_WINDOW = 60.0


class SlidingWindowLimiter:
    """Sliding-window-log limiter: exact within the window, bounded memory.

    A sliding window log (keep the timestamps, count those still inside the
    window) rather than a fixed window (INCR + EXPIRE, as used in the Redis
    implementations elsewhere in this portfolio). Fixed windows allow up to
    ~2x the limit across a boundary; that was an acceptable trade-off there
    because it saved Redis round-trips. Here the state is already in local
    memory, so the more accurate algorithm costs nothing extra and removes
    the boundary-burst loophole -- which matters more for a login endpoint
    than for a comment-posting endpoint.
    """

    def __init__(self, max_keys: int = MAX_TRACKED_KEYS, clock=time.monotonic):
        self._events: OrderedDict[str, deque[float]] = OrderedDict()
        self._lock = threading.Lock()
        self._max_keys = max_keys
        self._clock = clock

    def _prune(self, key: str, window: float, now: float) -> deque[float]:
        """Drop timestamps older than the window. Caller must hold the lock."""
        events = self._events.get(key)
        if events is None:
            events = deque()
            self._events[key] = events
            self._evict_if_full()
        cutoff = now - window
        while events and events[0] <= cutoff:
            events.popleft()
        return events

    def _evict_if_full(self) -> None:
        """Bound total tracked keys. Caller must hold the lock.

        OrderedDict is kept in least-recently-active order (move_to_end on
        every touch), so evicting from the front drops the keys that have been
        idle longest -- the ones least likely to matter.
        """
        while len(self._events) > self._max_keys:
            stale_key, _ = self._events.popitem(last=False)
            logger.debug("Evicting rate-limit key %s (memory cap reached)", stale_key)

    @staticmethod
    def _retry_after(oldest: float, now: float, window_seconds: float) -> int:
        """Whole seconds until the oldest event leaves the window (+1 to round up)."""
        return max(int(window_seconds - (now - oldest)) + 1, 1)

    def peek(self, key: str, limit: int, window_seconds: float) -> tuple[bool, int]:
        """Check whether `key` is already at/over its limit, WITHOUT recording.

        Returns (allowed, retry_after_seconds). Checking without recording is
        what lets the login endpoint enforce a per-account budget on *failures
        only* -- see app/api/auth.py. For the common "check and consume in one
        step" case use attempt() instead; peek()+record() is a check-then-act
        race under concurrency and can admit requests over the limit.
        """
        with self._lock:
            now = self._clock()
            events = self._prune(key, window_seconds, now)
            self._events.move_to_end(key)
            if len(events) < limit:
                return True, 0
            return False, self._retry_after(events[0], now, window_seconds)

    def attempt(
        self, key: str, limit: int, window_seconds: float
    ) -> tuple[bool, int]:
        """Atomically check the budget and consume one slot if allowed.

        Returns (allowed, retry_after_seconds). The check and the record happen
        under a single lock acquisition, so concurrent callers can never both
        see "under limit" and both proceed. `login` is a sync def and therefore
        runs in a threadpool, which makes that race reachable in production,
        not just in theory.
        """
        with self._lock:
            now = self._clock()
            events = self._prune(key, window_seconds, now)
            self._events.move_to_end(key)
            if len(events) >= limit:
                return False, self._retry_after(events[0], now, window_seconds)
            events.append(now)
            return True, 0

    def record(self, key: str, window_seconds: float = _DEFAULT_WINDOW) -> None:
        """Record one event against `key`.

        `window_seconds` MUST match the window the key is enforced with. An
        earlier version of this method always pruned with a 60s default, which
        silently truncated the 300s per-account failure budget down to 60s on
        every recorded failure -- the counter looked correct in tests that ran
        in milliseconds and was wrong in real time. Pruning with the wrong
        window is not a harmless tidy-up; it deletes evidence.
        """
        with self._lock:
            now = self._clock()
            events = self._prune(key, window_seconds, now)
            events.append(now)
            self._events.move_to_end(key)

    def reset(self, key: str) -> None:
        """Clear a key's history (used after a successful login)."""
        with self._lock:
            self._events.pop(key, None)

    def count(self, key: str, window_seconds: float = _DEFAULT_WINDOW) -> int:
        """Current event count for `key` inside the window. For tests/metrics."""
        with self._lock:
            now = self._clock()
            events = self._prune(key, window_seconds, now)
            return len(events)


#: Process-wide limiter instance used by the /auth/login dependency.
login_limiter = SlidingWindowLimiter()
