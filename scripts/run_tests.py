"""Run both test suites. They run in separate processes because the firmware and the
server each have a top-level ``config`` module.

    python scripts/run_tests.py
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
codes = [subprocess.call([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(ROOT / "tests" / suite)])
         for suite in ("firmware", "server")]
sys.exit(max(codes))
