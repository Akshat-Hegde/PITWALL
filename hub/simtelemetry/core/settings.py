"""Settings the cafe owner changes from /setup, kept in <data_dir>/settings.json and layered over hub.toml.

hub.toml stays the place for technical settings (ports, recorder, map); these are the owner's own.
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from ..config import AppConfig

log = logging.getLogger(__name__)
_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")
_PIN = re.compile(r"^(\d{4,8})?$")


class CafeSettings(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    tagline: str = Field("", max_length=60)
    accent: str = "#E10600"
    logo: str | None = None
    owner_pin: str = Field(min_length=4, max_length=8)
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
    def _digits(cls, value: str) -> str:
        if not _PIN.match(value):
            raise ValueError("PINs are 4 to 8 digits")
        return value

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


class SettingsStore:
    def __init__(self, data_dir: Path) -> None:
        self.path = data_dir / "settings.json"
        self.branding_dir = data_dir / "branding"

    def load(self) -> CafeSettings | None:
        try:
            return CafeSettings.model_validate_json(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, ValidationError, ValueError) as exc:
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
