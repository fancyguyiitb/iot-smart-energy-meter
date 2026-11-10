"""Server tests: isolated data dir, fast password hashing, a provisioned test device."""

import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_tmp = tempfile.mkdtemp(prefix="voltix-srv-")
os.environ.update({
    "SECRET_KEY": "test-secret-key-that-is-long-enough-123456",
    "DATA_DIR": _tmp,
    "STORAGE_BACKEND": "sqlite",
    "PASSWORD_HASH_ITERATIONS": "1000",
    "COMMAND_TIMEOUT_SECONDS": "3",
})
sys.path.insert(0, str(ROOT / "src" / "Server"))

from cryptography.fernet import Fernet  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

DEVICE_ID = "meter-test"
DEVICE_KEY = "device-key-for-tests"
CLAIM_KEY = Fernet.generate_key().decode()
DEVICE_HEADERS = {"X-Device-Id": DEVICE_ID, "X-Device-Key": DEVICE_KEY}


@pytest.fixture(scope="session")
def client():
    import main
    from utils.database import get_metadata_db
    from utils.security import hash_device_key

    get_metadata_db().upsert_device(DEVICE_ID, hash_device_key(DEVICE_KEY), CLAIM_KEY, "Test meter")
    get_metadata_db().upsert_device("someone-elses", hash_device_key("other"), Fernet.generate_key().decode())
    with TestClient(main.app) as c:
        yield c


def claim_code(nonce: str, age_s: int = 0, key: str = CLAIM_KEY, device_id: str = DEVICE_ID) -> str:
    import time

    token = Fernet(key.encode()).encrypt_at_time(f"{device_id}::{nonce}".encode(), int(time.time()) - age_s)
    return f"VOLTIX1:{device_id}:{token.decode()}"


@pytest.fixture(scope="session")
def user_token(client):
    r = client.post("/auth/sign-up", json={"username": "alice", "password": "correct-horse", "claim_code": claim_code("n-alice")})
    assert r.status_code == 201, r.text
    return r.json()["access_token"]


@pytest.fixture()
def auth(user_token):
    return {"Authorization": f"Bearer {user_token}"}
