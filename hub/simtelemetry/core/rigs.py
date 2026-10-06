"""Rig registry: rigs are identified by the source IP their packets arrive from.

A new IP gets the next free "Rig N" name. That auto name is saved to rigs.json so it stays
stable across restarts; a name in the config always takes precedence.
"""

from __future__ import annotations

import ipaddress
import json
import logging
from dataclasses import dataclass
from pathlib import Path

from ..config import AppConfig

log = logging.getLogger(__name__)


@dataclass
class Rig:
    ip: str
    auto_name: str
    config_name: str | None = None
    colour: str | None = None
    data_format: str | None = None
    session_id: str | None = None
    driver_name: str | None = None
    first_seen: float | None = None   # monotonic seconds; None for config rigs never seen

    @property
    def name(self) -> str:
        return self.config_name or self.auto_name


class RigRegistry:
    def __init__(self, config: AppConfig, state_file: Path | None = None) -> None:
        self._config = config
        self._state_file = state_file
        self._rigs: dict[str, Rig] = {}
        saved = self._load_saved()
        for ip, auto_name in saved.items():
            self._rigs[ip] = self._make(ip, auto_name)
        for rc in config.rigs:  # configured rigs show as "no data" until they send
            if rc.ip not in self._rigs:
                self._rigs[rc.ip] = self._make(rc.ip, self._next_auto_name())

    def _make(self, ip: str, auto_name: str) -> Rig:
        rc = self._config.rig_by_ip(ip)
        return Rig(ip=ip, auto_name=auto_name,
                   config_name=rc.name if rc else None,
                   colour=rc.colour if rc else None)

    def _next_auto_name(self) -> str:
        taken = {r.auto_name for r in self._rigs.values()} | {r.name for r in self._config.rigs if r.name}
        n = 1
        while f"Rig {n}" in taken:
            n += 1
        return f"Rig {n}"

    def _load_saved(self) -> dict[str, str]:
        if not self._state_file or not self._state_file.exists():
            return {}
        try:
            data = json.loads(self._state_file.read_text(encoding="utf-8"))
            return {str(ip): str(name) for ip, name in data.get("auto_names", {}).items()}
        except (OSError, ValueError, AttributeError) as exc:
            log.warning("Ignoring unreadable rig registry %s: %s", self._state_file, exc)
            return {}

    def save(self) -> None:
        if not self._state_file:
            return
        self._state_file.parent.mkdir(parents=True, exist_ok=True)
        data = {"auto_names": {ip: rig.auto_name for ip, rig in self._rigs.items()}}
        self._state_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def see(self, ip: str, now: float, data_format: str | None, session_id: str | None) -> Rig:
        rig = self._rigs.get(ip)
        if rig is None:
            rig = self._make(ip, self._next_auto_name())
            self._rigs[ip] = rig
            self.save()
        if rig.first_seen is None:
            rig.first_seen = now
            where = " (this PC)" if ipaddress.ip_address(ip).is_loopback else ""
            log.info("New rig detected: %s%s -> %s (format %s)", ip, where, rig.name, data_format or "?")
        if data_format and data_format != rig.data_format:
            if rig.data_format is not None:
                log.warning("%s (%s) changed packet format %s -> %s", rig.name, ip, rig.data_format, data_format)
            rig.data_format = data_format
        if session_id and session_id != rig.session_id:
            if rig.session_id is not None:
                log.info("%s (%s) new session %s", rig.name, ip, session_id)
            rig.session_id = session_id
        return rig

    def set_driver_name(self, ip: str, name: str | None) -> None:
        rig = self._rigs.get(ip)
        if rig and name and name != rig.driver_name:
            log.info("%s (%s) driver: %s", rig.name, ip, name)
            rig.driver_name = name

    def get(self, ip: str) -> Rig | None:
        return self._rigs.get(ip)

    def all(self) -> list[Rig]:
        return sorted(self._rigs.values(), key=lambda r: (r.name, r.ip))
