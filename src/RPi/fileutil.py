"""Small file helpers shared by the firmware processes."""

from __future__ import annotations

import os
import time
from pathlib import Path


def atomic_write_text(path: Path, text: str, retries: int = 20) -> None:
    """Write via a temp file + rename, so readers never see a half-written file.

    On Windows the rename fails while another process has the target open (e.g. the
    failure logger reading it), so retry briefly; on Linux the rename is always atomic.
    """
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text)
    for attempt in range(retries):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == retries - 1:
                tmp.unlink(missing_ok=True)
                raise
            time.sleep(0.01)
