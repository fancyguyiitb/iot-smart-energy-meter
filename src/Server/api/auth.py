"""Accounts and device ownership.

Sign-up = proving physical access to the meter: the QR code on its screen carries a
short-lived, one-time token encrypted with *that device's* claim key.

Fixes compared with the original version:
* Passwords are hashed (PBKDF2), never stored or compared in plaintext.
* Credentials travel in a JSON body, not in URL query strings (which end up in logs).
* The claim token's timestamp is enforced (``CLAIM_TTL_SECONDS``) and each token works
  once; previously a photo of the QR worked forever.
* A meter that already has an owner can't be silently re-registered (account takeover).
* A broken token returns 400 instead of an unhandled ``InvalidToken`` (500).
* Users live in a relational table, so accounts don't expire after 30 days.
"""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, Depends, HTTPException

from api.dependencies import get_current_user
from api.services import hub
from config import settings
from utils.database import ClaimError, get_metadata_db
from utils.models import ClaimRequest, LoginRequest, SignUpRequest
from utils.security import create_access_token, hash_password, verify_password

router = APIRouter()
CLAIM_PREFIX = "VOLTIX1"
_dummy_hash: str | None = None


def verify_claim_code(code: str) -> tuple[str, str]:
    """Return (device_id, nonce) for a valid, unexpired claim code, else raise 400."""
    parts = code.strip().split(":", 2)
    if len(parts) != 3 or parts[0] != CLAIM_PREFIX:
        raise HTTPException(status_code=400, detail="Not a Voltix sign-up code")
    _, device_id, token = parts
    device = get_metadata_db().get_device(device_id)
    if device is None:
        raise HTTPException(status_code=400, detail="Unknown meter")
    try:
        payload = Fernet(device["claim_key"].encode()).decrypt(token.encode(), ttl=settings.claim_ttl_seconds)
        token_device, nonce = payload.decode().split("::", 1)
    except (InvalidToken, ValueError):
        raise HTTPException(status_code=400, detail="Sign-up code is invalid or has expired. "
                                                    "Show a fresh QR code on the meter.")
    if token_device != device_id:
        raise HTTPException(status_code=400, detail="Sign-up code does not match the meter")
    return device_id, nonce


@router.post("/sign-up", status_code=201)
def sign_up(req: SignUpRequest):
    device_id, nonce = verify_claim_code(req.claim_code)
    password_hash = hash_password(req.password)
    try:
        user_id = get_metadata_db().claim(device_id, nonce, new_user=(req.username, password_hash))
    except ClaimError as e:
        raise HTTPException(status_code=e.status, detail=e.detail)
    return {
        "message": "User created successfully",
        "access_token": create_access_token(user_id, req.username),
        "token_type": "bearer",
        "device_id": device_id,
    }


@router.post("/login")
def login(req: LoginRequest):
    global _dummy_hash
    user = get_metadata_db().get_user_by_username(req.username)
    if user is None:
        # Spend the same time as a real check so response timing doesn't reveal usernames.
        _dummy_hash = _dummy_hash or hash_password("not-a-real-password")
        verify_password(req.password, _dummy_hash)
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not verify_password(req.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return {"access_token": create_access_token(user["id"], user["username"]), "token_type": "bearer"}


@router.get("/me")
def me(user: dict = Depends(get_current_user)):
    devices = get_metadata_db().devices_for_user(user["id"])
    return {"id": user["id"], "username": user["username"],
            "devices": [d | {"online": hub.is_online(d["device_id"])} for d in devices]}


@router.post("/claim-device", status_code=201)
def claim_device(req: ClaimRequest, user: dict = Depends(get_current_user)):
    """Add another meter to an existing account."""
    device_id, nonce = verify_claim_code(req.claim_code)
    try:
        get_metadata_db().claim(device_id, nonce, user_id=user["id"])
    except ClaimError as e:
        raise HTTPException(status_code=e.status, detail=e.detail)
    return {"device_id": device_id}


@router.post("/release-device/{device_id}")
def release_device(device_id: str, user: dict = Depends(get_current_user)):
    """Give up ownership (e.g. before selling the house) so someone else can sign up."""
    if not get_metadata_db().release_device(device_id, user["id"]):
        raise HTTPException(status_code=404, detail="Device not found")
    return {"released": device_id}
