"""Integrity, policy, and scope checks on disposable sample assets."""

import json
import os
import random
import time

import pytest

from qdc_anomaly.lab.config import LabConfig
from qdc_anomaly.lab.detection import normalize_flows
from qdc_anomaly.lab.framework import SecurityFramework, TelemetryBatch
from qdc_anomaly.lab.replay import replay
from qdc_anomaly.lab.simulator import gpu_sample
from qdc_anomaly.security.__main__ import main as security_cli
from qdc_anomaly.security.access_policy import AccessPolicy, AccessRequest
from qdc_anomaly.security.assets import AssetInventory, ScopeError
from qdc_anomaly.security.audit import AuditLog, AuditRecord
from qdc_anomaly.security.findings import audit_source, normalize_security
from qdc_anomaly.security.integrity import (
    AuthenticationError,
    BaselineStore,
    generate_key_file,
    load_key,
    seal_evidence,
    verify_sealed_evidence,
)
from qdc_anomaly.security.store import AccessDenied, GuardedStore, IntegrityFailure, Workload

POLICY = {
    "schema_version": 1,
    "actors": {
        "training-job": {"read": ["dataset:*", "model:ref"], "write": []},
        "publisher": {"read": ["*"], "write": ["model:*", "dataset:*"], "approve": True},
        "auditor": {"read": ["*"]},
    },
}


def write_inventory(folder, assets):
    (folder / "assets").mkdir(exist_ok=True)
    (folder / "inventory.json").write_text(
        json.dumps({"schema_version": 1, "root": "assets", "assets": assets})
    )
    return folder / "inventory.json"


@pytest.fixture
def lab(tmp_path):
    """A disposable inventory, policy, key, and store with one approved baseline."""
    root = tmp_path / "project"
    root.mkdir()
    (root / "assets" / "data").mkdir(parents=True)
    (root / "assets" / "models").mkdir()
    (root / "assets" / "data" / "sample.csv").write_bytes(b"a,b\n1,2\n")
    (root / "assets" / "models" / "ref.json").write_text('{"threshold": 0.5}')
    inventory_path = write_inventory(
        root,
        [
            {
                "id": "dataset:sample",
                "kind": "dataset",
                "path": "data/sample.csv",
                "approved_version": "v1",
            },
            {
                "id": "model:ref",
                "kind": "model",
                "path": "models/ref.json",
                "approved_version": "v1",
            },
        ],
    )
    (root / "policy.json").write_text(json.dumps(POLICY))
    key_path = tmp_path / "outside" / "integrity.key"
    generate_key_file(key_path)
    inventory = AssetInventory.load(inventory_path)
    store = GuardedStore(
        inventory=inventory,
        policy=AccessPolicy.load(root / "policy.json"),
        baselines=BaselineStore(tmp_path / "outside" / "baselines"),
        audit=AuditLog(tmp_path / "outside" / "audit.jsonl"),
        key=load_key(key_path, inventory),
    )
    store.approve_baseline("publisher", "initial")
    return store


def test_unchanged_assets_pass_and_audit_records_the_check(lab):
    report = lab.verify()
    assert report.passed and report.baseline_version == 1
    assert set(report.results.values()) == {"ok"}
    last = lab.audit.read()[-1]
    assert (last["operation"], last["outcome"], last["baseline_version"]) == ("verify", "ok", 1)
    assert "key" not in json.dumps(last).lower().replace("key_id", "")


def test_modified_dataset_fails_without_regenerating_the_baseline(lab):
    (lab.inventory.root / "data" / "sample.csv").write_text("a,b\n9,9\n")
    report = lab.verify()
    assert not report.passed and report.results["dataset:sample"] == "modified"
    # Verification must not quietly accept the change: the version is unchanged.
    assert lab.baselines.latest_version() == 1
    assert lab.verify().results["dataset:sample"] == "modified"


def test_missing_and_unexpected_files_are_reported(lab):
    (lab.inventory.root / "models" / "ref.json").unlink()
    (lab.inventory.root / "models" / "planted.bin").write_bytes(b"\x00")
    report = lab.verify()
    assert report.results["model:ref"] == "missing"
    assert report.unexpected == ["models/planted.bin"]
    outcomes = {r["outcome"] for r in lab.audit.read() if r["operation"] == "verify"}
    assert {"missing", "unexpected"} <= outcomes


def test_modified_model_is_rejected_before_it_is_consumed(lab):
    assert lab.read("training-job", "model:ref") == b'{"threshold": 0.5}'
    (lab.inventory.root / "models" / "ref.json").write_text('{"threshold": 0.0}')
    with pytest.raises(IntegrityFailure, match="does not match baseline 1"):
        lab.read("training-job", "model:ref")
    last = lab.audit.read()[-1]
    assert (last["outcome"], last["asset_id"]) == ("modified", "model:ref")


def test_policy_allows_reads_and_denies_unauthorized_writes(lab):
    data = lab.read("training-job", "dataset:sample")
    assert data == b"a,b\n1,2\n"
    with pytest.raises(AccessDenied, match="no write grant"):
        lab.write("training-job", "model:ref", b"replaced")
    assert (lab.inventory.root / "models" / "ref.json").read_text() == '{"threshold": 0.5}'
    with pytest.raises(AccessDenied):
        lab.read("unknown-actor", "dataset:sample")
    decisions = [(r["operation"], r["decision"]) for r in lab.audit.read()[-3:]]
    assert decisions == [("read", "allow"), ("write", "deny"), ("read", "deny")]


def test_requests_outside_the_declared_scope_are_denied(lab):
    for bad_id in ("../policy.json", "dataset:other", "/etc/hosts", ""):
        with pytest.raises(AccessDenied, match="outside the declared inventory scope"):
            lab.read("publisher", bad_id)
    # Policy evaluation alone has no side effects and is deny by default.
    decision = lab.policy.evaluate(AccessRequest("auditor", "write", "model:ref"), lab.inventory)
    assert not decision.allowed


@pytest.mark.parametrize("path", ["../secret.txt", "/abs/file", "data/../../x", "C:/win", "a\\b"])
def test_inventory_rejects_traversal_and_absolute_paths(tmp_path, path):
    inventory_path = write_inventory(
        tmp_path,
        [{"id": "dataset:x", "kind": "dataset", "path": path, "approved_version": "v1"}],
    )
    with pytest.raises(ScopeError):
        AssetInventory.load(inventory_path)


def test_symlink_escape_is_reported_not_followed(lab, tmp_path):
    outside = tmp_path / "outside" / "secret.txt"
    outside.write_text("secret")
    link = lab.inventory.root / "models" / "ref.json"
    link.unlink()
    try:
        os.symlink(outside, link)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are not available on this system")
    with pytest.raises(ScopeError):
        lab.inventory.resolve("model:ref")
    report = lab.verify()
    assert report.results["model:ref"] == "escaped" and not report.passed
    with pytest.raises(IntegrityFailure):
        lab.read("publisher", "model:ref")


def test_key_outside_root_is_enforced(lab, tmp_path):
    inside = lab.inventory.root / "integrity.key"
    inside.write_text("00" * 32)
    with pytest.raises(ScopeError, match="outside the inventory root"):
        load_key(inside, lab.inventory)
    with pytest.raises(ScopeError):
        BaselineStore(lab.inventory.root / "baselines").create(
            lab.inventory, lab.key, "publisher", ""
        )


def test_altered_manifest_pointer_or_wrong_key_fail_authentication(lab, tmp_path):
    manifest_path = lab.baselines.manifest_path(1)
    document = json.loads(manifest_path.read_text())
    document["assets"]["model:ref"]["sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(document))
    with pytest.raises(IntegrityFailure, match="does not match the pointer digest"):
        lab.verify()
    assert lab.audit.read()[-1]["outcome"] == "auth-failed"

    # Re-sign the altered manifest with no key: the pointer still catches it, and a
    # pointer edited without the key fails its own tag.
    pointer = json.loads(lab.baselines.pointer_path.read_text())
    pointer["baseline_version"] = 7
    lab.baselines.pointer_path.write_text(json.dumps(pointer))
    with pytest.raises(IntegrityFailure, match="does not match its authentication tag"):
        lab.verify()

    other_key = tmp_path / "other.key"
    generate_key_file(other_key)
    lab.baselines.pointer_path.write_text(json.dumps({**pointer, "baseline_version": 1}))
    manifest_path.write_bytes(manifest_path.read_bytes())
    wrong = GuardedStore(lab.inventory, lab.policy, lab.baselines, lab.audit, load_key(other_key))
    with pytest.raises(IntegrityFailure, match="different key|authentication tag"):
        wrong.verify()

    lab.baselines.pointer_path.unlink()
    with pytest.raises(IntegrityFailure, match="nothing is approved"):
        lab.read("training-job", "dataset:sample")


def test_old_manifest_with_valid_tag_is_not_the_approved_version(lab):
    old_bytes = lab.baselines.manifest_path(1).read_bytes()
    lab.write("publisher", "model:ref", b'{"threshold": 0.7}')
    assert lab.read("publisher", "dataset:sample")  # unaffected asset still verifies
    with pytest.raises(IntegrityFailure):
        lab.read("training-job", "model:ref")
    manifest = lab.approve_baseline("publisher", "model retrained")
    assert manifest["baseline_version"] == 2
    assert lab.verify().passed
    approval = [r for r in lab.audit.read() if r["operation"] == "approve"][-1]
    assert (approval["baseline_version"], approval["detail"]) == (2, "model retrained")
    # Copy the still-validly-tagged version 1 over version 2: the pointer digest rejects it.
    lab.baselines.manifest_path(2).write_bytes(old_bytes)
    with pytest.raises(IntegrityFailure, match="pointer digest"):
        lab.verify()


def test_workload_cannot_approve_its_own_baseline(lab):
    with pytest.raises(AccessDenied, match="may not approve"):
        lab.approve_baseline("training-job")
    assert lab.baselines.latest_version() == 1


def test_sealed_evidence_detects_edits_and_wrong_keys(lab, tmp_path):
    gpu = gpu_sample("baseline", random.Random(1), 100, "run")
    snapshot = {
        "schema_version": 1,
        "control": {"run_id": "run", "started_at": 0},
        "inventory": {"worker": "172.20.0.2"},
        "evidence": [{"id": "gpu-simulator:x", "ts": 100, "source": "gpu-simulator", "raw": gpu}],
    }
    bundle = seal_evidence(snapshot, lab.key, "collector")
    assert verify_sealed_evidence(json.loads(json.dumps(bundle)), lab.key) == snapshot
    edited = json.loads(json.dumps(bundle))
    edited["snapshot"]["evidence"][0]["raw"]["gpu_temp_c"] = 20.0
    with pytest.raises(AuthenticationError, match="does not match"):
        verify_sealed_evidence(edited, lab.key)
    relabeled = json.loads(json.dumps(bundle))
    relabeled["sealed_by"] = "someone-else"
    with pytest.raises(AuthenticationError):
        verify_sealed_evidence(relabeled, lab.key)
    other = tmp_path / "other.key"
    generate_key_file(other)
    with pytest.raises(AuthenticationError, match="different key"):
        verify_sealed_evidence(bundle, load_key(other))
    with pytest.raises(AuthenticationError, match="no authentication block"):
        verify_sealed_evidence(snapshot, lab.key)


def test_audit_records_have_fixed_fields_and_reject_unknown_outcomes(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl")
    row = log.record(AuditRecord("auditor", "verify", "n/a", "ok", detail="x" * 500))
    assert set(row) == {
        "actor", "operation", "decision", "outcome", "asset_id", "baseline_version",
        "evidence_ids", "detail", "node_id", "job_id", "ts", "source",
    }  # fmt: skip
    assert len(row["detail"]) == 300
    with pytest.raises(ValueError, match="outcome"):
        AuditRecord("a", "read", "allow", "exfiltrated")


def test_denials_and_failures_become_distinct_findings(lab):
    with pytest.raises(AccessDenied):
        lab.write("training-job", "model:ref", b"x", Workload(node_id="compute-01"))
    (lab.inventory.root / "data" / "sample.csv").write_text("changed")
    lab.verify()
    observations, bad = normalize_security(lab.audit.read(), 0)
    assert bad == 0
    assert {o["outcome"] for o in observations} == {"denied", "modified"}
    findings = SecurityFramework(LabConfig()).analyze(TelemetryBatch(security=observations))
    rules = {f["rule"]: f for f in findings}
    assert set(rules) == {"access-policy-violation", "integrity-failure"}
    assert rules["access-policy-violation"]["category"] == "investigate"
    assert rules["integrity-failure"]["category"] == "security"
    assert "not a confirmed incident" in rules["access-policy-violation"]["explanation"]
    assert all(f["rule_pack"] == "data-security-v1" for f in findings)
    # Successful operations other than reads are not observations; reads are kept only
    # for the read-then-transfer rule and never become findings by themselves.
    ok_rows = [r for r in lab.audit.read() if r["outcome"] == "ok"]
    ok_only, _ = normalize_security(ok_rows, 0)
    assert all(o["operation"] == "read" for o in ok_only)
    assert SecurityFramework(LabConfig()).analyze(TelemetryBatch(security=ok_only)) == []


def test_overlap_requires_matching_node_and_time():
    now = time.time()
    gpu = gpu_sample("misuse", random.Random(1), now, "run", "compute-01")
    denied = {
        "ts": now + 2,
        "actor": "training-job",
        "operation": "write",
        "decision": "deny",
        "outcome": "denied",
        "asset_id": "model:ref",
        "node_id": "compute-01",
    }
    engine = SecurityFramework(LabConfig())

    def rules(record, sample):
        observations, _ = normalize_security([record], 0)
        return {
            f["rule"] for f in engine.analyze(TelemetryBatch(gpu=[sample], security=observations))
        }

    assert "compute-policy-overlap" in rules(denied, gpu)
    assert "compute-policy-overlap" not in rules({**denied, "node_id": "compute-02"}, gpu)
    assert "compute-policy-overlap" not in rules({**denied, "ts": now + 60}, gpu)
    assert "compute-policy-overlap" not in rules({**denied, "node_id": None}, gpu)
    approved = {**gpu, "job_approved": True, "job_id": "approved-training-01"}
    assert "compute-policy-overlap" not in rules(denied, approved)


def test_collector_and_replay_carry_audit_observations(lab, tmp_path):
    from qdc_anomaly.lab.adapters import SourceResult
    from qdc_anomaly.lab.collector import Collector
    from qdc_anomaly.lab.storage import write_json

    with pytest.raises(AccessDenied):
        lab.read("unknown", "dataset:sample")
    write_json(tmp_path / "control.json", {"mode": "baseline", "run_id": "run", "started_at": 0})
    write_json(tmp_path / "inventory.json", {"worker": "172.20.0.2", "api": "172.20.0.3"})

    class Empty:
        def read(self, context):
            return SourceResult([], 0, 0)

    adapters = {"gpu": Empty(), "zeek": Empty(), "opencanary": Empty()}
    collector = Collector(
        LabConfig(), tmp_path, adapters=adapters, security_source=audit_source(lab.audit.path)
    )
    snapshot = collector.snapshot()
    assert snapshot["security"]["source"] == "audit log"
    assert [f["rule"] for f in snapshot["findings"]] == ["access-policy-violation"]
    ids = {e["id"] for e in snapshot["evidence"]}
    assert set(snapshot["findings"][0]["evidence_ids"]) <= ids
    result = replay({**snapshot, "findings": [{"rule": "fabricated"}]}, LabConfig())
    assert [f["rule"] for f in result["findings"]] == ["access-policy-violation"]
    assert result["counts"]["security"] == 1
    without = Collector(LabConfig(), tmp_path, adapters=adapters).snapshot()
    assert without["security"] == {"observations": [], "source": "none", "bad_records": 0}
    assert without["findings"] == []


def test_cli_round_trip_on_disposable_assets(lab, tmp_path, capsys):
    inventory = str(lab.inventory.root.parent / "inventory.json")
    key = str(tmp_path / "outside" / "integrity.key")
    baselines = str(lab.baselines.directory)
    audit = str(lab.audit.path)
    common = [
        "--inventory",
        inventory,
        "--key-file",
        key,
        "--baselines",
        baselines,
        "--audit",
        audit,
    ]
    assert security_cli([*common, "verify"]) == 0
    (lab.inventory.root / "data" / "sample.csv").write_text("tampered")
    assert security_cli([*common, "verify"]) == 1
    assert security_cli([*common, "baseline", "--approved-by", "training-job"]) == 2
    assert security_cli([*common, "baseline", "--approved-by", "publisher"]) == 0
    assert security_cli([*common, "verify"]) == 0
    export = tmp_path / "export.json"
    export.write_text(json.dumps({"control": {"run_id": "r"}, "evidence": []}))
    sealed = tmp_path / "sealed.json"
    assert (
        security_cli([*common, "seal-evidence", "--input", str(export), "--out", str(sealed)]) == 0
    )
    assert security_cli([*common, "verify-evidence", "--input", str(sealed)]) == 0
    tampered = json.loads(sealed.read_text())
    tampered["snapshot"]["evidence"].append({"id": "planted"})
    sealed.write_text(json.dumps(tampered))
    assert security_cli([*common, "verify-evidence", "--input", str(sealed)]) == 1
    output = capsys.readouterr().out
    assert "Authenticity of the bundle only" in output
    assert lab.audit.read()[-1]["outcome"] == "auth-failed"
    with pytest.raises(FileExistsError):
        security_cli([*common, "keygen"])


def test_allowed_read_then_transfer_requires_order_node_and_unapproved_peer():
    inventory = {"worker": "172.20.0.2", "api": "172.20.0.3", "canary": "172.20.0.4"}
    read = {
        "ts": 100,
        "actor": "training-job",
        "operation": "read",
        "decision": "allow",
        "outcome": "ok",
        "asset_id": "dataset:sample",
        "node_id": "compute-01",
    }
    transfer = {
        "ts": 110,
        "uid": "Cbig",
        "id.orig_h": inventory["worker"],
        "id.resp_h": "172.20.0.5",
        "id.resp_p": 8080,
        "orig_bytes": 66000,
    }
    engine = SecurityFramework(LabConfig())

    def rules(audit_row, raw_flow):
        observations, _ = normalize_security([audit_row], 0)
        flows, _ = normalize_flows([raw_flow], 0, inventory["worker"])
        batch = TelemetryBatch(flows=flows, inventory=inventory, security=observations)
        return {f["rule"] for f in engine.analyze(batch)}

    found = rules(read, transfer)
    assert "asset-read-then-transfer" in found
    assert "access-policy-violation" not in found  # an allowed read alone is never a violation
    assert rules(read, {**transfer, "ts": 90}) == set()  # transfer before the read
    assert rules(read, {**transfer, "ts": 200}) == set()  # outside the window
    assert rules({**read, "node_id": "other"}, transfer) == set()
    assert rules({**read, "asset_id": "config:thresholds"}, transfer) == set()
    assert rules(read, {**transfer, "id.resp_h": inventory["api"]}) == set()
    assert rules(read, {**transfer, "orig_bytes": 100}) == set()
    # Successful reads alone produce observations but no finding.
    observations, _ = normalize_security([read], 0)
    assert len(observations) == 1
    assert engine.analyze(TelemetryBatch(inventory=inventory, security=observations)) == []
