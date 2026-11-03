"""Guest Wi-Fi sharing: the one place that builds the WIFI: QR string shown on the TV."""

from __future__ import annotations

import re
from typing import Any

from ..config import AppConfig, FeaturesConfig

_SPECIAL = re.compile(r'([\\;,:"])')


def _escape(text: str) -> str:
    return _SPECIAL.sub(lambda m: "\\" + m.group(1), text)


def wifi_string(ssid: str, password: str, security: str) -> str:
    if security == "nopass" or not password:
        return f"WIFI:T:nopass;S:{_escape(ssid)};;"
    return f"WIFI:T:WPA;S:{_escape(ssid)};P:{_escape(password)};;"


def wifi_share(config: AppConfig, features: FeaturesConfig | None = None) -> dict[str, Any] | None:
    """`{"ssid", "qr"}` for the feed and the race podium, or None when sharing is off or no SSID is set.
    `features`: the effective flags (Hub.features: hub.toml and the licence); default the hub.toml ones."""
    c = config.cafe
    if not ((features or config.features).sharing and c.wifi_ssid):
        return None
    return {"ssid": c.wifi_ssid, "qr": wifi_string(c.wifi_ssid, c.wifi_password, c.wifi_security)}
