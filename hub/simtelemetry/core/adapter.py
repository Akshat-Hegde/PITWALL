"""Interface every game adapter implements. Core code never imports a specific game."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(slots=True)
class Checked:
    """Result of the cheap per-datagram check, run on the receive path."""

    ok: bool
    reason: str | None = None       # drop reason when not ok
    label: str | None = None        # packet type name for health counters, e.g. "Motion"
    data_format: str | None = None  # wire format the source is sending, e.g. "2025"
    session_id: str | None = None
    payload: Any = None             # adapter-private, passed back to decode()


@dataclass(slots=True)
class DecodeResult:
    driving: bool = False           # True for packets that mean "car is on track, player in control"


@dataclass(slots=True)
class LiveSummary:
    """Latest game-agnostic values per rig, for status lines and the dashboard feed.

    Units follow docs/WS_SCHEMA.md: metres, km/h, pedals 0-1. Lap timing fields here are
    raw game values for the console only; the dashboard's lap model comes with lap tracking.
    """

    driver_name: str | None = None
    track: str | None = None
    track_key: str | None = None       # "<game>:<track id>", None while unknown
    track_length_m: float | None = None
    session_type: str | None = None
    lap: int | None = None
    current_lap_ms: int | None = None
    speed_kph: int | None = None
    position: tuple[float, float] | None = None  # world (x, z): the horizontal plane
    gear: int | None = None            # -1 reverse, 0 neutral
    throttle: float | None = None
    brake: float | None = None
    rpm: int | None = None
    tyre_class: str | None = None      # soft/medium/hard/inter/wet/other/unknown
    tyre_label: str | None = None      # what to print, e.g. "C3"
    tyre_age_laps: int | None = None


class GameAdapter(Protocol):
    game: str

    def check(self, data: bytes, source: str) -> Checked: ...

    def decode(self, checked: Checked, data: bytes, source: str) -> DecodeResult: ...

    def live_summary(self, source: str) -> LiveSummary | None: ...

    def is_supported_format(self, data_format: str) -> bool: ...
