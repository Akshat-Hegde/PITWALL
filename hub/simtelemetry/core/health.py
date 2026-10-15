"""Per-rig health: packet rates per type, drops by reason, last seen and rig state."""

from __future__ import annotations

import datetime as dt
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
    last_accepted: float | None = None    # last packet the hub could read
    last_wrong: float | None = None       # last packet in the wrong format (wrong game settings)
    _rate_base: Counter = field(default_factory=Counter)
    _rate_base_time: float | None = None

    @property
    def total_rate(self) -> float:
        return sum(self.rates.values())


# Drop reasons that mean the game is set up wrong (e.g. UDP Format), not a hub problem.
WRONG_FORMAT_REASONS = frozenset({"too_short", "unsupported_format", "unknown_packet_id", "size_mismatch"})


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
        rig.last_accepted = now
        if driving:
            rig.last_driving = now

    def on_drop(self, ip: str, reason: str, now: float) -> None:
        rig = self._rig(ip, now)
        rig.drops[reason] += 1
        rig.last_seen = now
        if reason in WRONG_FORMAT_REASONS:
            rig.last_wrong = now

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

    def wrong_format(self, ip: str, now: float) -> bool:
        """Only wrong-format packets lately: the rig's game settings are wrong ("Wrong game settings")."""
        rig = self._rigs.get(ip)
        window = self._config.no_data_after_s
        if rig is None or rig.last_wrong is None or now - rig.last_wrong > window:
            return False
        return rig.last_accepted is None or now - rig.last_accepted > window

    def seconds_since_driving(self, ip: str, now: float) -> float | None:
        """Seconds since the last driving packet; None if this rig has not driven since the hub started."""
        rig = self._rigs.get(ip)
        return None if rig is None or rig.last_driving is None else max(0.0, now - rig.last_driving)

    def get(self, ip: str) -> RigHealth | None:
        return self._rigs.get(ip)

    def forget(self, ip: str) -> None:
        self._rigs.pop(ip, None)


# --- silent rigs ---------------------------------------------------------------------------

SILENT_WARN_AFTER_S = 600.0   # a rig silent this long during opening hours gets a staff warning


def opened_at(now: dt.datetime, open_hour: int, close_hour: int) -> dt.datetime | None:
    """When the cafe opened for the opening period `now` is in, or None while closed.
    A closing hour at or before the opening hour means the cafe closes after midnight."""
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    hour = now.hour
    if open_hour < close_hour:
        return today + dt.timedelta(hours=open_hour) if open_hour <= hour < close_hour else None
    if hour >= open_hour:
        return today + dt.timedelta(hours=open_hour)
    if hour < close_hour:
        return today - dt.timedelta(days=1) + dt.timedelta(hours=open_hour)
    return None


class SilentRigWatch:
    """Warn about a rig silent for over 10 minutes, only during opening hours and at most once per rig per day.

    Silence counts from the opening time at the earliest, so rigs left off overnight aren't flagged at opening.
    Once shown, the warning stays while the rig is silent; after the rig sends again it isn't shown again that day.
    """

    def __init__(self) -> None:
        self._shown_day: dict[str, dt.date] = {}
        self._showing: set[str] = set()

    def check(self, rig_id: str, silent_s: float | None, now: dt.datetime, open_hour: int, close_hour: int) -> bool:
        opened = opened_at(now, open_hour, close_hour)
        if silent_s is None or opened is None:
            self._showing.discard(rig_id)
            return False
        silent_s = min(silent_s, (now - opened).total_seconds())
        if silent_s <= SILENT_WARN_AFTER_S:
            self._showing.discard(rig_id)
            return False
        day = opened.date()
        if self._shown_day.get(rig_id) == day:
            return rig_id in self._showing
        self._shown_day[rig_id] = day
        self._showing.add(rig_id)
        return True
