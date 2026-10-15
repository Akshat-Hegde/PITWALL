"""Watching the hub's own network address.

Every rig sends telemetry to the hub's address and the check-in stickers point at it, so when it changes (the router
gave this PC a new one) the owner must be told. The address last shown is kept in <data>/hub-address.json; while the
current one differs, staff and setup pages show a warning until someone presses "OK, done". Never shown on the TV.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

ADDRESS_FILE = "hub-address.json"


def change_message(old: str, new: str) -> str:
    return (f"This PC's network address changed from {old} to {new}. On every rig set UDP IP Address to {new}, "
            f"and reprint the check-in stickers. To stop this happening, reserve the address in your router "
            f"(see the setup guide).")


class AddressWatch:
    def __init__(self, path: Path | None, current: Callable[[], str | None], clock=time.time) -> None:
        self._path = path               # None: kept in memory only (tests, replays)
        self.current = current
        self._clock = clock
        self._known: str | None = None
        self._loaded = False

    def _load(self) -> str | None:
        if not self._loaded:
            self._loaded = True
            if self._path is not None:
                try:
                    data = json.loads(self._path.read_text(encoding="utf-8"))
                    self._known = str(data["address"]) if data.get("address") else None
                except FileNotFoundError:
                    pass
                except (OSError, ValueError, AttributeError, KeyError, TypeError) as exc:
                    log.warning("Ignoring unreadable %s: %s", self._path, exc)
        return self._known

    def _store(self, address: str) -> None:
        self._known = address
        if self._path is None:
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"address": address, "at": round(self._clock() * 1000)}) + "\n",
                           encoding="utf-8")
            tmp.replace(self._path)
        except OSError:
            log.exception("Could not save %s", self._path)

    def warning(self) -> dict[str, Any] | None:
        """The address-change warning, or None. The first address ever seen is stored without a warning."""
        now = self.current()
        if not now:
            return None                 # no network right now: nothing to compare
        known = self._load()
        if known is None:
            self._store(now)
            return None
        if known == now:
            return None
        return {"code": "address_changed", "rig_id": None, "message": change_message(known, now),
                "old_address": known, "new_address": now}

    def acknowledge(self) -> str | None:
        """'OK, done': the current address becomes the known one."""
        now = self.current()
        if now:
            if now != self._load():
                log.info("Hub address change acknowledged: now %s", now)
            self._store(now)
        return now
