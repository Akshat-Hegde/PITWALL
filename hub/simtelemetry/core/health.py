"""Per-rig health: packet rates per type, drops by reason, last seen and rig state."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from enum import Enum

from ..config import HealthConfig


class RigState(str, Enum):
    DRIVING = "driving"
    IN_MENU = "in_menu_paused"   # packets arriving, but no driving packets recently
    NO_DATA = "no_data"


@dataclass
class RigHealth:
    totals: Counter = field(default_factory=Counter)      # accepted packets by label
    drops: Counter = field(default_factory=Counter)       # dropped packets by reason
    rates: dict[str, float] = field(default_factory=dict)  # packets/s by label, last tick
    last_seen: float | None = None
    last_driving: float | None = None
    _rate_base: Counter = field(default_factory=Counter)
    _rate_base_time: float | None = None

    @property
    def total_rate(self) -> float:
        return sum(self.rates.values())


class HealthMonitor:
    def __init__(self, config: HealthConfig) -> None:
        self._config = config
        self._rigs: dict[str, RigHealth] = {}

    def _rig(self, ip: str, now: float) -> RigHealth:
        rig = self._rigs.get(ip)
        if rig is None:
            rig = self._rigs[ip] = RigHealth(_rate_base_time=now)  # first rate window starts now
        return rig

    def on_packet(self, ip: str, label: str, now: float, driving: bool) -> None:
        rig = self._rig(ip, now)
        rig.totals[label] += 1
        rig.last_seen = now
        if driving:
            rig.last_driving = now

    def on_drop(self, ip: str, reason: str, now: float) -> None:
        rig = self._rig(ip, now)
        rig.drops[reason] += 1
        rig.last_seen = now

    def tick(self, now: float) -> None:
        """Recompute rates from the counts since the previous tick (call about once a second)."""
        for rig in self._rigs.values():
            if rig._rate_base_time is not None and now > rig._rate_base_time:
                dt = now - rig._rate_base_time
                rig.rates = {label: (rig.totals[label] - rig._rate_base[label]) / dt for label in rig.totals}
            rig._rate_base = Counter(rig.totals)
            rig._rate_base_time = now

    def state(self, ip: str, now: float) -> RigState:
        rig = self._rigs.get(ip)
        if rig is None or rig.last_seen is None or now - rig.last_seen > self._config.no_data_after_s:
            return RigState.NO_DATA
        if rig.last_driving is not None and now - rig.last_driving <= self._config.no_motion_after_s:
            return RigState.DRIVING
        return RigState.IN_MENU

    def get(self, ip: str) -> RigHealth | None:
        return self._rigs.get(ip)
