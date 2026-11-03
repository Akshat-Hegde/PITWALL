"""Rig registry: rigs are identified by the source IP their packets arrive from.

A new IP gets the next free "Rig N" name (its number) once its first valid packet arrives; wrong-format and garbage
senders never become rigs. The auto name is saved to rigs.json so it stays stable across restarts.

The owner edits rigs on the setup page: a name (rename), forget a rig that no longer exists, and "same rig as…"
(merge) when a rig PC got a new address. Names and colours given there are saved in rigs.json too:

    {"auto_names": {ip: "Rig N"}, "names": {ip: name}, "colours": {ip: "#rrggbb"}, "forgotten": [ip, ...],
     "pending_names": {"N": name}}

A name from the setup page wins over a name in hub.toml, which wins over the auto name.

`pending_names` are rig names baked into a cafe's installer (provision.py), by rig number: the rig that gets (or
already has) number N takes that name once, unless it was already given a name on the setup page. A used name
leaves the list. Pending names never look like "Rig N", so they never change how rigs are numbered.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import os
import re
import tempfile
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config import AppConfig
from .drivers import ZWJ, ZWNJ, _keep_joiner

log = logging.getLogger(__name__)

RIG_NAME_MAX = 16   # what the TV fits
_RIG_N = re.compile(r"rig\s*0*(\d+)", re.IGNORECASE)


class RigError(ValueError):
    """A rig edit that can't be done; the message is shown to the owner as-is."""


@dataclass
class Rig:
    ip: str
    auto_name: str
    config_name: str | None = None
    colour: str | None = None
    data_format: str | None = None
    session_id: str | None = None
    driver_name: str | None = None
    first_seen: float | None = None   # monotonic seconds; None for rigs not seen since the hub started
    custom_name: str | None = None    # given on the setup page

    @property
    def name(self) -> str:
        return self.custom_name or self.config_name or self.auto_name

    @property
    def number(self) -> int | None:
        """The rig's number from its auto name ("Rig 5" -> 5), stable in rigs.json (a merge keeps it); the licence
        covers the first N numbers. None when rigs.json was edited by hand to something else."""
        m = _RIG_N.fullmatch(self.auto_name.strip())
        return int(m.group(1)) if m else None


def clean_rig_name(value: Any) -> str | None:
    """A rig name as typed on the setup page; None (empty) means "back to its number". Invisible characters are
    dropped, except the joiners that shape an Indic (or other non-Latin) word, as in driver names."""
    raw = unicodedata.normalize("NFC", str(value or ""))
    text = "".join(c for i, c in enumerate(raw)
                   if unicodedata.category(c) not in ("Cc", "Cf") or (c in (ZWJ, ZWNJ) and _keep_joiner(raw, i)))
    name = " ".join(text.split())
    if len(name) > RIG_NAME_MAX:
        raise RigError(f"A rig name can be at most {RIG_NAME_MAX} characters.")
    return name or None


def _by_number(rig: Rig) -> tuple[int, str]:
    return (rig.number if rig.number is not None else 1 << 30, rig.ip)


def _pending_names(raw: Any) -> dict[int, str]:
    """rigs.json "pending_names" ({"3": "Senna"}); entries that don't make sense are left out."""
    out: dict[int, str] = {}
    for key, name in (raw.items() if isinstance(raw, dict) else ()):
        if isinstance(key, str) and key.isdigit() and isinstance(name, str) and name.strip() and int(key) >= 1:
            out[int(key)] = name
    return out


class RigRegistry:
    def __init__(self, config: AppConfig, state_file: Path | None = None) -> None:
        self._config = config
        self._state_file = state_file
        self._rigs: dict[str, Rig] = {}
        saved = self._load_saved()
        self._names: dict[str, str] = saved["names"]
        self._colours: dict[str, str] = saved["colours"]
        self._forgotten: set[str] = saved["forgotten"]
        self._pending: dict[int, str] = saved["pending_names"]
        for ip, auto_name in saved["auto_names"].items():
            self._rigs[ip] = self._make(ip, auto_name)
        for rc in config.rigs:  # configured rigs show as "no data" until they send
            if rc.ip not in self._rigs and rc.ip not in self._forgotten:
                self._rigs[rc.ip] = self._make(rc.ip, self._next_auto_name())
        if self._pending and any([self._claim_pending(rig) for rig in sorted(self._rigs.values(), key=_by_number)]):
            self.save()

    def _make(self, ip: str, auto_name: str) -> Rig:
        rc = self._config.rig_by_ip(ip)
        return Rig(ip=ip, auto_name=auto_name,
                   config_name=rc.name if rc else None,
                   colour=self._colours.get(ip) or (rc.colour if rc else None),
                   custom_name=self._names.get(ip))

    def _claim_pending(self, rig: Rig) -> bool:
        """Give `rig` the pending name for its number (see the module docstring). True when one was used up."""
        name = self._pending.pop(rig.number, None) if rig.number is not None else None
        if name is None:
            return False
        try:
            name = clean_rig_name(name)
        except RigError:
            name = None
        if rig.custom_name or not name or _RIG_N.fullmatch(name):
            return True                      # a name from the setup page wins; a bad one is dropped
        if any(r is not rig and r.name.casefold() == name.casefold() for r in self._rigs.values()):
            log.warning("Pending rig name %r not used: another rig already has it", name)
            return True
        rig.custom_name = name
        log.info("%s (%s) named %s from the cafe's installer", rig.auto_name, rig.ip, name)
        return True

    def _next_auto_name(self) -> str:
        """The lowest "Rig N" not used by any rig's number or name (a rig renamed "Rig 7" takes 7 too)."""
        names = [r.auto_name for r in self._rigs.values()]
        names += [r.custom_name for r in self._rigs.values() if r.custom_name]
        names += [r.name for r in self._config.rigs if r.name]
        taken = {int(m.group(1)) for name in names if (m := _RIG_N.fullmatch(name.strip()))}
        n = 1
        while n in taken:
            n += 1
        return f"Rig {n}"

    def _load_saved(self) -> dict[str, Any]:
        empty: dict[str, Any] = {"auto_names": {}, "names": {}, "colours": {}, "forgotten": set(), "pending_names": {}}
        if not self._state_file or not self._state_file.exists():
            return empty
        try:
            data = json.loads(self._state_file.read_text(encoding="utf-8"))
            return {
                "auto_names": {str(ip): str(name) for ip, name in data.get("auto_names", {}).items()},
                "names": {str(ip): str(name) for ip, name in (data.get("names") or {}).items() if name},
                "colours": {str(ip): str(c) for ip, c in (data.get("colours") or {}).items() if c},
                "forgotten": {str(ip) for ip in (data.get("forgotten") or [])},
                "pending_names": _pending_names(data.get("pending_names")),
            }
        except (OSError, ValueError, AttributeError, TypeError) as exc:
            log.warning("Ignoring unreadable rig registry %s: %s", self._state_file, exc)
            return empty

    def save(self) -> None:
        if not self._state_file:
            return
        rigs = list(self._rigs.items())          # snapshots: never iterate a dict another caller may change
        colours = dict(self._colours)
        data = {"auto_names": {ip: rig.auto_name for ip, rig in rigs},
                "names": {ip: rig.custom_name for ip, rig in rigs if rig.custom_name},
                "colours": {ip: c for ip, c in colours.items() if ip in dict(rigs)},
                "forgotten": sorted(list(self._forgotten))}
        if self._pending:
            data["pending_names"] = {str(n): name for n, name in sorted(self._pending.items())}
        tmp = None
        try:
            self._state_file.parent.mkdir(parents=True, exist_ok=True)
            # A unique temp file next to rigs.json, so two saves never write the same temp file.
            fd, tmp = tempfile.mkstemp(prefix=self._state_file.name + ".", suffix=".tmp",
                                       dir=self._state_file.parent)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(json.dumps(data, indent=2))
            os.replace(tmp, self._state_file)
            tmp = None
        except OSError:
            log.exception("Could not save %s", self._state_file)
        finally:
            if tmp is not None:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass

    def see(self, ip: str, now: float, data_format: str | None, session_id: str | None) -> Rig:
        """A valid packet from `ip`: registers the rig on its first one."""
        rig = self._rigs.get(ip)
        if rig is None:
            self._forgotten.discard(ip)          # a forgotten rig that sends again is a rig again
            rig = self._make(ip, self._next_auto_name())
            self._rigs[ip] = rig
            self._claim_pending(rig)
            self.save()
        if rig.first_seen is None:
            rig.first_seen = now
            where = " (this PC)" if ipaddress.ip_address(ip).is_loopback else ""
            log.info("New rig detected: %s%s -> %s (format %s)", ip, where, rig.name, data_format or "?")
        self.note_format(ip, data_format)
        if session_id and session_id != rig.session_id:
            if rig.session_id is not None:
                log.info("%s (%s) new session %s", rig.name, ip, session_id)
            rig.session_id = session_id
        return rig

    def note_format(self, ip: str, data_format: str | None) -> None:
        """The packet format a known rig sends, also when its packets are rejected (wrong format)."""
        rig = self._rigs.get(ip)
        if rig is not None and data_format and data_format != rig.data_format:
            if rig.data_format is not None:
                log.warning("%s (%s) changed packet format %s -> %s", rig.name, ip, rig.data_format, data_format)
            rig.data_format = data_format

    def set_driver_name(self, ip: str, name: str | None) -> None:
        rig = self._rigs.get(ip)
        if rig and name and name != rig.driver_name:
            log.info("%s (%s) driver: %s", rig.name, ip, name)
            rig.driver_name = name

    def get(self, ip: str) -> Rig | None:
        return self._rigs.get(ip)

    def all(self) -> list[Rig]:
        return sorted(list(self._rigs.values()), key=lambda r: (r.name, r.ip))

    # --- edits from the setup page -----------------------------------------------------------

    def _rig(self, ip: str) -> Rig:
        rig = self._rigs.get(ip)
        if rig is None:
            raise RigError("That rig isn't there any more. Reload the page.")
        return rig

    def rename(self, ip: str, name: Any) -> Rig:
        rig = self._rig(ip)
        new = clean_rig_name(name)
        if new is not None:
            other = next((r for r in self._rigs.values()
                          if r.ip != ip and r.name.casefold() == new.casefold()), None)
            if other is not None:
                raise RigError(f"Another rig is already called {other.name}.")
        rig.custom_name = new
        log.info("Rig %s renamed to %s", ip, rig.name)
        self.save()
        return rig

    def forget(self, ip: str) -> None:
        rig = self._rig(ip)
        del self._rigs[ip]
        self._colours.pop(ip, None)
        if self._config.rig_by_ip(ip) is not None:
            self._forgotten.add(ip)               # else hub.toml would bring it back at the next start
        log.info("Forgot %s (%s)", rig.name, ip)
        self.save()

    def merge(self, old_ip: str, new_ip: str) -> Rig:
        """`new_ip` is the same rig PC as `old_ip` (it got a new address): it takes the old rig's number, name
        and colour, and the old entry is forgotten."""
        old, new = self._rig(old_ip), self._rig(new_ip)
        if old is new:
            raise RigError("Choose a different rig.")
        new.auto_name = old.auto_name
        new.custom_name = old.custom_name or old.config_name
        new.colour = old.colour
        if old.colour:
            self._colours[new_ip] = old.colour
        else:
            self._colours.pop(new_ip, None)
        self.forget(old_ip)
        log.info("%s now at %s (was %s)", new.name, new_ip, old_ip)
        return new
