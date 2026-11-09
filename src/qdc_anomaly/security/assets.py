"""Declared protected assets confined to one inventory root."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

ASSET_KINDS = ("dataset", "model", "config", "evidence")


class ScopeError(ValueError):
    """A path is outside the declared inventory root or escapes it through a link."""


@dataclass(frozen=True)
class Asset:
    id: str
    kind: str
    path: str  # relative POSIX path under the inventory root
    approved_version: str
    description: str = ""
    location: dict[str, str] | None = None  # Schema v2: backend, optional bucket/version_id.


def check_relative_path(value: str) -> str:
    """Accept only a plain relative path with no traversal, drive, or absolute prefix."""
    if not isinstance(value, str) or not value or "\\" in value:
        raise ScopeError(f"Asset paths must be relative POSIX paths: {value!r}")
    pure = PurePosixPath(value)
    if pure.is_absolute() or ":" in value or any(part in {"..", ""} for part in pure.parts):
        raise ScopeError(f"Asset path escapes or is not relative: {value!r}")
    return str(pure)


def read_location(entry: dict, schema_version: int) -> dict[str, str] | None:
    if "location" not in entry:
        return None
    if schema_version != 2:
        raise ValueError("Asset locations require inventory schema_version 2")
    location = entry["location"]
    if not isinstance(location, dict) or "backend" not in location:
        raise ValueError("Asset location must name a backend")
    if set(location) - {"backend", "bucket", "version_id"}:
        raise ValueError("Unknown asset location fields")
    if any(not isinstance(value, str) or not value.strip() for value in location.values()):
        raise ValueError("Asset location values must be non-empty strings")
    return dict(location)


@dataclass(frozen=True)
class AssetInventory:
    root: Path
    assets: dict[str, Asset]
    schema_version: int = 1

    @classmethod
    def load(cls, path: str | Path) -> AssetInventory:
        path = Path(path)
        document = json.loads(path.read_text(encoding="utf-8"))
        schema_version = document.get("schema_version")
        if type(schema_version) is not int or schema_version not in (1, 2):
            raise ValueError("Unsupported inventory schema")
        root_value = check_relative_path(document["root"])
        root = (path.parent / root_value).resolve()
        if not root.is_dir():
            raise ScopeError(f"Inventory root does not exist: {root}")
        assets: dict[str, Asset] = {}
        for entry in document["assets"]:
            asset = Asset(
                id=str(entry["id"]),
                kind=str(entry["kind"]),
                path=check_relative_path(entry["path"]),
                approved_version=str(entry["approved_version"]),
                description=str(entry.get("description", "")),
                location=read_location(entry, schema_version),
            )
            if asset.kind not in ASSET_KINDS:
                raise ValueError(f"Unknown asset kind {asset.kind!r} for {asset.id}")
            if asset.id in assets:
                raise ValueError(f"Duplicate asset id {asset.id}")
            assets[asset.id] = asset
        return cls(root, assets, schema_version)

    def get(self, asset_id: str) -> Asset:
        if asset_id not in self.assets:
            raise KeyError(asset_id)
        return self.assets[asset_id]

    def contains(self, path: Path) -> bool:
        """True when the fully resolved path (links followed) is inside the root."""
        try:
            path.resolve().relative_to(self.root)
        except ValueError:
            return False
        return True

    def resolve(self, asset_id: str) -> Path:
        """Return the on-disk path for an asset after confirming it stays inside the root.

        The lexical check in ``check_relative_path`` rejects traversal. This second
        check follows symbolic links so a link planted inside the root cannot point
        at a file outside it.
        """
        from qdc_anomaly.security.backends import LocalDirectoryBackend, inventory_backend

        backend = LocalDirectoryBackend(self.root)
        inventory_backend(self, backend)
        return backend.resolve(self.get(asset_id).path)

    def is_outside(self, path: Path) -> bool:
        """Helper for callers that hold a path rather than an asset id."""
        return not self.contains(path)
