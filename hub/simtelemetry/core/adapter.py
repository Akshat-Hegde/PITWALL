"""Interface every game adapter implements. Core code never imports a specific game."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from .laps import LapEvent, LiveLap


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
    lap_events: list[LapEvent] = field(default_factory=list)
    lap_update: bool = False        # the live lap changed (new lap timing data)


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
    max_rpm: int | None = None         # the car's rev limit, for the TV's rev bar
    tyre_class: str | None = None      # soft/medium/hard/inter/wet/other/unknown
    tyre_label: str | None = None      # what to print, e.g. "C3"
    tyre_age_laps: int | None = None
    sector_starts_m: tuple[float, float, float] | None = None  # lap distance where S1/S2/S3 start
    # Session conditions
    weather: str | None = None         # clear, light_cloud, overcast, light_rain, heavy_rain, storm
    air_temp_c: int | None = None
    track_temp_c: int | None = None
    time_left_s: int | None = None
    # Car detail for the TV. Per-wheel values are ordered front-left, front-right, rear-left, rear-right.
    drs_open: bool | None = None
    drs_allowed: bool | None = None
    rev_lights_pct: int | None = None
    ers_pct: float | None = None
    ers_mode: str | None = None        # none, medium, hotlap, overtake
    fuel_kg: float | None = None
    fuel_laps: float | None = None
    pit_limiter: bool | None = None
    steer: float | None = None         # -1 (full left) .. 1 (full right)
    g_lat: float | None = None
    g_long: float | None = None
    tyre_surface_c: tuple[int, int, int, int] | None = None
    tyre_inner_c: tuple[int, int, int, int] | None = None
    tyre_pressure_psi: tuple[float, float, float, float] | None = None
    tyre_wear_pct: tuple[float, float, float, float] | None = None
    brake_c: tuple[int, int, int, int] | None = None
    damage: dict[str, int] | None = None  # percentages: front_wing, rear_wing, floor, diffuser, sidepod, ...
    top_speed_lap_kph: int | None = None
    top_speed_kph: int | None = None   # this session
    top_speed_lap_number: int | None = None
    slide_deg: float | None = None     # how sideways the car is: chassis vs direction of travel
    saves: int = 0                     # slides caught this session ("SAVE!")
    last_save_at_ms: int | None = None # Unix ms
    last_save_peak_deg: float | None = None
    # Assists, for Pro / Open laps. None until the game has reported them.
    assists: dict[str, int] | None = None

    @property
    def pro(self) -> bool | None:
        """True when every assist is off (a Pro lap), False when any is on, None while unknown."""
        a = self.assists
        if a is None or not PRO_ASSISTS.keys() <= a.keys():
            return None
        return all(a[k] == PRO_ASSISTS[k] for k in PRO_ASSISTS)


# Assist settings a Pro lap needs (docs/LAP_ASSUMPTIONS.md A16): everything off, manual gears.
PRO_ASSISTS = {"traction_control": 0, "anti_lock_brakes": 0, "steering": 0, "braking": 0, "gearbox": 1,
               "racing_line": 0}


class GameAdapter(Protocol):
    game: str

    def check(self, data: bytes, source: str) -> Checked: ...

    def decode(self, checked: Checked, data: bytes, source: str) -> DecodeResult: ...

    def live_summary(self, source: str) -> LiveSummary | None: ...

    def live_lap(self, source: str) -> LiveLap | None: ...

    def is_supported_format(self, data_format: str) -> bool: ...
