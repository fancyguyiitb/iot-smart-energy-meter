"""Firmware tests run against a throw-away data dir and the in-process virtual chip."""

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_tmp = tempfile.mkdtemp(prefix="voltix-fw-")
os.environ.update({
    "DATA_DIR": _tmp,
    "VOLTIX_HAL": "virtual",
    "VOLTIX_DEVICE_ENV": str(Path(_tmp) / "none.env"),  # never pick up a real device.env
    "DEVICE_ID": "test-meter",
    "DEVICE_KEY": "test-key",
    "CLAIM_KEY": "x" * 43 + "=",  # replaced in test_claim
})
for p in (ROOT / "src" / "RPi", ROOT / "src" / "VirtualDevice"):
    sys.path.insert(0, str(p))
