"""Small in-process rate limiter for the auth endpoints.

Sliding-window counters keyed by (rule, subject), where the subject is a client IP or
an account. Two uses:

* ``hit()``: count an attempt and refuse once the window is full (e.g. 20 logins per
  minute per IP, 10 sign-ups per hour per IP).
* failure counting for **account lockout**: ``record_failure()`` / ``locked()`` /
  ``reset()``. Only failed logins count, and a success clears them, so an attacker
  guessing one account's password is stopped after a few tries, while the real user
  isn't locked out by their own successful logins.

State lives in this process. With several server workers, move it to Redis (same
interface) - noted in docs/BUGFIXES.md.
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from dataclasses import dataclass

from fastapi import HTTPException, Request

from config import settings


@dataclass(frozen=True)
class Rule:
    name: str
    limit: int
    window_s: float


# Per client IP
LOGIN_PER_IP = Rule("login-ip", 20, 60)
SIGNUP_PER_IP = Rule("signup-ip", 10, 3600)
FORGOT_PER_IP = Rule("forgot-ip", 5, 3600)
RESET_PER_IP = Rule("reset-ip", 10, 900)
# Per account
LOGIN_FAILURES = Rule("login-fail", 5, 900)  # 5 wrong passwords -> locked for up to 15 min
FORGOT_PER_ACCOUNT = Rule("forgot-acct", 3, 3600)


class RateLimiter:
    def __init__(self, clock=time.monotonic) -> None:
        self._events: dict[tuple[str, str], deque[float]] = {}
        self._lock = threading.Lock()
        self._clock = clock

    def _window(self, rule: Rule, subject: str) -> deque[float]:
        q = self._events.setdefault((rule.name, subject.lower()), deque())
        cutoff = self._clock() - rule.window_s
        while q and q[0] <= cutoff:
            q.popleft()
        return q

    def retry_after(self, rule: Rule, subject: str) -> float:
        """Seconds until the oldest counted event leaves the window (0 if under the limit)."""
        with self._lock:
            q = self._window(rule, subject)
            if len(q) < rule.limit:
                return 0.0
            return max(q[0] + rule.window_s - self._clock(), 0.0)

    def hit(self, rule: Rule, subject: str) -> None:
        """Count one attempt; raise 429 if the limit is already reached."""
        with self._lock:
            q = self._window(rule, subject)
            if len(q) >= rule.limit:
                wait = max(q[0] + rule.window_s - self._clock(), 1.0)
                raise too_many(wait)
            q.append(self._clock())

    def record_failure(self, rule: Rule, subject: str) -> None:
        with self._lock:
            self._window(rule, subject).append(self._clock())

    def locked(self, rule: Rule, subject: str) -> float:
        return self.retry_after(rule, subject)

    def reset(self, rule: Rule, subject: str) -> None:
        with self._lock:
            self._events.pop((rule.name, subject.lower()), None)

    def clear(self) -> None:
        with self._lock:
            self._events.clear()


def too_many(wait_s: float) -> HTTPException:
    return HTTPException(status_code=429, detail=f"Too many attempts. Try again in {math.ceil(wait_s)} s.",
                         headers={"Retry-After": str(math.ceil(wait_s))})


def client_ip(request: Request) -> str:
    """Client address. Behind a reverse proxy, trust X-Forwarded-For only if configured
    (otherwise any client could fake its IP and dodge the per-IP limits)."""
    if settings.trust_proxy_headers:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


limiter = RateLimiter()
