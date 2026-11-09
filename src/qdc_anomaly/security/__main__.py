"""Command line for the local integrity experiments.

Defaults keep the key, baselines, and audit log under ``security/local/`` next to
the inventory file. That folder is ignored by git and is outside the asset root,
but it is still ordinary files on this machine: whoever can read the key can
authenticate anything.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from qdc_anomaly.security.access_policy import AccessPolicy
from qdc_anomaly.security.assets import AssetInventory
from qdc_anomaly.security.audit import AuditLog, AuditRecord
from qdc_anomaly.security.integrity import (
    AuthenticationError,
    BaselineStore,
    generate_key_file,
    load_key,
    seal_evidence,
    verify_sealed_evidence,
)
from qdc_anomaly.security.store import (
    AccessDenied,
    GuardedStore,
    IntegrityFailure,
    Workload,
    default_store_paths,
)


def build_store(args) -> GuardedStore:
    inventory = AssetInventory.load(args.inventory)
    paths = default_store_paths(Path(args.inventory))
    return GuardedStore(
        inventory=inventory,
        policy=AccessPolicy.load(args.policy or paths["policy"]),
        baselines=BaselineStore(Path(args.baselines or paths["baselines"])),
        audit=AuditLog(Path(args.audit or paths["audit"])),
        key=load_key(Path(args.key_file or paths["key"]), inventory),
    )


def emit(payload: dict, out: str | None) -> None:
    text = json.dumps(payload, indent=2, allow_nan=False)
    if out:
        Path(out).write_text(text, encoding="utf-8")
    else:
        print(text)


def access_demo(store: GuardedStore) -> dict:
    """The three required demonstrations, each recorded in the audit log."""
    steps = []

    def attempt(label, call):
        try:
            result = call()
            steps.append({"step": label, "result": "allowed", "detail": result})
        except AccessDenied as exc:
            steps.append({"step": label, "result": "denied", "detail": str(exc)})
        except IntegrityFailure as exc:
            steps.append({"step": label, "result": "integrity-failure", "detail": str(exc)})

    workload = Workload(node_id="compute-01", job_id="approved-training-01")
    attempt(
        "authorized read by training-job",
        lambda: f"{len(store.read('training-job', 'dataset:telemetry-sample', workload))} bytes",
    )
    attempt(
        "unauthorized write by training-job",
        lambda: store.write("training-job", "model:isolation-forest-reference", b"x", workload),
    )
    attempt(
        "request outside the asset scope",
        lambda: store.read("training-job", "../../lab/settings.json", workload),
    )
    return {"steps": steps, "audit_log": str(store.audit.path)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m qdc_anomaly.security", description=__doc__)
    parser.add_argument("--inventory", default="security/inventory.json")
    parser.add_argument("--policy", help="Defaults to policy.json beside the inventory")
    parser.add_argument("--key-file", help="Defaults to local/integrity.key beside the inventory")
    parser.add_argument("--baselines", help="Defaults to local/baselines beside the inventory")
    parser.add_argument("--audit", help="Defaults to local/audit.jsonl beside the inventory")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("keygen", help="Create a new key file; refuses to overwrite")
    baseline = commands.add_parser("baseline", help="Approve the current assets as a new version")
    baseline.add_argument("--approved-by", required=True, help="Actor label with approve rights")
    baseline.add_argument("--note", default="")
    verify = commands.add_parser("verify", help="Compare assets with the approved baseline")
    verify.add_argument("--actor", default="auditor")
    verify.add_argument("--out")
    commands.add_parser("access-demo", help="Run the authorized/denied/out-of-scope requests")
    seal = commands.add_parser("seal-evidence", help="Authenticate an exported snapshot")
    seal.add_argument("--input", required=True)
    seal.add_argument("--out", required=True)
    seal.add_argument("--sealed-by", default="collector")
    check = commands.add_parser("verify-evidence", help="Verify a sealed bundle")
    check.add_argument("--input", required=True)
    check.add_argument("--out", help="Write the verified snapshot here for replay")
    args = parser.parse_args(argv)

    paths = default_store_paths(Path(args.inventory))
    if args.command == "keygen":
        target = Path(args.key_file or paths["key"])
        generate_key_file(target)
        print(f"Key written to {target}. Keep it out of git and away from worker mounts.")
        return 0

    store = build_store(args)
    if args.command == "baseline":
        try:
            manifest = store.approve_baseline(args.approved_by, args.note)
        except AccessDenied as exc:
            print(f"Denied: {exc}", file=sys.stderr)
            return 2
        print(
            f"Approved baseline version {manifest['baseline_version']} "
            f"covering {len(manifest['assets'])} assets -> {store.baselines.pointer_path}"
        )
        return 0
    if args.command == "verify":
        try:
            report = store.verify(args.actor)
        except IntegrityFailure as exc:
            emit({"passed": False, "error": str(exc)}, args.out)
            return 1
        emit(report.to_dict(), args.out)
        return 0 if report.passed else 1
    if args.command == "access-demo":
        emit(access_demo(store), None)
        return 0
    if args.command == "seal-evidence":
        snapshot = json.loads(Path(args.input).read_text(encoding="utf-8"))
        bundle = seal_evidence(snapshot, store.key, args.sealed_by)
        Path(args.out).write_text(json.dumps(bundle, allow_nan=False), encoding="utf-8")
        store.audit.record(
            AuditRecord(
                actor=args.sealed_by,
                operation="seal",
                decision="n/a",
                outcome="ok",
                evidence_ids=[f"sha256:{bundle['evidence_sha256'][:16]}"],
                detail=f"sealed {bundle['record_count']} records from run {bundle['run_id']}",
            )
        )
        print(f"Sealed {bundle['record_count']} records -> {args.out}")
        return 0
    if args.command == "verify-evidence":
        bundle = json.loads(Path(args.input).read_text(encoding="utf-8"))
        try:
            snapshot = verify_sealed_evidence(bundle, store.key)
        except AuthenticationError as exc:
            store.audit.record(
                AuditRecord(
                    actor="auditor",
                    operation="verify-evidence",
                    decision="n/a",
                    outcome="auth-failed",
                    detail=str(exc),
                )
            )
            emit({"verified": False, "error": str(exc)}, None)
            return 1
        store.audit.record(
            AuditRecord(
                actor="auditor",
                operation="verify-evidence",
                decision="n/a",
                outcome="ok",
                evidence_ids=[f"sha256:{bundle['evidence_sha256'][:16]}"],
                detail=f"verified bundle for run {bundle.get('run_id')}",
            )
        )
        if args.out:
            emit(snapshot, args.out)
        print(
            json.dumps(
                {
                    "verified": True,
                    "run_id": bundle.get("run_id"),
                    "record_count": bundle.get("record_count"),
                    "sealed_by": bundle.get("sealed_by"),
                    "note": "Authenticity of the bundle only; not proof the sensors were truthful.",
                }
            )
        )
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
