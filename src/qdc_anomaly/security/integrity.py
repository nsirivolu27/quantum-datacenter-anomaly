"""SHA-256 digests, HMAC-SHA256 authenticated baselines, and sealed evidence bundles.

HMAC gives authentication with a shared key. It is not encryption and it is not a
public-key signature: anyone holding the key can produce a valid tag, so the key
file is the trust anchor and must stay outside the inventory root.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path

from qdc_anomaly.security.assets import Asset, AssetInventory, ScopeError
from qdc_anomaly.security.authenticators import (
    KEY_BYTES,
    Authenticator,
    as_authenticator,
)
from qdc_anomaly.security.backends import ArtifactBackend, inventory_backend


class AuthenticationError(ValueError):
    """A manifest, pointer, or evidence bundle failed authentication."""


def canonical_bytes(value: dict) -> bytes:
    """Stable JSON encoding so the same content always produces the same tag."""
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> tuple[str, int]:
    digest, size = hashlib.sha256(), 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 16), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


# --- key handling ---------------------------------------------------------------


def generate_key_file(path: Path) -> None:
    """Write a fresh random key. Refuses to overwrite so a key is never silently rotated."""
    if path.exists():
        raise FileExistsError(f"Key file already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(path, flags, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(secrets.token_hex(KEY_BYTES) + "\n")


def load_key(path: Path, inventory: AssetInventory | None = None) -> bytes:
    """Read the hex key. Rejects a key stored inside the inventory root it protects."""
    if inventory is not None and inventory.contains(path):
        raise ScopeError("The integrity key must live outside the inventory root")
    text = Path(path).read_text(encoding="utf-8").strip()
    try:
        key = bytes.fromhex(text)
    except ValueError as exc:
        raise ValueError("Key file must contain hex text") from exc
    if len(key) < KEY_BYTES:
        raise ValueError(f"Key must be at least {KEY_BYTES} bytes")
    return key


def key_id(key: Authenticator | bytes) -> str:
    """Short label that identifies which key was used without revealing it."""
    return as_authenticator(key).key_id()


# --- authenticated documents -------------------------------------------------------


def authenticate(body: dict, key: Authenticator | bytes) -> dict:
    authenticator = as_authenticator(key)
    if "auth" in body:
        raise ValueError("Authentication body must not contain an auth block")
    tag = authenticator.sign(canonical_bytes(body))
    return {
        **body,
        "auth": {
            "algorithm": authenticator.algorithm,
            "key_id": authenticator.key_id(),
            "mac": tag,
        },
    }


def verify_authenticated(document: dict, key: Authenticator | bytes, label: str) -> dict:
    """Return the body if the tag matches; raise AuthenticationError otherwise."""
    if not isinstance(document, dict) or "auth" not in document:
        raise AuthenticationError(f"{label} carries no authentication block")
    auth = document["auth"]
    body = {name: value for name, value in document.items() if name != "auth"}
    authenticator = as_authenticator(key)
    if not isinstance(auth, dict) or auth.get("algorithm") != authenticator.algorithm:
        raise AuthenticationError(f"{label} uses an unsupported authentication algorithm")
    if auth.get("key_id") != authenticator.key_id():
        raise AuthenticationError(f"{label} was authenticated with a different key")
    tag = auth.get("mac")
    if not isinstance(tag, str) or not authenticator.verify(canonical_bytes(body), tag):
        raise AuthenticationError(f"{label} content does not match its authentication tag")
    return body


# --- baselines -------------------------------------------------------------------


def digest_inventory(
    inventory: AssetInventory, backend: ArtifactBackend | None = None
) -> dict[str, dict]:
    """Current digests of every declared asset. Missing or escaping files raise."""
    backend = inventory_backend(inventory, backend)
    entries = {}
    for asset in inventory.assets.values():
        if not backend.exists(asset.path):
            raise FileNotFoundError(f"{asset.id} is missing at {asset.path}")
        digest, size = backend.digest(asset.path)
        entries[asset.id] = {
            "path": asset.path,
            "kind": asset.kind,
            "approved_version": asset.approved_version,
            "sha256": digest,
            "bytes": size,
        }
        if asset.location is not None:
            entries[asset.id]["location"] = dict(asset.location)
    return entries


@dataclass
class BaselineStore:
    """Versioned manifests plus an authenticated pointer that names the approved one.

    Why the pointer: every manifest ever approved stays valid under the key, so an
    old manifest on its own cannot say whether it is still current. ``approved.json``
    is the single authenticated statement of which version and digest is approved.
    Editing it without the key fails verification; deleting it is an explicit
    failure rather than a silent fallback to an older manifest. Replaying an older
    valid pointer together with its manifest is not detected by this local store.
    """

    directory: Path

    def __post_init__(self):
        self.directory = Path(self.directory)

    def manifest_path(self, version: int) -> Path:
        return self.directory / f"baseline-{version:04d}.json"

    @property
    def pointer_path(self) -> Path:
        return self.directory / "approved.json"

    def latest_version(self) -> int:
        versions = [
            int(p.stem.split("-")[1])
            for p in self.directory.glob("baseline-*.json")
            if p.stem.split("-")[1].isdigit()
        ]
        return max(versions, default=0)

    def create(
        self,
        inventory: AssetInventory,
        key: Authenticator | bytes,
        approved_by: str,
        note: str,
        backend: ArtifactBackend | None = None,
    ) -> dict:
        """Write a new authenticated manifest version and point approval at it."""
        if inventory.contains(self.directory):
            raise ScopeError("Baselines must be stored outside the inventory root")
        self.directory.mkdir(parents=True, exist_ok=True)
        version = self.latest_version() + 1
        body = {
            "schema_version": 1,
            "baseline_version": version,
            "created_at": time.time(),
            "approved_by": approved_by,
            "note": note,
            "assets": digest_inventory(inventory, backend),
        }
        manifest = authenticate(body, key)
        manifest_bytes = canonical_bytes(manifest)
        self.manifest_path(version).write_bytes(manifest_bytes)
        pointer = authenticate(
            {
                "schema_version": 1,
                "baseline_version": version,
                "manifest_sha256": sha256_bytes(manifest_bytes),
                "approved_at": body["created_at"],
                "approved_by": approved_by,
            },
            key,
        )
        self.pointer_path.write_bytes(canonical_bytes(pointer))
        return manifest

    def load_approved(self, key: Authenticator | bytes) -> dict:
        """Return the currently approved manifest body after verifying pointer and manifest."""
        if not self.pointer_path.exists():
            raise AuthenticationError("No approved baseline pointer; nothing is approved")
        pointer = verify_authenticated(
            json.loads(self.pointer_path.read_text(encoding="utf-8")), key, "approved pointer"
        )
        path = self.manifest_path(int(pointer["baseline_version"]))
        if not path.exists():
            raise AuthenticationError(f"Approved manifest {path.name} is missing")
        raw = path.read_bytes()
        if not hmac.compare_digest(sha256_bytes(raw), str(pointer["manifest_sha256"])):
            raise AuthenticationError("Approved manifest does not match the pointer digest")
        return verify_authenticated(json.loads(raw), key, path.name)


# --- verification ----------------------------------------------------------------


@dataclass
class IntegrityReport:
    baseline_version: int
    checked_at: float
    results: dict[str, str] = field(default_factory=dict)  # asset id -> status
    unexpected: list[str] = field(default_factory=list)  # relative paths not in the manifest
    escaped: list[str] = field(default_factory=list)  # links that point outside the root

    @property
    def passed(self) -> bool:
        return (
            all(status == "ok" for status in self.results.values())
            and not self.unexpected
            and not self.escaped
        )

    def problems(self) -> list[dict]:
        found = [
            {"asset_id": asset_id, "status": status}
            for asset_id, status in self.results.items()
            if status != "ok"
        ]
        found += [{"asset_id": None, "status": "unexpected", "path": p} for p in self.unexpected]
        found += [{"asset_id": None, "status": "escaped", "path": p} for p in self.escaped]
        return found

    def to_dict(self) -> dict:
        return {
            "baseline_version": self.baseline_version,
            "checked_at": self.checked_at,
            "passed": self.passed,
            "results": dict(self.results),
            "unexpected": list(self.unexpected),
            "escaped": list(self.escaped),
        }


def verify_asset_bytes(manifest: dict, asset_id: str, data: bytes) -> bool:
    """Compare bytes already in memory against the approved digest."""
    entry = manifest["assets"].get(asset_id)
    return entry is not None and hmac.compare_digest(sha256_bytes(data), entry["sha256"])


def matches_asset(entry: dict, asset: Asset) -> bool:
    """The approved digest is bound to the path, version label, and storage location."""
    return (
        entry.get("path") == asset.path
        and entry.get("kind") == asset.kind
        and entry.get("approved_version") == asset.approved_version
        and entry.get("location") == asset.location
    )


def verify_assets(
    inventory: AssetInventory, manifest: dict, backend: ArtifactBackend | None = None
) -> IntegrityReport:
    """Compare the inventory root against an approved manifest. Never rewrites anything."""
    backend = inventory_backend(inventory, backend)
    report = IntegrityReport(int(manifest["baseline_version"]), time.time())
    declared_paths = set()
    for asset_id, entry in manifest["assets"].items():
        declared_paths.add(entry["path"])
        if asset_id not in inventory.assets:
            report.results[asset_id] = "missing"  # approved but no longer declared
            continue
        try:
            relative = inventory.get(asset_id).path
            if not backend.exists(relative):
                report.results[asset_id] = "missing"
                continue
            digest, _ = backend.digest(relative)
        except ScopeError:
            report.results[asset_id] = "escaped"
            continue
        except FileNotFoundError:
            report.results[asset_id] = "missing"
            continue
        matches = matches_asset(entry, inventory.get(asset_id)) and hmac.compare_digest(
            digest, entry["sha256"]
        )
        report.results[asset_id] = "ok" if matches else "modified"
    for asset_id in inventory.assets:
        if asset_id not in manifest["assets"]:
            report.results[asset_id] = "unapproved"  # declared but never baselined
    report.escaped = backend.escaped_links()
    report.unexpected = sorted(set(backend.list_files()) - declared_paths)
    return report


# --- evidence bundles --------------------------------------------------------------


def seal_evidence(snapshot: dict, key: Authenticator | bytes, sealed_by: str) -> dict:
    """Wrap an exported snapshot so later edits are detectable.

    Sealing proves the bundle has not changed since this moment. It cannot say
    anything about whether the sensors that produced the snapshot were truthful.
    """
    if not isinstance(snapshot, dict) or "evidence" not in snapshot:
        raise ValueError("Expected an exported snapshot with an evidence list")
    content = canonical_bytes(snapshot)
    return authenticate(
        {
            "schema_version": 1,
            "kind": "sealed-evidence",
            "sealed_at": time.time(),
            "sealed_by": sealed_by,
            "run_id": snapshot.get("control", {}).get("run_id"),
            "record_count": len(snapshot["evidence"]),
            "evidence_sha256": sha256_bytes(content),
            "snapshot": snapshot,
        },
        key,
    )


def verify_sealed_evidence(bundle: dict, key: Authenticator | bytes) -> dict:
    """Return the snapshot inside a bundle, or raise AuthenticationError."""
    body = verify_authenticated(bundle, key, "evidence bundle")
    if body.get("kind") != "sealed-evidence":
        raise AuthenticationError("Document is not a sealed evidence bundle")
    digest = sha256_bytes(canonical_bytes(body["snapshot"]))
    if not hmac.compare_digest(digest, str(body["evidence_sha256"])):
        raise AuthenticationError("Evidence digest does not match the sealed content")
    return body["snapshot"]
