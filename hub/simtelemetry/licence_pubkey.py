"""The public keys the hub trusts for licence codes (raw 32-byte Ed25519 public keys).

Empty until LOCAL task L1: the factory's "Set up keys" step generates this file with the real key, and it is
committed. With no key here every code fails verification, so the hub runs on the fallback entitlement.
A public key can only check codes, never make them; the private key never enters this repo.
"""

from __future__ import annotations

TRUSTED_KEYS: tuple[bytes, ...] = ()
