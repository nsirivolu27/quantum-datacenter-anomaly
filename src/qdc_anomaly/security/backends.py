"""Artifact storage boundary. The only implementation uses a confined directory."""

from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from qdc_anomaly.security.assets import AssetInventory, ScopeError, check_relative_path


class ArtifactBackend(Protocol):
    """Paths are relative POSIX paths; writes replace one file atomically.

    ``name`` identifies the backend in optional inventory locations. Missing reads
    raise FileNotFoundError; escapes raise ScopeError. Other I/O errors propagate.
    """

    name: str

    def read_bytes(self, relative: str) -> bytes: ...

    def write_bytes(self, relative: str, data: bytes) -> None: ...

    def exists(self, relative: str) -> bool: ...

    def digest(self, relative: str) -> tuple[str, int]: ...

    def list_files(self) -> list[str]: ...

    def escaped_links(self) -> list[str]: ...


@dataclass
class LocalDirectoryBackend:
    root: Path
    name = "local"

    def __post_init__(self):
        self.root = Path(self.root).resolve()
        if not self.root.is_dir():
            raise ScopeError(f"Artifact root does not exist: {self.root}")

    def contains(self, path: Path) -> bool:
        try:
            path.resolve().relative_to(self.root)
        except ValueError:
            return False
        return True

    def resolve(self, relative: str) -> Path:
        candidate = self.root / check_relative_path(relative)
        if not self.contains(candidate):
            raise ScopeError(f"{relative} resolves outside the inventory root")
        return candidate

    def read_bytes(self, relative: str) -> bytes:
        return self.resolve(relative).read_bytes()

    def write_bytes(self, relative: str, data: bytes) -> None:
        path = self.resolve(relative)
        # A unique, exclusively created sibling avoids following a planted .tmp link.
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            self.resolve(relative)  # Recheck scope before replacing the destination.
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def exists(self, relative: str) -> bool:
        return self.resolve(relative).is_file()

    def digest(self, relative: str) -> tuple[str, int]:
        digest, size = hashlib.sha256(), 0
        with self.resolve(relative).open("rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 16), b""):
                digest.update(chunk)
                size += len(chunk)
        return digest.hexdigest(), size

    def _paths(self):
        def fail(error):
            raise error

        for parent, directories, files in os.walk(self.root, followlinks=False, onerror=fail):
            for name in sorted(directories + files):
                yield Path(parent) / name
            # Do not scan linked directories or descend outside the declared root.
            directories[:] = [
                name
                for name in directories
                if not (Path(parent) / name).is_symlink() and self.contains(Path(parent) / name)
            ]

    def list_files(self) -> list[str]:
        return sorted(
            path.relative_to(self.root).as_posix()
            for path in self._paths()
            if self.contains(path) and path.is_file()
        )

    def escaped_links(self) -> list[str]:
        return sorted(
            path.relative_to(self.root).as_posix()
            for path in self._paths()
            if not self.contains(path)
        )


def inventory_backend(
    inventory: AssetInventory, backend: ArtifactBackend | None = None
) -> ArtifactBackend:
    """Select local storage only when no backend was explicitly supplied."""
    if backend is None:
        backend = LocalDirectoryBackend(inventory.root)
    if isinstance(backend, LocalDirectoryBackend) and backend.root != inventory.root.resolve():
        raise ScopeError("Local backend root must match the inventory root")
    for asset in inventory.assets.values():
        if asset.location is None:
            continue
        if asset.location["backend"] != backend.name:
            raise ScopeError(f"{asset.id} names a different backend: {asset.location['backend']}")
        if backend.name == "local" and set(asset.location) != {"backend"}:
            raise ScopeError("Local storage does not support bucket or version_id locations")
    return backend
