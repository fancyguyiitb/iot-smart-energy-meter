"""Passwords, device keys and access tokens.

* Passwords: PBKDF2-HMAC-SHA256 with a per-user salt (stdlib, no extra dependency);
  previously they were stored and compared in plaintext.
* Device keys: 256-bit random secrets. Only their SHA-256 is stored server-side; a slow
  hash isn't needed because the key is not guessable.
* Access tokens: short-lived JWTs (``ACCESS_TOKEN_EXPIRE_MINUTES``, default 60).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import HTTPException

from config import settings

ALGORITHM = "HS256"


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode()


def hash_password(password: str, iterations: int | None = None) -> str:
    iterations = iterations or settings.password_hash_iterations
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return f"pbkdf2_sha256${iterations}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, iterations, salt, digest = stored.split("$")
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), base64.b64decode(salt), int(iterations))
    return hmac.compare_digest(candidate, base64.b64decode(digest))


def new_device_key() -> str:
    return secrets.token_urlsafe(32)


def hash_device_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def device_key_matches(key: str, stored_hash: str) -> bool:
    return hmac.compare_digest(hash_device_key(key), stored_hash)


def create_access_token(user_id: int, username: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "uname": username,
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_expire_minutes),
        "typ": "access",
    }
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def verify_token(token: str) -> dict:
    """Decode a JWT and return its payload, or raise 401."""
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")
    if payload.get("typ") != "access":
        raise HTTPException(status_code=401, detail="Invalid token")
    return payload
