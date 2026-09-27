"""Tests for /auth/login brute-force mitigation (app/core/rate_limit.py).

Covers both the endpoint behaviour (429s, scoping, reset-on-success) and the
limiter's own guarantees (sliding-window expiry, bounded memory, thread
safety, peek-does-not-record). Window tests inject a fake clock rather than
sleeping, so they are deterministic and fast.
"""
import threading
import time

from app.core.config import settings
from app.core.rate_limit import SlidingWindowLimiter, login_limiter


class FakeClock:
    """Manually advanced monotonic clock."""

    def __init__(self, start=1000.0):
        self.now = start

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def _login(client, username, password):
    return client.post("/auth/login", json={"username": username, "password": password})


def _register(client, username, password="supersecret1"):
    resp = client.post("/auth/register", json={"username": username, "password": password})
    assert resp.status_code == 201, resp.text
    return password


# --------------------------------------------------------------------------
# Endpoint behaviour
# --------------------------------------------------------------------------
def test_failed_logins_below_limit_still_get_401(client):
    _register(client, "below")
    for _ in range(settings.LOGIN_ACCOUNT_FAILURE_LIMIT - 1):
        resp = _login(client, "below", "wrong-password")
        assert resp.status_code == 401


def test_failed_logins_over_limit_return_429_with_retry_after(client):
    _register(client, "locked")
    for _ in range(settings.LOGIN_ACCOUNT_FAILURE_LIMIT):
        assert _login(client, "locked", "wrong-password").status_code == 401

    resp = _login(client, "locked", "wrong-password")
    assert resp.status_code == 429
    assert "Retry-After" in resp.headers
    assert int(resp.headers["Retry-After"]) > 0


def test_correct_password_is_also_rejected_once_throttled(client):
    """The lockout must hold even for the RIGHT credentials -- otherwise an
    attacker only needs to keep guessing while a legitimate user's eventual
    success proves nothing about the throttle working."""
    password = _register(client, "locked2")
    for _ in range(settings.LOGIN_ACCOUNT_FAILURE_LIMIT):
        _login(client, "locked2", "wrong-password")

    assert _login(client, "locked2", password).status_code == 429


def test_successful_login_clears_account_failures(client):
    """A user who mistypes a few times then succeeds must not stay one step
    from a lockout forever -- success resets the account budget."""
    password = _register(client, "recovering")
    for _ in range(settings.LOGIN_ACCOUNT_FAILURE_LIMIT - 1):
        assert _login(client, "recovering", "wrong-password").status_code == 401

    assert _login(client, "recovering", password).status_code == 200

    # Full failure budget available again after the success.
    for _ in range(settings.LOGIN_ACCOUNT_FAILURE_LIMIT):
        assert _login(client, "recovering", "wrong-password").status_code == 401
    assert _login(client, "recovering", "wrong-password").status_code == 429


def test_account_limit_is_scoped_per_username(client):
    """One account being throttled must not lock out a different account."""
    _register(client, "attacked")
    password_b = _register(client, "bystander")

    for _ in range(settings.LOGIN_ACCOUNT_FAILURE_LIMIT + 1):
        _login(client, "attacked", "wrong-password")
    assert _login(client, "attacked", "wrong-password").status_code == 429

    assert _login(client, "bystander", password_b).status_code == 200


def test_username_key_is_case_insensitive(client):
    """Otherwise an attacker just alternates 'Alice'/'alice' to double the
    budget on the same account."""
    _register(client, "CaseUser")
    for _ in range(settings.LOGIN_ACCOUNT_FAILURE_LIMIT):
        _login(client, "CASEUSER", "wrong-password")
    assert _login(client, "caseuser", "wrong-password").status_code == 429


def test_per_ip_limit_counts_every_attempt_including_successes(client):
    """The IP budget bounds total work from one source, so successful logins
    consume it too -- otherwise a single host could hammer the endpoint
    indefinitely using valid credentials it already has."""
    password = _register(client, "ipuser")
    got_429 = False
    for _ in range(settings.LOGIN_IP_LIMIT + 3):
        resp = _login(client, "ipuser", password)
        if resp.status_code == 429:
            got_429 = True
            break
        assert resp.status_code == 200, resp.text
    assert got_429, "per-IP limit never triggered on repeated successful logins"


def test_429_does_not_reveal_which_limit_tripped(client):
    """Telling the caller whether the IP or the account tripped lets an
    attacker tune the other dimension."""
    _register(client, "quiet")
    for _ in range(settings.LOGIN_ACCOUNT_FAILURE_LIMIT + 1):
        _login(client, "quiet", "wrong-password")

    body = _login(client, "quiet", "wrong-password").json()
    text = str(body).lower()
    assert "ip" not in text
    assert "account" not in text
    assert "username" not in text


def test_register_is_not_rate_limited_by_the_login_limiter(client):
    """Scope check: only /auth/login is protected. Registration is a
    different endpoint with different abuse characteristics and is not
    silently swept into this limit."""
    for i in range(settings.LOGIN_ACCOUNT_FAILURE_LIMIT + 5):
        resp = client.post(
            "/auth/register", json={"username": f"bulk{i}", "password": "supersecret1"}
        )
        assert resp.status_code == 201, resp.text


def test_other_endpoints_unaffected(client):
    for _ in range(settings.LOGIN_IP_LIMIT + 5):
        assert client.get("/health").status_code == 200


# --------------------------------------------------------------------------
# Limiter guarantees
# --------------------------------------------------------------------------
def test_sliding_window_expires_old_events():
    clock = FakeClock()
    lim = SlidingWindowLimiter(clock=clock)

    for _ in range(3):
        lim.record("k")
    allowed, _ = lim.peek("k", 3, 60)
    assert allowed is False

    # Sliding, not fixed: after the window passes the FIRST event, capacity
    # returns even though a fixed window might still be counting.
    clock.advance(61)
    allowed, retry = lim.peek("k", 3, 60)
    assert allowed is True
    assert retry == 0


def test_sliding_window_has_no_boundary_burst():
    """The whole reason this project uses a sliding log instead of the fixed
    window (INCR+EXPIRE) used by the Redis limiters elsewhere in this
    portfolio.

    An earlier version of this test advanced 59.9s from an arbitrary start
    time, which never crossed an epoch-aligned boundary -- a fixed-window
    limiter would have blocked there too, so the test proved nothing. This
    version runs the SAME scenario against a minimal fixed-window counter and
    asserts the two algorithms actually disagree, which is the claim.
    """

    class FixedWindow:
        """INCR + EXPIRE, bucketed on epoch-aligned windows (the Redis pattern)."""

        def __init__(self, clock, window):
            self._clock, self._window = clock, window
            self._buckets: dict[tuple[str, int], int] = {}

        def count(self, key):
            bucket = int(self._clock() // self._window)
            return self._buckets.get((key, bucket), 0)

        def record(self, key):
            bucket = int(self._clock() // self._window)
            self._buckets[(key, bucket)] = self._buckets.get((key, bucket), 0) + 1

    limit, window = 5, 60
    clock = FakeClock(start=0.0)
    sliding = SlidingWindowLimiter(clock=clock)
    fixed = FixedWindow(clock, window)

    # Spend the full budget at t=30 -- mid-bucket, so the epoch-aligned fixed
    # bucket [0,60) rolls over at t=60 while these events are only 31s old.
    clock.advance(30)
    for _ in range(limit):
        sliding.record("k")
        fixed.record("k")
    assert fixed.count("k") == limit
    assert sliding.peek("k", limit, window)[0] is False

    clock.advance(31)  # t=61: the fixed bucket has rolled over, the log has not
    assert sliding.peek("k", limit, window)[0] is False, "sliding log must still block"
    assert fixed.count("k") == 0, "fixed window must have reset (that is the flaw)"

    # The fixed window now admits a second full budget inside 31 seconds.
    for _ in range(limit):
        assert fixed.count("k") < limit
        fixed.record("k")
    assert fixed.count("k") == limit  # 2x limit between t=30 and t=61
    assert sliding.peek("k", limit, window)[0] is False


def test_events_older_than_the_window_do_expire():
    """Guard the other direction: the sliding log must actually release
    capacity, or it would lock accounts out permanently."""
    clock = FakeClock()
    lim = SlidingWindowLimiter(clock=clock)
    for _ in range(5):
        lim.record("k", window_seconds=60)
    assert lim.peek("k", 5, 60)[0] is False
    clock.advance(61)
    assert lim.peek("k", 5, 60)[0] is True


def test_record_honours_a_window_longer_than_the_default():
    """Regression: record() used to prune with a hard-coded 60s default
    regardless of the caller's window, which silently truncated the 300s
    per-account failure budget to 60s. Failures spread over more than a minute
    must still accumulate to the limit."""
    clock = FakeClock()
    lim = SlidingWindowLimiter(clock=clock)
    limit, window = 5, 300

    # One failure every 70 seconds. Five of them span 280s, so all are inside
    # the 300s budget -- but each is more than 60s older than the next, which
    # is exactly what the hard-coded default used to destroy (it pruned the
    # previous failure away on every record, capping the count at 1-2).
    for i in range(limit):
        if i:
            clock.advance(70)
        lim.record("k", window_seconds=window)
        assert lim.count("k", window_seconds=window) == i + 1

    assert lim.peek("k", limit, window)[0] is False

    # And the budget does still release once events age out.
    clock.advance(window + 1)
    assert lim.peek("k", limit, window)[0] is True


def test_peek_does_not_record():
    lim = SlidingWindowLimiter(clock=FakeClock())
    for _ in range(10):
        lim.peek("k", 3, 60)
    assert lim.count("k") == 0


def test_attempt_consumes_a_slot():
    """attempt() is the atomic check-and-consume used by the endpoint's IP
    budget; it must actually count, unlike peek()."""
    lim = SlidingWindowLimiter(clock=FakeClock())
    for i in range(3):
        assert lim.attempt("k", 3, 60) == (True, 0)
        assert lim.count("k", window_seconds=60) == i + 1
    allowed, retry = lim.attempt("k", 3, 60)
    assert allowed is False
    assert retry > 0
    assert lim.count("k", window_seconds=60) == 3  # blocked attempt not counted


class SlowClock:
    """Monotonic clock that sleeps on every read.

    A race test built on an instant clock is worthless: the window between
    `peek()` returning and `record()` running is a handful of bytecodes, and
    the GIL rarely switches there, so a genuinely racy implementation passes
    anyway. That is exactly what happened to the first version of these tests
    -- they passed identically against the atomic and the racy limiter,
    proving nothing. Sleeping inside the clock widens the window and makes the
    interleaving reproduce reliably (verified: 10 admitted vs 60 admitted at
    limit=10, across 1ms/5ms/20ms sleeps).
    """

    def __init__(self, delay=0.005):
        self._delay = delay

    def __call__(self):
        time.sleep(self._delay)
        return time.monotonic()


class CountingLock:
    """Drop-in replacement for threading.Lock that counts acquisitions."""

    def __init__(self):
        self._lock = threading.Lock()
        self.acquisitions = 0

    def __enter__(self):
        self._lock.acquire()
        self.acquisitions += 1
        return self

    def __exit__(self, *exc):
        self._lock.release()
        return False


def test_attempt_is_a_single_critical_section():
    """Timing-independent proof of atomicity: attempt() must hold the lock
    exactly ONCE. peek()+record() holds it twice, and the gap between those
    two acquisitions is precisely where a concurrent request slips through.
    Unlike a race test this cannot flake, so it pins the property even on a
    machine where the empirical test below happens not to interleave.
    """
    lim = SlidingWindowLimiter(clock=FakeClock())
    lim._lock = CountingLock()
    lim.attempt("k", 10, 60)
    assert lim._lock.acquisitions == 1

    lim2 = SlidingWindowLimiter(clock=FakeClock())
    lim2._lock = CountingLock()
    lim2.peek("k", 10, 60)
    lim2.record("k", window_seconds=60)
    assert lim2._lock.acquisitions == 2, "sanity: the racy pattern takes two acquisitions"


def test_attempt_never_overshoots_the_limit_under_concurrency():
    """The race that motivated attempt(): `login` is a sync def, so FastAPI
    runs it in a threadpool and many requests genuinely execute at once. With
    peek()+record() they can all pass the check before any records -- measured
    at 60 admitted against a limit of 10 when attempt() was rewritten as that
    pair. The atomic version must admit exactly `limit`.
    """
    lim = SlidingWindowLimiter(clock=SlowClock())
    limit, n_threads = 10, 60
    admitted = []
    lock = threading.Lock()
    barrier = threading.Barrier(n_threads)

    def worker():
        barrier.wait()  # maximise contention: every thread starts together
        ok, _ = lim.attempt("race", limit, 60)
        if ok:
            with lock:
                admitted.append(1)

    threads = [threading.Thread(target=worker) for _ in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(admitted) == limit, (
        f"attempt() admitted {len(admitted)} of {n_threads} against a limit of "
        f"{limit}; any overshoot means the check-then-act race is back"
    )


def test_peek_then_record_pair_is_not_a_safe_substitute():
    """Documents WHY attempt() exists, by exercising the racy pattern directly
    with the same slow clock. Asserted loosely (>= limit) because the exact
    overshoot is timing-dependent; the point is that this pattern is not the
    one the endpoint may use, and that it never admits FEWER than the limit.
    """
    lim = SlidingWindowLimiter(clock=SlowClock())
    limit, n_threads = 10, 60
    admitted = []
    lock = threading.Lock()
    barrier = threading.Barrier(n_threads)

    def worker():
        barrier.wait()
        ok, _ = lim.peek("race", limit, 60)
        if ok:
            lim.record("race", window_seconds=60)
            with lock:
                admitted.append(1)

    threads = [threading.Thread(target=worker) for _ in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(admitted) >= limit


def test_retry_after_is_positive_and_within_window():
    clock = FakeClock()
    lim = SlidingWindowLimiter(clock=clock)
    for _ in range(3):
        lim.record("k")
    allowed, retry = lim.peek("k", 3, 60)
    assert allowed is False
    assert 1 <= retry <= 61


def test_reset_clears_history():
    lim = SlidingWindowLimiter(clock=FakeClock())
    for _ in range(4):
        lim.record("k")
    assert lim.peek("k", 3, 60)[0] is False
    lim.reset("k")
    assert lim.peek("k", 3, 60)[0] is True
    assert lim.count("k") == 0


def test_memory_is_bounded_under_key_flooding():
    """Unbounded key growth is itself a DoS vector: an attacker sends logins
    for millions of random usernames to exhaust server memory. The cap must
    hold regardless of how many distinct keys are used."""
    lim = SlidingWindowLimiter(max_keys=100, clock=FakeClock())
    for i in range(5_000):
        lim.record(f"attacker-key-{i}")
    assert len(lim._events) <= 100


def test_eviction_drops_least_recently_active_keys():
    clock = FakeClock()
    lim = SlidingWindowLimiter(max_keys=3, clock=clock)
    lim.record("old")
    clock.advance(1)
    lim.record("mid")
    clock.advance(1)
    lim.record("new")
    clock.advance(1)
    lim.record("newest")  # forces eviction of the least-recently-active key

    assert lim.count("old") == 0
    assert lim.count("newest") == 1


def test_concurrent_records_are_not_lost():
    """`login` is a sync def, so FastAPI runs it in a threadpool and these
    mutations really are concurrent. A missing lock would produce a
    check-then-act race that silently admits requests over the limit."""
    lim = SlidingWindowLimiter(clock=FakeClock())
    threads = [
        threading.Thread(target=lambda: [lim.record("shared") for _ in range(200)])
        for _ in range(8)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert lim.count("shared", window_seconds=60) == 8 * 200


def test_module_level_limiter_is_shared_instance():
    """The endpoint must use the same instance across requests, or no limit
    would ever accumulate."""
    from app.api.auth import login_limiter as imported

    assert imported is login_limiter


def test_http_exception_carries_retry_after_header(client):
    _register(client, "hdr")
    for _ in range(settings.LOGIN_ACCOUNT_FAILURE_LIMIT + 1):
        _login(client, "hdr", "wrong")
    resp = _login(client, "hdr", "wrong")
    assert resp.status_code == 429
    # FastAPI only forwards headers from HTTPException if they are supplied
    # explicitly -- assert the client actually receives it.
    assert resp.headers.get("Retry-After") is not None
