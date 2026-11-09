"""Local data-security and integrity checks for declared sample assets.

Everything here works on one declared inventory root. Identity is a label supplied
by the caller, enforcement covers only calls made through ``GuardedStore``, and
authentication of manifests and evidence uses a local HMAC key kept outside the
inventory root. See ``docs/13-data-security-and-integrity.md`` for the limits.
"""
