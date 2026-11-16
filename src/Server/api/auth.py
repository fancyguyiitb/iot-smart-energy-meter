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

from datetime import datetime, timedelta, timezone

from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request

from api.dependencies import get_current_user
from api.services import hub
from config import settings
from utils.database import ClaimError, get_metadata_db
from utils.mailer import send_mail
from utils.models import (
    ChangePasswordRequest,
    ClaimRequest,
    EmailUpdateRequest,
    ForgotPasswordRequest,
    LoginRequest,
    ResetPasswordRequest,
    SignUpRequest,
)
from utils.ratelimit import (
    FORGOT_PER_ACCOUNT,
    FORGOT_PER_IP,
    LOGIN_FAILURES,
    LOGIN_PER_IP,
    RESET_PER_IP,
    SIGNUP_PER_IP,
    client_ip,
    limiter,
    too_many,
)
from utils.security import (
    create_access_token,
    hash_password,
    hash_reset_token,
    new_reset_token,
    password_problem,
    verify_password,
)

router = APIRouter()
CLAIM_PREFIX = "VOLTIX1"
_dummy_hash: str | None = None
FORGOT_REPLY = {"message": "If that account has an email address, a reset link is on its way."}


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


def _check_password(password: str, username: str) -> None:
    problem = password_problem(password, username)
    if problem:
        raise HTTPException(status_code=400, detail=problem)


def _verify_or_count(username: str, password: str, stored_hash: str | None) -> bool:
    """Check a password, enforcing the per-account lockout. Locks apply to the *name* typed,
    whether or not the account exists, so lockouts don't reveal which usernames are real."""
    global _dummy_hash
    wait = limiter.locked(LOGIN_FAILURES, username)
    if wait:
        raise too_many(wait)
    if stored_hash is None:
        # Spend the same time as a real check so response timing doesn't reveal usernames.
        _dummy_hash = _dummy_hash or hash_password("not-a-real-password")
        verify_password(password, _dummy_hash)
        ok = False
    else:
        ok = verify_password(password, stored_hash)
    if ok:
        limiter.reset(LOGIN_FAILURES, username)
    else:
        limiter.record_failure(LOGIN_FAILURES, username)
    return ok


@router.post("/sign-up", status_code=201)
def sign_up(req: SignUpRequest, request: Request):
    limiter.hit(SIGNUP_PER_IP, client_ip(request))
    device_id, nonce = verify_claim_code(req.claim_code)
    _check_password(req.password, req.username)
    password_hash = hash_password(req.password)
    try:
        user_id = get_metadata_db().claim(device_id, nonce, new_user=(req.username, password_hash, req.email))
    except ClaimError as e:
        raise HTTPException(status_code=e.status, detail=e.detail)
    return {
        "message": "User created successfully",
        "access_token": create_access_token(user_id, req.username, 0),
        "token_type": "bearer",
        "device_id": device_id,
    }


@router.post("/login")
def login(req: LoginRequest, request: Request):
    limiter.hit(LOGIN_PER_IP, client_ip(request))
    user = get_metadata_db().get_user_by_username(req.username)
    if not _verify_or_count(req.username, req.password, user["password_hash"] if user else None):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return {"access_token": create_access_token(user["id"], user["username"], user["token_version"]),
            "token_type": "bearer"}


@router.get("/me")
def me(user: dict = Depends(get_current_user)):
    devices = get_metadata_db().devices_for_user(user["id"])
    return {"id": user["id"], "username": user["username"], "email": user["email"],
            "devices": [d | {"online": hub.is_online(d["device_id"])} for d in devices]}


# ---------------------------------------------------------------------- password management
@router.post("/forgot-password", status_code=202)
def forgot_password(req: ForgotPasswordRequest, request: Request, background: BackgroundTasks):
    """Email a single-use reset link. The reply is identical whether or not the account
    exists or has an email, and the email is sent after the response, so neither the
    message nor the timing reveals which accounts exist."""
    limiter.hit(FORGOT_PER_IP, client_ip(request))
    db = get_metadata_db()
    ident = req.identifier.strip()
    user = db.get_user_by_email(ident) if "@" in ident else db.get_user_by_username(ident)
    if not user or not user.get("email") or limiter.retry_after(FORGOT_PER_ACCOUNT, str(user["id"])):
        return FORGOT_REPLY
    limiter.record_failure(FORGOT_PER_ACCOUNT, str(user["id"]))  # counts requests per account
    token, token_hash = new_reset_token()
    expires = datetime.now(timezone.utc) + timedelta(minutes=settings.reset_token_ttl_minutes)
    db.create_reset_token(user["id"], token_hash, expires)
    link = f"{settings.public_app_url}#/reset?token={token}"
    background.add_task(
        send_mail, user["email"], "Reset your Voltix password",
        f"Hi {user['username']},\n\nSomeone asked to reset the password of your Voltix account. "
        f"If it was you, open this link within {settings.reset_token_ttl_minutes} minutes:\n\n{link}\n\n"
        "The link works once. If you didn't ask for this, ignore this email; your password is unchanged.\n")
    return FORGOT_REPLY


@router.post("/reset-password")
def reset_password(req: ResetPasswordRequest, request: Request, background: BackgroundTasks):
    limiter.hit(RESET_PER_IP, client_ip(request))
    db = get_metadata_db()
    token_hash = hash_reset_token(req.token)
    user_id = db.consume_reset_token(token_hash)  # single use: two concurrent attempts can't both win
    if user_id is None:
        raise HTTPException(status_code=400, detail="This reset link is invalid, expired or already used. "
                                                    "Request a new one.")
    user = db.get_user(user_id)
    problem = password_problem(req.new_password, user["username"])
    if problem:
        # Give the link back (briefly) so a rejected weak password doesn't burn it.
        db.create_reset_token(user_id, token_hash, datetime.now(timezone.utc) + timedelta(minutes=5))
        raise HTTPException(status_code=400, detail=problem)
    db.set_password(user_id, hash_password(req.new_password))  # also logs out every session
    limiter.reset(LOGIN_FAILURES, user["username"])
    if user.get("email"):
        background.add_task(send_mail, user["email"], "Your Voltix password was changed",
                            f"Hi {user['username']},\n\nYour password was just reset and all devices were "
                            "logged out. If this wasn't you, reset it again immediately.\n")
    return {"message": "Password changed. Log in with your new password."}


@router.post("/change-password")
def change_password(req: ChangePasswordRequest, user: dict = Depends(get_current_user)):
    db = get_metadata_db()
    full = db.get_user_by_username(user["username"])
    if not _verify_or_count(user["username"], req.current_password, full["password_hash"]):
        raise HTTPException(status_code=400, detail="Current password is wrong")
    _check_password(req.new_password, user["username"])
    version = db.set_password(user["id"], hash_password(req.new_password))
    # Every other session is now logged out; hand this one a fresh token.
    return {"message": "Password changed",
            "access_token": create_access_token(user["id"], user["username"], version), "token_type": "bearer"}


@router.post("/email")
def update_email(req: EmailUpdateRequest, user: dict = Depends(get_current_user)):
    db = get_metadata_db()
    full = db.get_user_by_username(user["username"])
    if not _verify_or_count(user["username"], req.current_password, full["password_hash"]):
        raise HTTPException(status_code=400, detail="Current password is wrong")
    try:
        db.set_email(user["id"], req.email)
    except ClaimError as e:
        raise HTTPException(status_code=e.status, detail=e.detail)
    return {"email": req.email.lower() if req.email else None}


@router.post("/logout-all")
def logout_all(user: dict = Depends(get_current_user)):
    """End every session of this account, including the current one."""
    get_metadata_db().bump_token_version(user["id"])
    return {"message": "Logged out everywhere"}


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
