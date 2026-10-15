"""Stored PINs: salted scrypt hashes, so settings.json (and its backups) never hold a PIN in plain text.

A stored PIN is either a hash made by hash_pin ("scrypt$...") or, from hub.toml or --owner-pin, plain digits.
verify_pin accepts both and always compares in constant time.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import logging
import os
import threading
import time
from collections import deque

log = logging.getLogger(__name__)

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


# --- wrong-PIN lock-out ------------------------------------------------------------------------

MAX_FAILURES = 5                 # wrong PINs from one address ...
FAILURE_WINDOW_S = 60.0          # ... within this long lock it out for SHORT_LOCK_S
SHORT_LOCK_S = 60.0
LOCKOUTS_FOR_LONG = 3            # this many lock-outs ...
LOCKOUT_WINDOW_S = 3600.0        # ... within an hour lock the address out for LONG_LOCK_S
LONG_LOCK_S = 15 * 60.0
SHORT_LOCK_TEXT = "Too many wrong PINs. Wait a minute, then try again."
LONG_LOCK_TEXT = "Too many wrong PINs from this device. Wait 15 minutes, then try again."


class PinAttempts:
    """Wrong PINs per address, shared by the staff, owner and setup pages: 5 wrong in a minute lock the address out
    for a minute; the third lock-out within an hour locks it out for 15 minutes, is logged and listed on the owner
    page ("Someone tried wrong PINs 15 times at 21:40")."""

    def __init__(self, clock=time.monotonic, wall=time.time) -> None:
        self._clock = clock
        self._wall = wall
        self._failures: dict[str, deque[float]] = {}
        self._lockouts: dict[str, deque[float]] = {}     # when each lock-out started, per address
        self._wrong: dict[str, deque[float]] = {}        # every wrong PIN in the last hour, per address
        self._until: dict[str, tuple[float, str]] = {}
        self.alerts: deque[dict] = deque(maxlen=20)      # {"at": Unix ms, "wrong": n, "text": ...}, newest last
        self._lock = threading.Lock()

    def locked(self, client: str) -> str | None:
        """The message to show while `client` is locked out, else None."""
        with self._lock:
            until = self._until.get(client)
            if until is None:
                return None
            if self._clock() < until[0]:
                return until[1]
            del self._until[client]
            return None

    def failed(self, client: str) -> None:
        now = self._clock()
        with self._lock:
            self._prune(now)
            wrong = self._wrong.setdefault(client, deque())
            wrong.append(now)
            failures = self._failures.setdefault(client, deque())
            failures.append(now)
            while failures and now - failures[0] > FAILURE_WINDOW_S:
                failures.popleft()
            if len(failures) < MAX_FAILURES:
                return
            failures.clear()
            lockouts = self._lockouts.setdefault(client, deque())
            lockouts.append(now)
            if len(lockouts) < LOCKOUTS_FOR_LONG:
                self._until[client] = (now + SHORT_LOCK_S, SHORT_LOCK_TEXT)
                return
            lockouts.clear()
            self._until[client] = (now + LONG_LOCK_S, LONG_LOCK_TEXT)
            count = len(wrong)
            wall = self._wall()
            text = f"Someone tried wrong PINs {count} times at {dt.datetime.fromtimestamp(wall):%H:%M}"
            self.alerts.append({"at": round(wall * 1000), "wrong": count, "text": text})
        log.warning("%d wrong PINs from %s in the last hour: locked out for 15 minutes", count, client)

    def _prune(self, now: float) -> None:
        for table in (self._wrong, self._lockouts):
            for client in list(table):
                q = table[client]
                while q and now - q[0] > LOCKOUT_WINDOW_S:
                    q.popleft()
                if not q:
                    del table[client]
        for client in [c for c, f in self._failures.items() if not f or now - f[-1] > FAILURE_WINDOW_S]:
            del self._failures[client]
        for client in [c for c, (until, _) in self._until.items() if now >= until]:
            del self._until[client]
