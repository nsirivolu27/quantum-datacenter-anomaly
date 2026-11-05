"""Deny-by-default policy evaluation. Pure decisions; nothing here touches files.

The actor is a label supplied by the caller. Nothing in this module authenticates
it, so a decision means "this label is permitted", not "this caller is who it says".
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from qdc_anomaly.security.assets import AssetInventory

OPERATIONS = ("read", "write", "approve")


@dataclass(frozen=True)
class AccessRequest:
    actor: str
    operation: str
    asset_id: str | None = None  # None only for operations that are not about one asset


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reason: str

    @property
    def decision(self) -> str:
        return "allow" if self.allowed else "deny"


def _pattern_matches(pattern: str, asset_id: str, kind: str) -> bool:
    if pattern == "*":
        return True
    if pattern.endswith(":*"):
        return kind == pattern[:-2]
    return pattern == asset_id


@dataclass(frozen=True)
class AccessPolicy:
    actors: dict[str, dict]

    @classmethod
    def load(cls, path: str | Path) -> AccessPolicy:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
        if document.get("schema_version") != 1:
            raise ValueError("Unsupported policy schema")
        actors = {}
        for name, grant in document["actors"].items():
            unknown = set(grant) - {"description", "read", "write", "approve"}
            if unknown:
                raise ValueError(f"Unknown policy keys for {name}: {sorted(unknown)}")
            actors[name] = {
                "read": list(grant.get("read", [])),
                "write": list(grant.get("write", [])),
                "approve": bool(grant.get("approve", False)),
            }
        return cls(actors)

    def evaluate(self, request: AccessRequest, inventory: AssetInventory) -> PolicyDecision:
        if request.operation not in OPERATIONS:
            return PolicyDecision(False, f"unknown operation {request.operation!r}")
        grant = self.actors.get(request.actor)
        if grant is None:
            return PolicyDecision(False, f"actor {request.actor!r} has no policy entry")
        if request.operation == "approve":
            if grant["approve"]:
                return PolicyDecision(True, "actor may approve baselines")
            return PolicyDecision(False, "actor may not approve baselines")
        if request.asset_id is None or request.asset_id not in inventory.assets:
            return PolicyDecision(False, "asset is outside the declared inventory scope")
        kind = inventory.assets[request.asset_id].kind
        for pattern in grant[request.operation]:
            if _pattern_matches(pattern, request.asset_id, kind):
                return PolicyDecision(True, f"matched {request.operation} grant {pattern!r}")
        return PolicyDecision(False, f"no {request.operation} grant for {request.asset_id}")
