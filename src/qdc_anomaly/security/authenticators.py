"""Document authentication boundary; only local shared-key HMAC is implemented."""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass, field
from typing import Protocol

ALGORITHM = "HMAC-SHA256"
KEY_BYTES = 32


class Authenticator(Protocol):
    """Authenticate bytes with a named algorithm and key; tags are hex strings.

    Implementations must compare authentication tags in constant time. A key ID
    is a public label, not a secret or an authenticated caller identity.
    """

    algorithm: str

    def key_id(self) -> str: ...

    def sign(self, data: bytes) -> str: ...

    def verify(self, data: bytes, tag: str) -> bool: ...


@dataclass(frozen=True)
class LocalHmacAuthenticator:
    key: bytes = field(repr=False)
    algorithm = ALGORITHM

    def __post_init__(self):
        if not isinstance(self.key, bytes) or len(self.key) < KEY_BYTES:
            raise ValueError(f"Key must be at least {KEY_BYTES} bytes")

    def key_id(self) -> str:
        return hashlib.sha256(b"qdc-integrity-key-id:" + self.key).hexdigest()[:12]

    def sign(self, data: bytes) -> str:
        return hmac.new(self.key, data, hashlib.sha256).hexdigest()

    def verify(self, data: bytes, tag: str) -> bool:
        if not isinstance(tag, str) or len(tag) != 64:
            return False
        try:
            supplied = bytes.fromhex(tag)
        except ValueError:
            return False
        expected = hmac.new(self.key, data, hashlib.sha256).digest()
        return hmac.compare_digest(expected, supplied)


def as_authenticator(value: Authenticator | bytes) -> Authenticator:
    """Keep existing raw-key callers working without choosing an implicit fallback."""
    if isinstance(value, bytes):
        return LocalHmacAuthenticator(value)
    return value
