"""Stored PINs: salted scrypt hashes, so settings.json (and its backups) never hold a PIN in plain text.

A stored PIN is either a hash made by hash_pin ("scrypt$...") or, from hub.toml or --owner-pin, plain digits.
verify_pin accepts both and always compares in constant time.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import threading

PREFIX = "scrypt$"
_N, _R, _P = 2 ** 14, 8, 1           # ~16 MB and a few tens of ms per check
_SALT_BYTES, _KEY_BYTES = 16, 32

# Successful checks, so the staff page's frequent requests don't each pay for scrypt.
# Keyed by the stored hash and a SHA-256 of the PIN given (never the PIN itself).
_verified: set[tuple[str, bytes]] = set()
_lock = threading.Lock()


def is_hashed(stored: str) -> bool:
    return stored.startswith(PREFIX)


def _derive(pin: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(pin.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=_KEY_BYTES, maxmem=64 * 1024 * 1024)


def hash_pin(pin: str) -> str:
    """'' stays '' (no PIN); a hash stays as it is; anything else is hashed with a fresh salt."""
    if not pin or is_hashed(pin):
        return pin
    salt = os.urandom(_SALT_BYTES)
    return f"{PREFIX}{_N}${_R}${_P}${salt.hex()}${_derive(pin, salt, _N, _R, _P).hex()}"


def verify_pin(given: str, stored: str) -> bool:
    """True when `given` matches the stored PIN (hashed or plain). An empty stored PIN matches nothing."""
    if not stored or not given:
        return False
    if not is_hashed(stored):
        return hmac.compare_digest(given.encode("utf-8"), stored.encode("utf-8"))
    key = (stored, hashlib.sha256(given.encode("utf-8")).digest())
    with _lock:
        if key in _verified:
            return True
    try:
        n, r, p, salt, digest = stored[len(PREFIX):].split("$")
        derived = _derive(given, bytes.fromhex(salt), int(n), int(r), int(p))
        ok = hmac.compare_digest(derived, bytes.fromhex(digest))
    except (ValueError, MemoryError):
        return False
    if ok:
        with _lock:
            if len(_verified) > 256:
                _verified.clear()
            _verified.add(key)
    return ok
