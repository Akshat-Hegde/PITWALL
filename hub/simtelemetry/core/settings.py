"""Settings the cafe owner changes from /setup, kept in <data_dir>/settings.json and layered over hub.toml.

hub.toml stays the place for technical settings (ports, recorder, map); these are the owner's own.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import re
import zipfile
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError, ValidationInfo, field_validator, model_validator

from ..config import AppConfig
from .pins import hash_pin, is_hashed

log = logging.getLogger(__name__)
_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")
_PIN = re.compile(r"^(\d{4,8})?$")


class CafeSettings(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    tagline: str = Field("", max_length=60)
    accent: str = "#E10600"
    logo: str | None = None
    owner_pin: str                  # stored as a salted hash (core/pins.py); plain digits are hashed on the way in
    staff_pin: str = ""
    open_hour: int = Field(10, ge=0, le=23)
    close_hour: int = Field(22, ge=1, le=24)
    setup_done: bool = False
    wifi_ssid: str = ""             # at most 32 BYTES of UTF-8 (checked below)
    wifi_password: str = Field("", max_length=63)
    wifi_security: str = "WPA"

    @field_validator("accent")
    @classmethod
    def _hex(cls, value: str) -> str:
        if not _HEX.match(value):
            raise ValueError("accent must be a colour like #E10600")
        return value.upper()

    @field_validator("wifi_ssid")
    @classmethod
    def _strip_ssid(cls, value: str) -> str:
        return value.strip()                  # whitespace only means no Wi-Fi

    @field_validator("owner_pin", "staff_pin")
    @classmethod
    def _digits(cls, value: str, info: ValidationInfo) -> str:
        if is_hashed(value):
            return value
        if not _PIN.match(value) or (info.field_name == "owner_pin" and not value):
            raise ValueError("PINs are 4 to 8 digits")
        return hash_pin(value)

    @model_validator(mode="after")
    def _wifi(self) -> "CafeSettings":
        if self.wifi_security not in ("WPA", "nopass"):
            raise ValueError("Wi-Fi security must be WPA or nopass")
        if not self.wifi_ssid:
            return self
        if len(self.wifi_ssid.encode("utf-8")) > 32:
            raise ValueError("a Wi-Fi name is at most 32 bytes (fewer letters if it has accents or emoji)")
        if self.wifi_security == "WPA" and not 8 <= len(self.wifi_password) <= 63:
            raise ValueError("a WPA Wi-Fi password is 8 to 63 characters")
        if self.wifi_security == "nopass" and self.wifi_password:
            raise ValueError("an open Wi-Fi network has no password")
        return self

    @model_validator(mode="after")
    def _hours(self) -> "CafeSettings":
        if self.close_hour <= self.open_hour:
            raise ValueError("closing hour must be after opening hour")
        return self


class SettingsDamaged(Exception):
    """settings.json exists but can't be read or doesn't make sense."""


class SettingsStore:
    def __init__(self, data_dir: Path) -> None:
        self.path = data_dir / "settings.json"
        self.branding_dir = data_dir / "branding"

    def read(self) -> CafeSettings | None:
        """The saved settings, None when there are none yet. Raises SettingsDamaged when the file can't be used.

        PINs saved in plain text by older versions are hashed and the file is rewritten at once.
        """
        try:
            text = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise SettingsDamaged(str(exc)) from exc
        try:
            raw = json.loads(text)
            s = CafeSettings.model_validate(raw)
        except (ValidationError, ValueError, TypeError) as exc:
            raise SettingsDamaged(str(exc)) from exc
        if any(isinstance(raw.get(k), str) and raw[k] and not is_hashed(raw[k]) for k in ("owner_pin", "staff_pin")):
            try:
                self.save(s)
                log.info("PINs in %s are now stored hashed", self.path)
            except OSError as exc:
                log.warning("Could not rewrite %s with hashed PINs (%s)", self.path, exc)
        return s

    def load(self) -> CafeSettings | None:
        try:
            return self.read()
        except SettingsDamaged as exc:
            log.warning("Ignoring unreadable %s (%s); using hub.toml values", self.path, exc)
            return None

    def save(self, settings: CafeSettings) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(json.dumps(settings.model_dump(), indent=2))
            f.flush()
            os.fsync(f.fileno())               # on disk before the rename, or a power cut can leave an empty file
        os.replace(tmp, self.path)             # atomic: a power cut never leaves half a file


def apply_settings(config: AppConfig, s: CafeSettings) -> None:
    config.cafe.name = s.name
    config.cafe.tagline = s.tagline
    config.cafe.logo = s.logo
    config.cafe.branding = {**config.cafe.branding, "--brand-accent": s.accent}
    config.owner.pin = s.owner_pin
    config.staff.pin = s.staff_pin
    config.owner.open_hour, config.owner.close_hour = s.open_hour, s.close_hour
    config.cafe.wifi_ssid, config.cafe.wifi_password = s.wifi_ssid, s.wifi_password
    config.cafe.wifi_security = s.wifi_security


def recover_damaged_settings(store: SettingsStore, backups_dir: Path, now: dt.datetime) -> str | None:
    """At start-up: when settings.json is damaged, put it aside as settings.json.broken-<time> and restore the
    newest good copy from the backup zips. Returns a plain-English warning for the staff and setup pages,
    or None when the file was fine (or absent)."""
    try:
        store.read()
        return None
    except SettingsDamaged as exc:
        log.error("%s is damaged (%s)", store.path, exc)
    broken = store.path.with_name(f"{store.path.name}.broken-{now:%Y%m%d-%H%M%S}")
    try:
        os.replace(store.path, broken)
        log.error("Moved the damaged settings to %s", broken)
    except OSError as move_exc:
        log.error("Could not move %s aside (%s)", store.path, move_exc)
        return ("The cafe settings file can't be read and couldn't be moved aside. Restart the PC; "
                "if this message stays, contact support.")
    from .backup import PATTERN
    zips = sorted(backups_dir.glob(PATTERN), reverse=True) if backups_dir.is_dir() else []
    for z in zips:
        try:
            with zipfile.ZipFile(z) as archive:
                raw = archive.read("settings.json")
            store.save(CafeSettings.model_validate_json(raw))
        except (KeyError, OSError, ValueError, ValidationError, zipfile.BadZipFile) as exc:
            log.warning("No usable settings in %s (%s)", z, exc)
            continue
        when = dt.datetime.fromtimestamp(z.stat().st_mtime).strftime("%d %b %H:%M")
        log.warning("Restored the cafe settings from %s", z)
        return (f"The cafe settings were damaged, so the hub put back the copy from the backup of {when}. "
                "Check the setup page in case something changed since then.")
    return ("The cafe settings were damaged and there was no backup to restore them from. "
            "Open the setup page and set the hub up again with a new setup code.")
