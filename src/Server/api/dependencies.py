"""Authentication / authorisation dependencies shared by every router.

Two kinds of callers:
* **Users** (web / mobile app): ``Authorization: Bearer <JWT>`` from /auth/login.
* **Devices** (the meter): ``X-Device-Id`` + ``X-Device-Key`` provisioned per device.

Previously ``verify_token`` existed but no route used it, so every endpoint - including
switching a consumer's supply off - was open to the internet, and any caller could read
any device's data by changing ``device_id``.
"""

from __future__ import annotations

from fastapi import Depends, Header, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from utils.database import get_metadata_db
from utils.security import device_key_matches, verify_token

bearer = HTTPBearer(auto_error=False)


def get_current_user(creds: HTTPAuthorizationCredentials | None = Depends(bearer)) -> dict:
    if creds is None or creds.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Not authenticated", headers={"WWW-Authenticate": "Bearer"})
    payload = verify_token(creds.credentials)
    user = get_metadata_db().get_user(int(payload["sub"]))
    if user is None:
        raise HTTPException(status_code=401, detail="User no longer exists")
    return user


def authenticate_device(device_id: str | None, device_key: str | None) -> dict | None:
    if not device_id or not device_key:
        return None
    device = get_metadata_db().get_device(device_id)
    if device is None or not device_key_matches(device_key, device["key_hash"]):
        return None
    return device


def get_current_device(x_device_id: str | None = Header(None), x_device_key: str | None = Header(None)) -> dict:
    device = authenticate_device(x_device_id, x_device_key)
    if device is None:
        raise HTTPException(status_code=401, detail="Invalid device credentials")
    return device


def resolve_user_device(user: dict, device_id: str | None) -> str:
    """The device a user is asking about - only ever one they own."""
    devices = [d["device_id"] for d in get_metadata_db().devices_for_user(user["id"])]
    if device_id:
        if device_id not in devices:
            raise HTTPException(status_code=404, detail="Device not found")
        return device_id
    if not devices:
        raise HTTPException(status_code=404, detail="No meter is registered to this account")
    return devices[0]
