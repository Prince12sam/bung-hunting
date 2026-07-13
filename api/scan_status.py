"""In-memory "what stage is this scan on right now" tracker.

Single-user local tool, so an in-memory dict is enough — no need for
Postgres/Redis just to answer "which of the 8 stages is running." This
exists because a `scan` request is one long blocking HTTP call with zero
visibility into progress otherwise; found the hard way today that silence
for 10+ minutes is indistinguishable from a hang without this.
"""

import threading
import time

_lock = threading.Lock()
_status: dict[str, dict] = {}


def set_stage(target: str, stage: str, index: int, total: int) -> None:
    with _lock:
        _status[target] = {
            "stage": stage,
            "index": index,
            "total": total,
            "started_at": time.monotonic(),
        }


def clear(target: str) -> None:
    with _lock:
        _status.pop(target, None)


def get(target: str) -> dict | None:
    with _lock:
        info = _status.get(target)
        if info is None:
            return None
        return {**info, "elapsed_seconds": time.monotonic() - info["started_at"]}
