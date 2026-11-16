"""Don't timestamp readings until the system clock can be trusted.

The Pi has no battery-backed real-time clock. After a power cut it boots with whatever
time ``fake-hwclock`` saved (up to an hour old) or the epoch, until NTP syncs. Readings
taken in that window get a wrong but plausible timestamp and land on the wrong day.

The clock is trusted when:
* NTP reports it is synchronised (``timedatectl``, real Pi only), and
* it is not earlier than the newest reading already stored (time can't go backwards),
  and not earlier than this firmware's build floor.

If NTP never syncs (no internet) but the clock passes the other checks, sampling starts
after ``CLOCK_SYNC_TIMEOUT_S`` with a warning: a meter with no network still meters.
"""

from __future__ import annotations

import shutil
import subprocess
import time
from datetime import datetime, timedelta, timezone
from typing import Callable

from config import HAL

CLOCK_FLOOR = datetime(2025, 1, 1, tzinfo=timezone.utc)
TOLERANCE = timedelta(seconds=5)


def ntp_synchronised() -> bool | None:
    """True/False from timedatectl on the real Pi; None when it can't be determined."""
    if HAL != "hardware" or not shutil.which("timedatectl"):
        return None
    try:
        out = subprocess.run(["timedatectl", "show", "-p", "NTPSynchronized", "--value"],
                             capture_output=True, text=True, timeout=5)
        return out.stdout.strip() == "yes"
    except (OSError, subprocess.SubprocessError):
        return None


def clock_plausible(now: datetime, last_stored: datetime | None) -> bool:
    if now < CLOCK_FLOOR:
        return False
    return last_stored is None or now >= last_stored - TOLERANCE


def wait_for_trusted_clock(last_stored: Callable[[], datetime | None], timeout_s: float,
                           log: Callable[[str], None] = print,
                           now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
                           synced: Callable[[], bool | None] = ntp_synchronised,
                           sleep: Callable[[float], None] = time.sleep,
                           poll_s: float = 2.0) -> bool:
    """Block until the clock is trusted. Returns True if NTP-confirmed (or not checkable)."""
    waited = 0.0
    warned = False
    while True:
        plausible = clock_plausible(now(), last_stored())
        ntp = synced()
        if plausible and ntp is not False:
            return True
        if plausible and waited >= timeout_s:
            log(f"[CLOCK] NTP not synchronised after {timeout_s:.0f} s; clock looks plausible, starting anyway")
            return False
        if not warned:
            reason = "NTP not synchronised yet" if plausible else \
                f"system time {now().isoformat(timespec='seconds')} is earlier than stored data"
            log(f"[CLOCK] Waiting for a trustworthy clock ({reason})")
            warned = True
        sleep(poll_s)
        waited += poll_s
