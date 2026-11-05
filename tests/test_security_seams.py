"""Replacement implementations must drive the actual guarded paths."""

import hashlib
import hmac
import json
import shutil
from dataclasses import replace
from pathlib import Path

import pytest

from qdc_anomaly.security.access_policy import AccessPolicy
from qdc_anomaly.security.assets import AssetInventory, ScopeError
from qdc_anomaly.security.audit import AuditLog
from qdc_anomaly.security.authenticators import LocalHmacAuthenticator
from qdc_anomaly.security.backends import LocalDirectoryBackend
from qdc_anomaly.security.integrity import (
    AuthenticationError,
    BaselineStore,
    authenticate,
    canonical_bytes,
    seal_evidence,
    verify_authenticated,
    verify_sealed_evidence,
)
from qdc_anomaly.security.store import AccessDenied, GuardedStore, IntegrityFailure

DATASET = "dataset:telemetry-sample"
MODEL = "model:isolation-forest-reference"


def make_store(tmp_path, key=b"test key material only" * 2):
    fixtures = Path(__file__).resolve().parents[1] / "security"
    shutil.copytree(fixtures / "assets", tmp_path / "assets")
    shutil.copy(fixtures / "inventory.json", tmp_path / "inventory.json")
    return GuardedStore(
        AssetInventory.load(tmp_path / "inventory.json"),
        AccessPolicy.load(fixtures / "policy.json"),
        BaselineStore(tmp_path / "local" / "baselines"),
        AuditLog(tmp_path / "local" / "audit.jsonl"),
        key,
    )


def test_baseline_store_and_evidence_use_a_replacement_authenticator(tmp_path):
    class FakeAuthenticator:
        # Deliberately not HMAC. This test double provides no security guarantee.
        algorithm = "TEST-ONLY-SHA512"

        def __init__(self):
            self.signed = []
            self.verified = []

        def key_id(self):
            return "test-double"

        def sign(self, data):
            self.signed.append(data)
            return hashlib.sha512(b"test-only:" + data).hexdigest()

        def verify(self, data, tag):
            self.verified.append(data)
            expected = hashlib.sha512(b"test-only:" + data).hexdigest()
            return hmac.compare_digest(expected, tag)

    fake = FakeAuthenticator()
    store = make_store(tmp_path, fake)
    manifest = store.approve_baseline("publisher", "replacement authenticator")
    assert manifest["auth"]["algorithm"] == fake.algorithm
    assert store.verify().passed
    assert store.read("training-job", DATASET)
    snapshot = {"evidence": [], "control": {"run_id": "test"}}
    bundle = seal_evidence(snapshot, fake, "collector")
    assert verify_sealed_evidence(json.loads(json.dumps(bundle)), fake) == snapshot
    assert len(fake.signed) == 3  # manifest, approved pointer, evidence bundle
    assert set(fake.signed) <= set(fake.verified)
    bundle["snapshot"]["evidence"].append({"id": "planted"})
    with pytest.raises(AuthenticationError, match="authentication tag"):
        verify_sealed_evidence(bundle, fake)


def test_legacy_hmac_document_shape_and_key_id_stay_compatible():
    key = bytes(range(32))
    body = {"schema_version": 1, "example": "unchanged"}
    # Reproduce the old format independently of the new implementation.
    legacy = {
        **body,
        "auth": {
            "algorithm": "HMAC-SHA256",
            "key_id": hashlib.sha256(b"qdc-integrity-key-id:" + key).hexdigest()[:12],
            "mac": hmac.new(key, canonical_bytes(body), hashlib.sha256).hexdigest(),
        },
    }
    assert authenticate(body, key) == legacy
    assert verify_authenticated(legacy, LocalHmacAuthenticator(key), "legacy") == body
    legacy["auth"]["key_id"] = "wrong-label"
    with pytest.raises(AuthenticationError, match="different key"):
        verify_authenticated(legacy, key, "legacy")


@pytest.mark.parametrize("tag", [None, "", "g" * 64, "\u00e9" * 64, "00" * 32])
def test_local_authenticator_rejects_invalid_tags(tag):
    authenticator = LocalHmacAuthenticator(bytes(range(32)))
    assert not authenticator.verify(b"original", tag)
    assert authenticator.verify(b"original", authenticator.sign(b"original"))
    assert not authenticator.verify(b"changed", authenticator.sign(b"original"))


def test_guarded_operations_and_whole_inventory_checks_use_the_backend(tmp_path):
    class MemoryBackend:
        name = "memory-test"

        def __init__(self, files):
            self.files = files
            self.reads = []
            self.writes = []

        def read_bytes(self, relative):
            self.reads.append(relative)
            if relative not in self.files:
                raise FileNotFoundError(relative)
            return self.files[relative]

        def write_bytes(self, relative, data):
            self.writes.append(relative)
            self.files[relative] = data

        def exists(self, relative):
            return relative in self.files

        def digest(self, relative):
            data = self.read_bytes(relative)
            return hashlib.sha256(data).hexdigest(), len(data)

        def list_files(self):
            return sorted(self.files)

        def escaped_links(self):
            return []

    store = make_store(tmp_path)
    files = {
        asset.path: store.inventory.resolve(asset.id).read_bytes()
        for asset in store.inventory.assets.values()
    }
    backend = MemoryBackend(files)
    store = replace(store, backend=backend)
    for asset in store.inventory.assets.values():
        store.inventory.resolve(asset.id).unlink()
    manifest = store.approve_baseline("publisher", "memory backend")
    assert store.verify().passed  # No artifact remains on disk.
    assert store.read("training-job", DATASET) == files[store.inventory.get(DATASET).path]
    reads = list(backend.reads)
    with pytest.raises(AccessDenied):
        store.write("training-job", MODEL, b"unauthorized")
    assert backend.writes == [] and backend.reads == reads
    store.write("publisher", MODEL, b"approved caller, pending content approval")
    assert backend.writes == [store.inventory.get(MODEL).path]
    with pytest.raises(IntegrityFailure):
        store.read("training-job", MODEL)
    assert store.verify().results[MODEL] == "modified"
    assert store.baselines.latest_version() == manifest["baseline_version"] == 1
    store.approve_baseline("publisher", "explicit update")
    assert store.verify().passed
    del backend.files[store.inventory.get(DATASET).path]
    backend.files["models/planted.bin"] = b"x"
    report = store.verify()
    assert report.results[DATASET] == "missing"
    assert report.unexpected == ["models/planted.bin"]


@pytest.mark.parametrize("relative", ["../outside", "/absolute", "C:/outside", "a\\b"])
def test_backend_rejects_escape_paths_for_reads_writes_and_digests(tmp_path, relative):
    backend = LocalDirectoryBackend(tmp_path)
    for operation in (backend.read_bytes, backend.exists, backend.digest):
        with pytest.raises(ScopeError):
            operation(relative)
    with pytest.raises(ScopeError):
        backend.write_bytes(relative, b"escape")


def test_atomic_write_preserves_original_when_replace_fails(tmp_path, monkeypatch):
    import qdc_anomaly.security.backends as module

    backend = LocalDirectoryBackend(tmp_path)
    (tmp_path / "model.json").write_bytes(b"original")
    (tmp_path / "model.json.tmp").write_bytes(b"unrelated existing file")

    def fail_replace(source, destination):
        raise PermissionError("replacement refused")

    with monkeypatch.context() as patch:
        patch.setattr(module.os, "replace", fail_replace)
        with pytest.raises(PermissionError, match="replacement refused"):
            backend.write_bytes("model.json", b"new")
    assert backend.read_bytes("model.json") == b"original"
    assert backend.list_files() == ["model.json", "model.json.tmp"]
    backend.write_bytes("model.json", b"new")
    assert backend.read_bytes("model.json") == b"new"
    assert backend.read_bytes("model.json.tmp") == b"unrelated existing file"
    assert backend.digest("model.json") == (hashlib.sha256(b"new").hexdigest(), 3)


@pytest.mark.parametrize("schema_version", [1, 2])
def test_inventory_versions_round_trip_without_inventing_locations(tmp_path, schema_version):
    store = make_store(tmp_path)
    path = tmp_path / "inventory.json"
    document = json.loads(path.read_text())
    document["schema_version"] = schema_version
    if schema_version == 2:
        document["assets"][0]["location"] = {"backend": "local"}
    path.write_text(json.dumps(document))
    store = replace(store, inventory=AssetInventory.load(path))
    manifest = store.approve_baseline("publisher", "inventory version test")
    first_id = document["assets"][0]["id"]
    first = manifest["assets"][first_id]
    if schema_version == 1:
        assert "location" not in first
    else:
        assert first["location"] == {"backend": "local"}
    assert store.verify().passed
    assert store.read("publisher", first_id)


def test_cloud_location_loads_but_cannot_fall_back_to_local_files(tmp_path):
    store = make_store(tmp_path)
    path = tmp_path / "inventory.json"
    document = json.loads(path.read_text())
    document["schema_version"] = 2
    location = {"backend": "s3", "bucket": "example-only", "version_id": "version-example"}
    document["assets"][0]["location"] = location
    path.write_text(json.dumps(document))
    inventory = AssetInventory.load(path)
    assert inventory.get(document["assets"][0]["id"]).location == location
    with pytest.raises(ScopeError, match="different backend"):
        replace(store, inventory=inventory)
    with pytest.raises(ScopeError, match="different backend"):
        store.baselines.create(inventory, store.key, "publisher", "must not read local files")


def test_location_changes_require_explicit_approval_even_when_bytes_match(tmp_path):
    store = make_store(tmp_path)
    store.approve_baseline("publisher", "v1 inventory")
    assets = dict(store.inventory.assets)
    assets[DATASET] = replace(assets[DATASET], location={"backend": "local"})
    inventory = replace(store.inventory, assets=assets, schema_version=2)
    store = replace(store, inventory=inventory)
    assert store.verify().results[DATASET] == "modified"
    with pytest.raises(IntegrityFailure):
        store.read("training-job", DATASET)
    store.approve_baseline("publisher", "approve location binding")
    assert store.verify().passed


@pytest.mark.parametrize("location", [None, {}, {"backend": ""}, {"backend": "local", "typo": "x"}])
def test_malformed_locations_are_rejected(tmp_path, location):
    make_store(tmp_path)
    path = tmp_path / "inventory.json"
    document = json.loads(path.read_text())
    document["schema_version"] = 2
    document["assets"][0]["location"] = location
    path.write_text(json.dumps(document))
    with pytest.raises(ValueError, match="location"):
        AssetInventory.load(path)


def test_schema_v1_does_not_silently_ignore_a_location(tmp_path):
    make_store(tmp_path)
    path = tmp_path / "inventory.json"
    document = json.loads(path.read_text())
    document["assets"][0]["location"] = {"backend": "s3"}
    path.write_text(json.dumps(document))
    with pytest.raises(ValueError, match="schema_version 2"):
        AssetInventory.load(path)
