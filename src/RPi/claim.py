"""Short-lived, one-time sign-up ("claim") codes, shown as a QR code on the device.

Format: ``VOLTIX1:<device_id>:<fernet token>``. The token is encrypted with this
device's own ``CLAIM_KEY`` (provisioned per device, never committed) and carries a
random nonce; Fernet embeds the creation time. The server accepts it only within
``CLAIM_TTL_SECONDS`` and only once, and only if the device has no owner yet.

Previously one global key was hard-coded in QRCodePage.py (public on GitHub), the
timestamp was never checked and re-registering silently took over the device.

Run ``python claim.py`` to print a fresh code and the sign-up link (handy without a
touchscreen).
"""

from __future__ import annotations

import secrets
from urllib.parse import quote

from cryptography.fernet import Fernet

from config import CLAIM_KEY, DEVICE_ID, SERVER_URL

PREFIX = "VOLTIX1"


def make_claim_code() -> str:
    if not (CLAIM_KEY and DEVICE_ID):
        raise RuntimeError("CLAIM_KEY / DEVICE_ID missing: provision the device first")
    payload = f"{DEVICE_ID}::{secrets.token_urlsafe(12)}".encode()
    token = Fernet(CLAIM_KEY.encode()).encrypt(payload).decode()
    return f"{PREFIX}:{DEVICE_ID}:{token}"


def signup_url(code: str) -> str:
    return f"{SERVER_URL}/app/#/signup?code={quote(code, safe='')}"


if __name__ == "__main__":
    code = make_claim_code()
    print(code)
    print(signup_url(code))
