"""The guarded read/write/approve path. Policy is checked before anything touches disk.

This store only governs calls made through it. A process that opens the files
directly bypasses it; only an operating-system boundary (file permissions, a
container mount, a separate host) can stop that. Compose gives the worker a
read-only asset mount; the Python store itself cannot enforce that boundary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from qdc_anomaly.security.access_policy import AccessPolicy, AccessRequest
from qdc_anomaly.security.assets import AssetInventory, ScopeError
from qdc_anomaly.security.audit import AuditLog, AuditRecord
from qdc_anomaly.security.authenticators import Authenticator, as_authenticator
from qdc_anomaly.security.backends import ArtifactBackend, inventory_backend
from qdc_anomaly.security.integrity import (
    AuthenticationError,
    BaselineStore,
    IntegrityReport,
    matches_asset,
    sha256_bytes,
    verify_asset_bytes,
    verify_assets,
)


class AccessDenied(PermissionError):
    pass


class IntegrityFailure(ValueError):
    pass


@dataclass(frozen=True)
class Workload:
    """Optional simulated workload identity attached to a request for later correlation."""

    node_id: str | None = None
    job_id: str | None = None


@dataclass
class GuardedStore:
    inventory: AssetInventory
    policy: AccessPolicy
    baselines: BaselineStore
    audit: AuditLog
    key: Authenticator | bytes = field(repr=False)
    backend: ArtifactBackend | None = None

    def __post_init__(self):
        self.key = as_authenticator(self.key)
        self.backend = inventory_backend(self.inventory, self.backend)
        if self.inventory.contains(self.audit.path):
            raise ScopeError("The audit log must live outside the inventory root")

    # -- helpers -------------------------------------------------------------------

    def _decide(self, actor: str, operation: str, asset_id: str | None):
        return self.policy.evaluate(AccessRequest(actor, operation, asset_id), self.inventory)

    def _log(self, workload: Workload | None, **fields) -> dict:
        workload = workload or Workload()
        return self.audit.record(
            AuditRecord(node_id=workload.node_id, job_id=workload.job_id, **fields)
        )

    def _approved_manifest(self, actor, operation, asset_id, workload) -> dict:
        try:
            return self.baselines.load_approved(self.key)
        except AuthenticationError as exc:
            self._log(
                workload,
                actor=actor,
                operation=operation,
                decision="allow",
                outcome="auth-failed",
                asset_id=asset_id,
                detail=str(exc),
            )
            raise IntegrityFailure(str(exc)) from exc

    # -- operations ------------------------------------------------------------------

    def read(self, actor: str, asset_id: str, workload: Workload | None = None) -> bytes:
        """Return verified bytes, or raise.

        The bytes handed back are exactly the bytes that were hashed, so the caller
        consumes what was verified. The file on disk can still change afterwards; a
        later read through this method verifies again.
        """
        decision = self._decide(actor, "read", asset_id)
        if not decision.allowed:
            self._log(
                workload,
                actor=actor,
                operation="read",
                decision="deny",
                outcome="denied",
                asset_id=asset_id,
                detail=decision.reason,
            )
            raise AccessDenied(decision.reason)
        manifest = self._approved_manifest(actor, "read", asset_id, workload)
        version = int(manifest["baseline_version"])
        try:
            data = self.backend.read_bytes(self.inventory.get(asset_id).path)
        except (ScopeError, OSError) as exc:
            outcome = "escaped" if isinstance(exc, ScopeError) else "missing"
            self._log(
                workload,
                actor=actor,
                operation="read",
                decision="allow",
                outcome=outcome,
                asset_id=asset_id,
                baseline_version=version,
                detail=str(exc),
            )
            raise IntegrityFailure(f"{asset_id}: {outcome}") from exc
        entry = manifest["assets"].get(asset_id, {})
        if not matches_asset(entry, self.inventory.get(asset_id)) or not verify_asset_bytes(
            manifest, asset_id, data
        ):
            outcome = "modified" if asset_id in manifest["assets"] else "unapproved"
            self._log(
                workload,
                actor=actor,
                operation="read",
                decision="allow",
                outcome=outcome,
                asset_id=asset_id,
                baseline_version=version,
                evidence_ids=[f"sha256:{sha256_bytes(data)[:16]}"],
                detail="content differs from the approved baseline",
            )
            raise IntegrityFailure(f"{asset_id} does not match baseline {version}")
        self._log(
            workload,
            actor=actor,
            operation="read",
            decision="allow",
            outcome="ok",
            asset_id=asset_id,
            baseline_version=version,
            evidence_ids=[f"sha256:{manifest['assets'][asset_id]['sha256'][:16]}"],
            detail=decision.reason,
        )
        return data

    def write(self, actor: str, asset_id: str, data: bytes, workload: Workload | None = None):
        """Replace an asset's content after a policy check. Does not approve it."""
        decision = self._decide(actor, "write", asset_id)
        if not decision.allowed:
            self._log(
                workload,
                actor=actor,
                operation="write",
                decision="deny",
                outcome="denied",
                asset_id=asset_id,
                detail=decision.reason,
            )
            raise AccessDenied(decision.reason)
        try:
            self.backend.write_bytes(self.inventory.get(asset_id).path, data)
        except ScopeError as exc:
            self._log(
                workload,
                actor=actor,
                operation="write",
                decision="allow",
                outcome="escaped",
                asset_id=asset_id,
                detail=str(exc),
            )
            raise IntegrityFailure(str(exc)) from exc
        self._log(
            workload,
            actor=actor,
            operation="write",
            decision="allow",
            outcome="ok",
            asset_id=asset_id,
            evidence_ids=[f"sha256:{sha256_bytes(data)[:16]}"],
            detail="written; differs from the approved baseline until a new version is approved",
        )

    def approve_baseline(self, actor: str, note: str = "") -> dict:
        """Create the next approved manifest version. Never called automatically."""
        decision = self._decide(actor, "approve", None)
        if not decision.allowed:
            self._log(
                None,
                actor=actor,
                operation="approve",
                decision="deny",
                outcome="denied",
                detail=decision.reason,
            )
            raise AccessDenied(decision.reason)
        manifest = self.baselines.create(self.inventory, self.key, actor, note, self.backend)
        self._log(
            None,
            actor=actor,
            operation="approve",
            decision="allow",
            outcome="ok",
            baseline_version=int(manifest["baseline_version"]),
            evidence_ids=[f"sha256:{e['sha256'][:16]}" for e in manifest["assets"].values()],
            detail=note or "new baseline version approved",
        )
        return manifest

    def verify(self, actor: str = "auditor") -> IntegrityReport:
        """Compare the whole inventory with the approved baseline and record the outcome."""
        manifest = self._approved_manifest(actor, "verify", None, None)
        report = verify_assets(self.inventory, manifest, self.backend)
        version = int(manifest["baseline_version"])
        if report.passed:
            self._log(
                None,
                actor=actor,
                operation="verify",
                decision="n/a",
                outcome="ok",
                baseline_version=version,
                detail=f"{len(report.results)} assets match",
            )
        for problem in report.problems():
            self._log(
                None,
                actor=actor,
                operation="verify",
                decision="n/a",
                outcome=problem["status"],
                asset_id=problem["asset_id"],
                baseline_version=version,
                detail=problem.get("path", ""),
            )
        return report


def default_store_paths(inventory_path: Path) -> dict[str, Path]:
    """Conventional locations beside the inventory file, all outside the asset root."""
    local = inventory_path.parent / "local"
    return {
        "key": local / "integrity.key",
        "baselines": local / "baselines",
        "audit": local / "audit.jsonl",
        "policy": inventory_path.parent / "policy.json",
    }
