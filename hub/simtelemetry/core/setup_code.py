"""One-time setup code. The installer makes it (`<exe> setup-code --new`) and shows it on its last page; first-run
/setup accepts changes only with it, so nobody else on the cafe network can claim the hub first.
Deleted once setup is done (after that the owner PIN guards /setup)."""

from __future__ import annotations

import hmac
import os
import secrets
import time
from collections.abc import Callable
from pathlib import Path

ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"     # no 0/O, 1/I/L: easy to read off a screen
MAX_TRIES = 10
LOCK_S = 60


class SetupLocked(Exception):
    def __init__(self, seconds_left: int) -> None:
        super().__init__(f"Too many wrong setup codes. Try again in {seconds_left} s.")
        self.seconds_left = seconds_left


def _norm(code: str) -> str:
    return "".join(ch for ch in code.upper() if ch.isalnum())


class SetupCode:
    def __init__(self, data_dir: Path, clock: Callable[[], float] = time.monotonic) -> None:
        self.path = data_dir / "setup-code.txt"
        self._clock = clock
        self._wrong = 0
        self._locked_until = 0.0

    def current(self) -> str | None:
        try:
            code = self.path.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        return code or None

    def new(self) -> str:
        raw = "".join(secrets.choice(ALPHABET) for _ in range(8))
        code = f"{raw[:4]}-{raw[4:]}"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(code + "\n", encoding="utf-8")
        os.replace(tmp, self.path)
        return code

    def ensure(self) -> str:
        return self.current() or self.new()

    def check(self, given: str | None) -> bool:
        now = self._clock()
        if now < self._locked_until:
            raise SetupLocked(int(self._locked_until - now) + 1)
        code = self.current()
        ok = bool(code and given) and hmac.compare_digest(_norm(given or "").encode(), _norm(code or "").encode())
        if ok:
            self._wrong = 0
            return True
        self._wrong += 1
        if self._wrong >= MAX_TRIES:
            self._wrong = 0
            self._locked_until = now + LOCK_S
        return False

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)
