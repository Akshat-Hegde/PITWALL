"""Game-agnostic lap model: lap events from a game adapter -> completed laps, bests, sector ratings.

Adapters turn game packets into the events below (see adapters/f1/laps.py and
docs/LAP_ASSUMPTIONS.md); LapBook keeps everything the dashboard needs:

- completed laps, newest first;
- per track: session bests (all rigs, since the hub started) and personal bests (per driver);
- per rig: best lap on its current track, live lap with rated sectors, last lap's rated sectors.

Only laps that are valid and not out laps ("counted" laps) set bests. Ratings follow the
TV timing convention: purple = equal to or faster than the session best, green = this
driver's personal best, yellow = slower. Live sectors are rated against existing bests
without changing them, because the lap may still be invalidated before the line.
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)
lap_debug = logging.getLogger("simtelemetry.lapdebug")  # enabled by --lap-debug

RECENT_LAPS_MAX = 20

SESSION_BEST = "session_best"
PERSONAL_BEST = "personal_best"
NORMAL = "normal"


# --- what adapters provide ---------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class LiveLap:
    """The lap in progress, as the game reports it."""

    number: int
    distance_m: float            # may be negative before the line is first crossed
    current_ms: int
    valid: bool
    sector: int                  # 0..2
    sector1_ms: int | None       # completed sectors of this lap
    sector2_ms: int | None
    last_ms: int | None          # previous lap's time
    out_lap: bool = False


@dataclass(frozen=True, slots=True)
class LapStarted:
    lap: int
    game_time: float
    out_lap: bool = False


@dataclass(frozen=True, slots=True)
class LapCompleted:
    lap: int
    game_time: float
    lap_ms: int
    sectors_ms: tuple[int, int, int] | None
    valid: bool
    out_lap: bool = False
    source: str = ""             # where the numbers came from, for --lap-debug


@dataclass(frozen=True, slots=True)
class LapInvalidated:
    lap: int
    game_time: float


@dataclass(frozen=True, slots=True)
class LapReset:
    """The in-progress lap's history is no longer continuous (flashback, restart, new session)."""

    reason: str                  # "flashback", "lap_number_decreased", "session_changed"
    game_time: float
    lap: int | None = None
    detail: str = ""


@dataclass(frozen=True, slots=True)
class LapRetracted:
    """A lap reported as completed was undone by the game (e.g. a flashback back across the line)."""

    lap: int
    game_time: float
    reason: str = ""


@dataclass(frozen=True, slots=True)
class HistoryUpdate:
    """Debug only: the game's lap history changed."""

    game_time: float
    num_laps: int
    changed: tuple[int, ...]     # lap numbers whose entries changed


LapEvent = LapStarted | LapCompleted | LapInvalidated | LapReset | LapRetracted | HistoryUpdate


def describe(event: LapEvent) -> str:
    """One line for --lap-debug."""
    name = {LapStarted: "lap_started", LapCompleted: "lap_completed", LapInvalidated: "lap_invalidated",
            LapReset: "reset", LapRetracted: "lap_retracted", HistoryUpdate: "session_history_update"}[type(event)]
    parts = [f"event={name}", f"game_t={event.game_time:.3f}"]
    for key, value in ((k, getattr(event, k)) for k in event.__slots__ if k != "game_time"):
        if key in ("lap_ms",):
            value = f"{value} ({fmt_ms(value)})"
        parts.append(f"{key}={value}")
    return " ".join(parts)


def fmt_ms(ms: int | None) -> str:
    if ms is None:
        return "-"
    minutes, rest = divmod(ms, 60000)
    return f"{minutes}:{rest // 1000:02d}.{rest % 1000:03d}"


# --- what the lap book keeps -------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class LapContext:
    """Who/where a rig is when its events arrive (from the registry and adapter)."""

    rig_name: str
    driver: str | None
    track_key: str | None
    track_name: str | None
    session_id: str | None
    tyre: dict[str, Any] | None = None


@dataclass(slots=True)
class LapRecord:
    rig_id: str
    rig_name: str
    driver: str | None
    track_key: str
    track_name: str | None
    session_id: str | None
    lap_number: int
    lap_ms: int
    sectors_ms: tuple[int, int, int] | None
    valid: bool
    out_lap: bool
    tyre: dict[str, Any] | None
    personal_best: bool
    session_best: bool
    completed_at: int            # Unix ms
    sector_ratings: tuple[str | None, str | None, str | None] = (None, None, None)

    @property
    def counted(self) -> bool:
        return self.valid and not self.out_lap

    @property
    def driver_key(self) -> str:
        return driver_key(self.driver, self.rig_id)

    def to_schema(self) -> dict[str, Any]:
        return {
            "rig_id": self.rig_id, "driver": self.driver, "track_key": self.track_key,
            "session_id": self.session_id, "lap_number": self.lap_number, "lap_ms": self.lap_ms,
            "sectors_ms": list(self.sectors_ms) if self.sectors_ms else None, "valid": self.valid,
            "out_lap": self.out_lap, "tyre": self.tyre, "personal_best": self.personal_best,
            "session_best": self.session_best, "completed_at": self.completed_at,
        }


def driver_key(driver: str | None, rig_id: str) -> str:
    """Personal bests follow the driver name; a rig without a name stands in for its driver."""
    return f"driver:{driver.casefold()}" if driver else f"rig:{rig_id}"


@dataclass(slots=True)
class Bests:
    lap: LapRecord | None = None
    sectors: list[int | None] = field(default_factory=lambda: [None, None, None])

    def consider(self, lap: LapRecord) -> None:
        if self.lap is None or lap.lap_ms < self.lap.lap_ms:
            self.lap = lap
        if lap.sectors_ms:
            for i, ms in enumerate(lap.sectors_ms):
                if ms > 0 and (self.sectors[i] is None or ms < self.sectors[i]):
                    self.sectors[i] = ms


@dataclass(slots=True)
class RigLaps:
    live: LiveLap | None = None
    track_key: str | None = None
    driver: str | None = None
    last_sectors: list[dict[str, Any] | None] | None = None
    best: dict[str, LapRecord] = field(default_factory=dict)  # track_key -> this rig's best counted lap


class LapBook:
    def __init__(self, clock=None) -> None:
        import time
        self._clock = clock or time.time
        self.rigs: dict[str, RigLaps] = {}
        self.laps: list[LapRecord] = []                       # every lap this hub session, oldest first
        self.recent: deque[LapRecord] = deque(maxlen=RECENT_LAPS_MAX)
        self._session: dict[str, Bests] = {}                  # track_key -> bests across all rigs
        self._personal: dict[tuple[str, str], Bests] = {}     # (track_key, driver_key) -> bests

    def rig(self, rig_id: str) -> RigLaps:
        return self.rigs.setdefault(rig_id, RigLaps())

    # --- input -----------------------------------------------------------------------------

    def update(self, rig_id: str, ctx: LapContext, live: LiveLap | None, events: list[LapEvent]) -> list[LapRecord]:
        """Apply one decoded packet's worth of lap information. Returns laps completed by it."""
        rig = self.rig(rig_id)
        rig.track_key, rig.driver = ctx.track_key, ctx.driver
        completed = []
        for event in events:
            lap_debug.info("rig=%s %s", rig_id, describe(event))
            if isinstance(event, LapCompleted):
                record = self._complete(rig_id, rig, ctx, event)
                if record is not None:
                    completed.append(record)
            elif isinstance(event, LapRetracted):
                self._retract(rig_id, rig, ctx, event)
            elif isinstance(event, LapReset) and event.reason == "session_changed":
                rig.last_sectors = None
        if live is not None:
            rig.live = live
        return completed

    def _complete(self, rig_id: str, rig: RigLaps, ctx: LapContext, event: LapCompleted) -> LapRecord | None:
        if ctx.track_key is None:
            log.warning("Lap %d from %s completed before its track was known; not recorded", event.lap, rig_id)
            return None
        record = LapRecord(
            rig_id=rig_id, rig_name=ctx.rig_name, driver=ctx.driver, track_key=ctx.track_key,
            track_name=ctx.track_name, session_id=ctx.session_id, lap_number=event.lap, lap_ms=event.lap_ms,
            sectors_ms=event.sectors_ms, valid=event.valid, out_lap=event.out_lap, tyre=ctx.tyre,
            personal_best=False, session_best=False, completed_at=round(self._clock() * 1000),
        )
        session = self._session.setdefault(record.track_key, Bests())
        personal = self._personal.setdefault((record.track_key, record.driver_key), Bests())
        if record.sectors_ms:
            record.sector_ratings = tuple(
                self._rate(i, ms, session, personal) if record.counted else None
                for i, ms in enumerate(record.sectors_ms))  # type: ignore[assignment]
        if record.counted:
            record.personal_best = personal.lap is None or record.lap_ms < personal.lap.lap_ms
            record.session_best = session.lap is None or record.lap_ms < session.lap.lap_ms
            session.consider(record)
            personal.consider(record)
            best = rig.best.get(record.track_key)
            if best is None or record.lap_ms < best.lap_ms:
                rig.best[record.track_key] = record
        rig.last_sectors = self._sector_list(record.sectors_ms, record.sector_ratings)
        self.laps.append(record)
        self.recent.appendleft(record)
        lap_debug.info("rig=%s recorded lap=%d time=%s valid=%s out_lap=%s counted=%s personal_best=%s "
                       "session_best=%s ratings=%s", rig_id, record.lap_number, fmt_ms(record.lap_ms), record.valid,
                       record.out_lap, record.counted, record.personal_best, record.session_best,
                       list(record.sector_ratings))
        return record

    def _retract(self, rig_id: str, rig: RigLaps, ctx: LapContext, event: LapRetracted) -> None:
        match = next((r for r in reversed(self.laps)
                      if r.rig_id == rig_id and r.lap_number == event.lap and r.session_id == ctx.session_id), None)
        if match is None:
            return
        self.laps.remove(match)
        if match in self.recent:
            self.recent.remove(match)
        self._rebuild_bests()
        lap_debug.info("rig=%s removed lap=%d time=%s; bests recomputed", rig_id, match.lap_number,
                       fmt_ms(match.lap_ms))

    def _rebuild_bests(self) -> None:
        self._session.clear()
        self._personal.clear()
        for rig in self.rigs.values():
            rig.best.clear()
        for record in self.laps:
            if not record.counted:
                continue
            self._session.setdefault(record.track_key, Bests()).consider(record)
            self._personal.setdefault((record.track_key, record.driver_key), Bests()).consider(record)
            rig = self.rig(record.rig_id)
            best = rig.best.get(record.track_key)
            if best is None or record.lap_ms < best.lap_ms:
                rig.best[record.track_key] = record

    # --- ratings ---------------------------------------------------------------------------

    @staticmethod
    def _rate(i: int, ms: int, session: Bests, personal: Bests) -> str:
        session_best = session.sectors[i]
        if session_best is None or ms <= session_best:
            return SESSION_BEST
        personal_best = personal.sectors[i]
        if personal_best is None or ms <= personal_best:
            return PERSONAL_BEST
        return NORMAL

    @staticmethod
    def _sector_list(sectors_ms, ratings) -> list[dict[str, Any] | None] | None:
        if not sectors_ms:
            return None
        return [{"ms": ms, "rating": ratings[i]} for i, ms in enumerate(sectors_ms)]

    # --- views -----------------------------------------------------------------------------

    def rig_best(self, rig_id: str, track_key: str | None) -> LapRecord | None:
        rig = self.rigs.get(rig_id)
        return rig.best.get(track_key) if rig and track_key else None

    def session_best(self, track_key: str) -> LapRecord | None:
        bests = self._session.get(track_key)
        return bests.lap if bests else None

    def live_view(self, rig_id: str) -> dict[str, Any] | None:
        """Schema LiveLap for the rig, with sectors rated against current bests."""
        rig = self.rigs.get(rig_id)
        if rig is None or rig.live is None:
            return None
        live = rig.live
        session = self._session.get(rig.track_key or "") or Bests()
        personal = self._personal.get((rig.track_key or "", driver_key(rig.driver, rig_id))) or Bests()
        sectors: list[dict[str, Any] | None] = [None, None, None]
        for i, ms in enumerate((live.sector1_ms, live.sector2_ms)):
            if ms is not None and live.sector > i:
                sectors[i] = {"ms": ms, "rating": self._rate(i, ms, session, personal)
                              if live.valid and not live.out_lap else None}
        return {
            "number": live.number,
            "distance_m": round(live.distance_m, 1),
            "current_ms": live.current_ms,
            "last_ms": live.last_ms,
            "valid": live.valid,
            "sector": max(0, min(2, live.sector)),
            "sectors": sectors,
            "last_sectors": rig.last_sectors,
        }

    def leaderboard(self, track_key: str) -> list[LapRecord]:
        """Best counted lap per driver on a track this hub session, fastest first."""
        best: dict[str, LapRecord] = {}
        for record in self.laps:
            if record.counted and record.track_key == track_key:
                current = best.get(record.driver_key)
                if current is None or record.lap_ms < current.lap_ms:
                    best[record.driver_key] = record
        return sorted(best.values(), key=lambda r: (r.lap_ms, r.completed_at))
