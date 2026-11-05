"""Run integrity experiments on a new disposable copy, never on the declared fixtures."""

from __future__ import annotations

import argparse
import json
import platform
import shutil
from datetime import datetime, timezone
from pathlib import Path

from qdc_anomaly.security.access_policy import AccessPolicy
from qdc_anomaly.security.assets import AssetInventory
from qdc_anomaly.security.audit import AuditLog
from qdc_anomaly.security.integrity import (
    AuthenticationError,
    BaselineStore,
    generate_key_file,
    load_key,
    seal_evidence,
    verify_sealed_evidence,
)
from qdc_anomaly.security.store import AccessDenied, GuardedStore


def run(destination: Path) -> dict:
    destination.mkdir(parents=True, exist_ok=False)
    source = Path(__file__).resolve().parents[1] / "security"
    shutil.copytree(source / "assets", destination / "assets")
    shutil.copy(source / "inventory.json", destination / "inventory.json")
    inventory = AssetInventory.load(destination / "inventory.json")
    local = destination / "local"
    generate_key_file(local / "integrity.key")
    store = GuardedStore(
        inventory,
        AccessPolicy.load(source / "policy.json"),
        BaselineStore(local / "baselines"),
        AuditLog(local / "audit.jsonl"),
        load_key(local / "integrity.key", inventory),
    )
    store.approve_baseline("publisher", "explicit initial baseline for disposable experiment")
    unchanged = store.verify()
    assert unchanged.passed

    dataset = inventory.resolve("dataset:telemetry-sample")
    original = dataset.read_bytes()
    dataset.write_bytes(original + b"\nmodified experiment data\n")
    modified = store.verify()
    assert not modified.passed
    assert modified.results["dataset:telemetry-sample"] == "modified"
    dataset.write_bytes(original)

    planted = inventory.root / "models" / "planted.bin"
    planted.write_bytes(b"unexpected experiment file")
    unexpected = store.verify()
    assert not unexpected.passed and unexpected.unexpected == ["models/planted.bin"]
    planted.unlink()

    assert store.read("training-job", "dataset:telemetry-sample") == original
    try:
        store.write("training-job", "model:isolation-forest-reference", b"not allowed")
    except AccessDenied:
        denied = True
    else:
        raise AssertionError("Unauthorized write was accepted")

    snapshot = json.loads(inventory.resolve("evidence:sample-export").read_text())
    sealed = seal_evidence(snapshot, store.key, "collector")
    (local / "sealed.json").write_text(json.dumps(sealed), encoding="utf-8")
    assert verify_sealed_evidence(sealed, store.key) == snapshot
    changed = json.loads(json.dumps(sealed))
    changed["snapshot"]["evidence"].append({"id": "planted"})
    try:
        verify_sealed_evidence(changed, store.key)
    except AuthenticationError as error:
        rejection = str(error)
    else:
        raise AssertionError("Altered evidence was accepted")

    assert store.verify().passed
    assert store.baselines.latest_version() == 1
    report = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "machine": platform.platform(),
        "python": platform.python_version(),
        "unchanged": unchanged.to_dict(),
        "modified_dataset": modified.to_dict(),
        "planted_file": unexpected.to_dict(),
        "authorized_read_bytes": len(original),
        "unauthorized_write_denied": denied,
        "sealed_bundle_verified": True,
        "altered_bundle_rejected": rejection,
        "restored_assets_pass": True,
        "baseline_version_after_checks": store.baselines.latest_version(),
        "live_boundary": "not exercised by this local experiment",
        "live_findings": "not exercised by this local experiment",
    }
    (destination / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out", type=Path, required=True, help="New directory; existing paths refused"
    )
    args = parser.parse_args()
    print(json.dumps(run(args.out), indent=2))


if __name__ == "__main__":
    main()
