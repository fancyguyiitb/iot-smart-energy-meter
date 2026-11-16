"""Rate limiting, lockout, password policy, reset, change password, logout everywhere."""

import re
from datetime import datetime, timedelta, timezone

from conftest import claim_code


def _outbox_link(to: str) -> str:
    """Newest reset link emailed to ``to`` (local dev writes emails to DATA_DIR/outbox)."""
    import email

    from utils.mailer import outbox_dir

    files = sorted(outbox_dir().glob(f"*-{to}.eml"))
    assert files, "no email written"
    body = email.message_from_bytes(files[-1].read_bytes()).get_payload(decode=True).decode()
    return re.search(r"#/reset\?token=([A-Za-z0-9_-]+)", body).group(1)


# ------------------------------------------------------------------ rate limiting / lockout
def test_account_locks_after_five_wrong_passwords(client, new_user):
    u = new_user()
    for _ in range(5):
        assert client.post("/auth/login", json={"username": u["username"], "password": "wrong-guess-1"}).status_code == 401
    r = client.post("/auth/login", json={"username": u["username"], "password": u["password"]})
    assert r.status_code == 429 and "Retry-After" in r.headers  # locked even with the right password


def test_lockout_doesnt_reveal_whether_an_account_exists(client):
    for _ in range(5):
        client.post("/auth/login", json={"username": "ghost-user", "password": "wrong-guess-1"})
    assert client.post("/auth/login", json={"username": "ghost-user", "password": "x"}).status_code == 429


def test_successful_login_clears_failures(client, new_user):
    u = new_user()
    for _ in range(4):
        client.post("/auth/login", json={"username": u["username"], "password": "wrong-guess-1"})
    assert client.post("/auth/login", json={"username": u["username"], "password": u["password"]}).status_code == 200
    for _ in range(4):  # the counter started again from zero
        assert client.post("/auth/login", json={"username": u["username"], "password": "wrong-guess-1"}).status_code == 401


def test_login_rate_limited_per_ip(client):
    codes = [client.post("/auth/login", json={"username": f"spray{i}", "password": "wrong-guess-1"}).status_code
             for i in range(21)]
    assert codes[:20] == [401] * 20 and codes[20] == 429  # password spraying across accounts


def test_signup_rate_limited_per_ip(client):
    codes = [client.post("/auth/sign-up", json={"username": f"x{i}aa", "password": "good-pass-123",
                                                 "claim_code": "VOLTIX1:nope:nope"}).status_code for i in range(11)]
    assert codes[-1] == 429


# ------------------------------------------------------------------ password policy
def test_weak_passwords_rejected(client, new_user):
    u = new_user()
    for bad in ("password123", "short", f"{u['username']}-2024"):
        r = client.post("/auth/change-password", headers=u["headers"],
                        json={"current_password": u["password"], "new_password": bad})
        assert r.status_code in (400, 422), bad


# ------------------------------------------------------------------ reset flow
def test_password_reset_end_to_end(client, new_user):
    u = new_user(email="Owner@Example.com")
    r = client.post("/auth/forgot-password", json={"identifier": "owner@example.com"})
    assert r.status_code == 202
    token = _outbox_link("owner@example.com")

    r = client.post("/auth/reset-password", json={"token": token, "new_password": "brand-new-pass-7"})
    assert r.status_code == 200
    assert client.get("/auth/me", headers=u["headers"]).status_code == 401  # old sessions ended
    assert client.post("/auth/reset-password", json={"token": token, "new_password": "another-pass-8"}).status_code == 400
    assert client.post("/auth/login", json={"username": u["username"], "password": "brand-new-pass-7"}).status_code == 200
    assert client.post("/auth/login", json={"username": u["username"], "password": u["password"]}).status_code == 401


def test_forgot_password_reply_is_identical_for_unknown_accounts(client, new_user):
    u = new_user()  # no email on file
    replies = {client.post("/auth/forgot-password", json={"identifier": ident}).text
               for ident in ("nobody@example.com", "no-such-user", u["username"])}
    assert len(replies) == 1  # nothing to learn about which accounts exist


def test_only_a_hash_of_the_reset_token_is_stored(client, new_user):
    import config
    import sqlite3

    new_user(email="hash@example.com")
    client.post("/auth/forgot-password", json={"identifier": "hash@example.com"})
    token = _outbox_link("hash@example.com")
    with sqlite3.connect(config.settings.metadata_db) as c:
        stored = [r[0] for r in c.execute("SELECT token_hash FROM reset_tokens")]
    assert token not in stored and len(stored[-1]) == 64


def test_expired_reset_link_is_rejected(client, new_user):
    from utils.database import get_metadata_db
    from utils.security import new_reset_token

    u = new_user()
    user = get_metadata_db().get_user_by_username(u["username"])
    token, token_hash = new_reset_token()
    get_metadata_db().create_reset_token(user["id"], token_hash, datetime.now(timezone.utc) - timedelta(minutes=1))
    assert client.post("/auth/reset-password", json={"token": token, "new_password": "new-pass-1234"}).status_code == 400


def test_weak_password_doesnt_burn_the_reset_link(client, new_user):
    new_user(email="keep@example.com")
    client.post("/auth/forgot-password", json={"identifier": "keep@example.com"})
    token = _outbox_link("keep@example.com")
    assert client.post("/auth/reset-password", json={"token": token, "new_password": "password123"}).status_code == 400
    assert client.post("/auth/reset-password", json={"token": token, "new_password": "solid-pass-99"}).status_code == 200


def test_reset_requests_are_rate_limited_per_account(client, new_user):
    from utils.mailer import outbox_dir

    new_user(email="limit@example.com")
    for _ in range(5):
        client.post("/auth/forgot-password", json={"identifier": "limit@example.com"})
    assert len(list(outbox_dir().glob("*-limit@example.com.eml"))) == 3  # max 3 emails/hour


# ------------------------------------------------------------------ sessions
def test_change_password_logs_out_other_sessions(client, new_user):
    u = new_user()
    other = client.post("/auth/login", json={"username": u["username"], "password": u["password"]}).json()
    r = client.post("/auth/change-password", headers=u["headers"],
                    json={"current_password": u["password"], "new_password": "changed-pass-42"})
    assert r.status_code == 200
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {other['access_token']}"}).status_code == 401
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {r.json()['access_token']}"}).status_code == 200


def test_change_password_requires_current_password(client, new_user):
    u = new_user()
    r = client.post("/auth/change-password", headers=u["headers"],
                    json={"current_password": "not-it-at-all", "new_password": "changed-pass-42"})
    assert r.status_code == 400


def test_logout_everywhere(client, new_user):
    u = new_user()
    assert client.post("/auth/logout-all", headers=u["headers"]).status_code == 200
    assert client.get("/auth/me", headers=u["headers"]).status_code == 401


def test_email_must_be_unique(client, new_user):
    new_user(email="dup@example.com")
    v = new_user()
    r = client.post("/auth/email", headers=v["headers"], json={"current_password": v["password"], "email": "DUP@example.com"})
    assert r.status_code == 409
