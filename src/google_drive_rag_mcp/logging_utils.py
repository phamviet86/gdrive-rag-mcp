from __future__ import annotations

import json
import sys
from typing import Any


def emit_stderr(event: str, *, level: str = "error", **fields: Any) -> None:
    """Write one machine-readable operational event without configuring global logging."""
    payload = {"level": level, "event": event, **fields}
    sys.stderr.write(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str) + "\n")
    sys.stderr.flush()
