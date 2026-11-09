"""Probe what the worker process can actually do to the declared assets.

The access policy in ``qdc_anomaly.security`` only governs calls made through the
guarded store. This probe asks the operating system instead: can this process read
a dataset, write into the model folder, or open the integrity key? In the Compose
lab the assets are mounted read-only and the key is not mounted at all, so the
expected answers are yes, no, and "not present". The results are recorded as plain
observations and are never used as detection inputs.
"""

from __future__ import annotations

import errno
import os
import time
from pathlib import Path

PROBE_NAME = ".boundary-probe"
READ_SAMPLE = "datasets/telemetry-sample.csv"
WRITE_TARGET_DIR = "models"


def _outcome(action, path, result, detail=""):
    return {"action": action, "path": str(path), "result": result, "detail": detail}


def probe_boundary(asset_root: str | Path, key_path: str | Path) -> dict:
    """Run the three checks and return one record describing what happened."""
    root = Path(asset_root)
    checks = []

    sample = root / READ_SAMPLE
    try:
        size = len(sample.read_bytes())
        checks.append(_outcome("read-dataset", sample, "allowed", f"{size} bytes"))
    except OSError as exc:
        checks.append(_outcome("read-dataset", sample, "failed", exc.strerror or str(exc)))

    target = root / WRITE_TARGET_DIR / PROBE_NAME
    try:
        with target.open("wb") as handle:
            handle.write(b"probe")
    except OSError as exc:
        name = errno.errorcode.get(exc.errno, "OSError")
        denied = exc.errno in {errno.EROFS, errno.EACCES, errno.EPERM}
        checks.append(_outcome("write-model-dir", target, "denied" if denied else "failed", name))
    else:
        # The mount is writable. Remove the probe so it does not linger as an
        # unexpected file, and report the gap plainly.
        try:
            os.remove(target)
            cleanup = "probe removed"
        except OSError as exc:
            cleanup = f"probe left behind: {exc.strerror}"
        checks.append(_outcome("write-model-dir", target, "allowed", cleanup))

    key = Path(key_path)
    try:
        with key.open("rb"):
            pass
        checks.append(_outcome("open-key", key, "allowed", "key is reachable; boundary gap"))
    except FileNotFoundError:
        checks.append(_outcome("open-key", key, "absent", "not mounted"))
    except OSError as exc:
        checks.append(_outcome("open-key", key, "denied", exc.strerror or str(exc)))

    return {
        "ts": time.time(),
        "source": "os-boundary",
        "note": "Operating-system answer for this process; not a detection input",
        "checks": checks,
        "enforced": _is_enforced(checks),
    }


def _is_enforced(checks: list[dict]) -> bool:
    by_action = {c["action"]: c["result"] for c in checks}
    return (
        by_action.get("read-dataset") == "allowed"
        and by_action.get("write-model-dir") == "denied"
        and by_action.get("open-key") in {"absent", "denied"}
    )
