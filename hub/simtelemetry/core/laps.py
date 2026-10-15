"""Game-agnostic lap model: lap events from a game adapter -> completed laps, bests, sector ratings.

Adapters turn game packets into the events below (see adapters/f1/laps.py and
docs/LAP_ASSUMPTIONS.md); LapBook keeps everything the dashboard needs:

- completed laps, newest first;
- per track: session bests (all rigs, since the hub started) and personal bests (per driver);
- per rig: best lap on its current track, live lap with rated sectors, last lap's rated sectors.

Only laps that are valid and not out laps ("counted" laps) set bests. Sector ratings follow the
TV timing convention: purple = equal to or faster than the fastest sector on this track today
(all rigs; the same database and day boundary as the "today" board), green = equal to or faster
than this driver's own best in their current session (same rig, game session and driver),
yellow = slower. Live sectors are rated against existing bests without changing them, because
the lap may still be invalidated before the line.
"""

from __future__ import annotations

import bisect
import datetime as dt
import itertools
import json
import logging
import math
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .store import LapStore

log = logging.getLogger(__name__)
lap_debug = logging.getLogger("simtelemetry.lapdebug")  # enabled by --lap-debug

RECENT_LAPS_MAX = 20
STORY_LAPS_MAX = 400          # session-story chart: laps sent in the snapshot
STORY_WINDOW_MS = 60 * 60_000  # ...from the last hour
EVENT_LOG_MAX = 200           # lap_completed / track_outline messages kept for dashboard connections

# A lap's path (valid or not) becomes the track outline only if it covers the whole lap without gaps and had no
# flashback. Later laps refine it: each is resampled by lap distance and averaged in, up to OUTLINE_MAX_LAPS laps.
OUTLINE_START_MAX_M = 40      # first point within this distance of the line
OUTLINE_END_MARGIN_M = 80     # last point within this distance of the track length
OUTLINE_MAX_GAP_M = 120       # no bigger gap between consecutive points
OUTLINE_MIN_POINTS = 50
OUTLINE_STEP_M = 6            # outline point spacing (by lap distance)
OUTLINE_MAX_LAPS = 5          # laps averaged into a learned outline; later laps leave it alone
OUTLINE_MAX_DEVIATION_M = 40  # a lap this far from the outline anywhere (spin, cut, wrong way) isn't averaged in
MINI_SECTORS = 24             # per lap, by distance (story cards; the dashboard uses the same count)
SPEED_BINS = 200              # speed trace resolution for head to head (one value per 0.5 % of the lap)
FULL_THROTTLE = 0.98          # lap share thresholds, the same as the dashboard's
HEAVY_BRAKING = 0.6
CORNERING_G = 1.5

PRO_CLASS = "pro"             # every assist off for the whole lap (LAP_ASSUMPTIONS A16)
OPEN_CLASS = "open"           # anything else; the Open boards include Pro laps too
CLASSES = (OPEN_CLASS, PRO_CLASS)

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
    position: tuple[float, float] | None = None       # world (x, z) of the latest Motion packet
    track_length_m: float | None = None
    sector_starts_m: tuple[float, float, float] | None = None
    pro: bool | None = None                            # all assists off right now (None: unknown)
    driver_id: int | None = None                       # driver profile, if the session has one
    throttle: float | None = None                      # latest inputs, for the head-to-head lap share
    brake: float | None = None
    g_lat: float | None = None


@dataclass(slots=True)
class Trace:
    """One lap as driven: lap distance -> lap time and position, distance increasing."""

    lap: int
    d: list[float] = field(default_factory=list)
    t: list[int] = field(default_factory=list)
    x: list[float] = field(default_factory=list)
    z: list[float] = field(default_factory=list)
    # Inputs per point (None where unknown): lap share for head to head.
    thr: list[float | None] = field(default_factory=list)
    brk: list[float | None] = field(default_factory=list)
    glat: list[float | None] = field(default_factory=list)
    flashback: bool = False  # cut by a flashback: the path may jump, so it never shapes the outline

    def add(self, d: float, t: int, x: float, z: float, thr: float | None = None, brk: float | None = None,
            glat: float | None = None) -> None:
        if self.d and d <= self.d[-1]:
            return  # standing still or noise: keep distance strictly increasing
        self.d.append(d)
        self.t.append(t)
        self.x.append(x)
        self.z.append(z)
        self.thr.append(thr)
        self.brk.append(brk)
        self.glat.append(glat)

    def cut_to(self, d: float) -> None:
        """Flashback: forget everything driven after distance d."""
        self.flashback = True
        keep = bisect.bisect_right(self.d, d)
        del self.d[keep:], self.t[keep:], self.x[keep:], self.z[keep:]
        del self.thr[keep:], self.brk[keep:], self.glat[keep:]

    def time_at(self, d: float) -> float | None:
        """Lap time at a distance, interpolated; None outside the trace."""
        if len(self.d) < 2 or d < self.d[0] or d > self.d[-1]:
            return None
        i = bisect.bisect_right(self.d, d)
        if i >= len(self.d):
            return float(self.t[-1])
        d0, d1, t0, t1 = self.d[i - 1], self.d[i], self.t[i - 1], self.t[i]
        return t0 + (t1 - t0) * (d - d0) / (d1 - d0)

    def position_at(self, d: float) -> tuple[float, float]:
        """World (x, z) at a lap distance, interpolated (clamped to the ends of the trace)."""
        i = bisect.bisect_right(self.d, d)
        if i <= 0:
            return self.x[0], self.z[0]
        if i >= len(self.d):
            return self.x[-1], self.z[-1]
        d0, d1 = self.d[i - 1], self.d[i]
        f = (d - d0) / (d1 - d0)
        return self.x[i - 1] + (self.x[i] - self.x[i - 1]) * f, self.z[i - 1] + (self.z[i] - self.z[i - 1]) * f

    def complete(self, track_length: float | None) -> bool:
        if len(self.d) < OUTLINE_MIN_POINTS or self.d[0] > OUTLINE_START_MAX_M:
            return False
        if track_length and self.d[-1] < track_length - OUTLINE_END_MARGIN_M:
            return False
        return all(b - a <= OUTLINE_MAX_GAP_M for a, b in zip(self.d, self.d[1:]))


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
    trace: Trace | None = field(default=None, repr=False, compare=False)  # best laps keep theirs
    db_id: int | None = None                                               # row in the lap store
    lap_class: str = OPEN_CLASS                                            # "pro" or "open"
    driver_id: int | None = None                                           # driver profile
    minis: list[int] | None = field(default=None, repr=False)              # mini-sector times (ms), if traced
    analysis: dict[str, Any] | None = field(default=None, repr=False)     # speed trace + lap share, if traced

    @property
    def counted(self) -> bool:
        return self.valid and not self.out_lap

    @property
    def driver_key(self) -> str:
        return driver_key(self.driver, self.rig_id, self.driver_id)

    def best_schema(self) -> dict[str, Any]:
        """Schema BestLap."""
        return {"lap_ms": self.lap_ms, "sectors_ms": list(self.sectors_ms) if self.sectors_ms else None,
                "lap_number": self.lap_number, "set_at": self.completed_at}

    def to_schema(self) -> dict[str, Any]:
        return {
            "rig_id": self.rig_id, "driver": self.driver, "track_key": self.track_key,
            "session_id": self.session_id, "lap_number": self.lap_number, "lap_ms": self.lap_ms,
            "sectors_ms": list(self.sectors_ms) if self.sectors_ms else None, "valid": self.valid,
            "out_lap": self.out_lap, "tyre": self.tyre, "personal_best": self.personal_best,
            "session_best": self.session_best, "completed_at": self.completed_at,
            "lap_class": self.lap_class,
        }


def driver_key(driver: str | None, rig_id: str, driver_id: int | None = None) -> str:
    """Personal bests follow the driver profile, else the name; a rig without a name stands in for its driver."""
    if driver_id is not None:
        return f"profile:{driver_id}"
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
    driver_id: int | None = None
    session_id: str | None = None
    last_sectors: list[dict[str, Any] | None] | None = None
    best: dict[str, LapRecord] = field(default_factory=dict)  # track_key -> this rig's best counted lap
    traces: dict[int, Trace] = field(default_factory=dict)    # lap number -> trace (current + recent)
    pro_laps: set[int] = field(default_factory=set)           # laps seen with every assist off
    assisted_laps: set[int] = field(default_factory=set)      # laps seen with an assist on (or unknown)
    cut_pending: bool = False                                  # flashback: cut the trace at the next update


class LapBook:
    def __init__(self, clock=None, outline_display: dict[str, Any] | None = None, store: LapStore | None = None,
                 day_start_hour: int = 0, bundled_outlines: dict[str, dict[str, Any]] | None = None) -> None:
        import time
        self._clock = clock or time.time
        self.store = store
        self.day_start_hour = day_start_hour
        self.outline_display = outline_display or {"flip_x": False, "flip_z": False, "rotate_deg": 0}
        self.outlines: dict[str, dict[str, Any]] = {}          # track_key -> schema TrackOutline
        if store is not None:
            self.outlines.update(store.outlines())
        self.outlines.update(bundled_outlines or {})  # a bundled track file wins over a learned outline
        for outline in self.outlines.values():
            outline["display"] = dict(self.outline_display)  # the current config wins
        self.messages: deque[tuple[int, str, dict[str, Any]]] = deque(maxlen=EVENT_LOG_MAX)
        self._message_ids = itertools.count(1)
        self.board_version: dict[str, int] = {}                # track_key -> bumps when its board may change
        self.rigs: dict[str, RigLaps] = {}
        self.laps: list[LapRecord] = []                       # every lap this hub session, oldest first
        self.recent: deque[LapRecord] = deque(maxlen=RECENT_LAPS_MAX)
        self._session: dict[str, Bests] = {}                  # track_key -> bests across all rigs
        self._personal: dict[tuple[str, str], Bests] = {}     # (track_key, driver_key) -> bests
        self._lap_version = 0                                  # bumps on every recorded/removed lap
        self.analysis_version = 0                              # bumps when a head-to-head lap is kept
        self._analyses: dict[tuple[str, str, str], dict[str, Any]] = {}  # no store: (track, day, driver) -> lap
        self._sector_cache: dict[tuple, list[int | None]] = {}

    def rig(self, rig_id: str) -> RigLaps:
        return self.rigs.setdefault(rig_id, RigLaps())

    # --- input -----------------------------------------------------------------------------

    def update(self, rig_id: str, ctx: LapContext, live: LiveLap | None, events: list[LapEvent]) -> list[LapRecord]:
        """Apply one decoded packet's worth of lap information. Returns laps completed by it."""
        rig = self.rig(rig_id)
        rig.track_key, rig.driver, rig.session_id = ctx.track_key, ctx.driver, ctx.session_id
        rig.driver_id = ctx.driver_id
        completed = []
        for event in events:
            lap_debug.info("rig=%s %s", rig_id, describe(event))
            if isinstance(event, LapCompleted):
                record = self._complete(rig_id, rig, ctx, event)
                if record is not None:
                    completed.append(record)
            elif isinstance(event, LapRetracted):
                self._retract(rig_id, rig, ctx, event)
            elif isinstance(event, LapReset):
                if event.reason == "flashback":
                    rig.cut_pending = True
                else:
                    rig.traces.clear()
                    rig.cut_pending = False
                if event.reason == "session_changed":
                    rig.last_sectors = None
                    rig.live = None
        if live is not None:
            rig.live = live
            self._trace(rig, ctx, live)
            (rig.pro_laps if ctx.pro is True else rig.assisted_laps).add(live.number)
            for laps in (rig.pro_laps, rig.assisted_laps):
                for old in [n for n in laps if n < live.number - 3]:
                    laps.discard(old)
        return completed

    def _trace(self, rig: RigLaps, ctx: LapContext, live: LiveLap) -> None:
        if rig.cut_pending:
            rig.cut_pending = False
            trace = rig.traces.get(live.number)
            if trace is not None:
                trace.cut_to(live.distance_m)
        if ctx.position is None or live.distance_m < 0:
            return  # before the line: not part of any lap [A13]
        trace = rig.traces.get(live.number)
        if trace is None:
            trace = rig.traces[live.number] = Trace(live.number)
            for old in sorted(rig.traces)[:-3]:  # keep the lap in progress and a few before it
                del rig.traces[old]
        trace.add(live.distance_m, live.current_ms, ctx.position[0], ctx.position[1], ctx.throttle, ctx.brake,
                  ctx.g_lat)

    def publish(self, type_: str, body: dict[str, Any]) -> None:
        """Queue a message for every dashboard connection (lap_completed, track_outline, moment)."""
        self.messages.append((next(self._message_ids), type_, body))

    _publish = publish

    def publish_moment(self, kind: str, **body: Any) -> dict[str, Any]:
        """A broadcast moment for the TV (docs/WS_SCHEMA.md, Moment)."""
        moment = {"kind": kind, "at": round(self._clock() * 1000), **body}
        self.publish("moment", {"moment": moment})
        return moment

    def messages_after(self, message_id: int) -> list[tuple[int, str, dict[str, Any]]]:
        return [m for m in self.messages if m[0] > message_id]

    @property
    def last_message_id(self) -> int:
        return self.messages[-1][0] if self.messages else 0

    def _bump_board(self, track_key: str) -> None:
        self.board_version[track_key] = self.board_version.get(track_key, 0) + 1

    def _complete(self, rig_id: str, rig: RigLaps, ctx: LapContext, event: LapCompleted) -> LapRecord | None:
        if ctx.track_key is None:
            log.warning("Lap %d from %s completed before its track was known; not recorded", event.lap, rig_id)
            return None
        record = LapRecord(
            rig_id=rig_id, rig_name=ctx.rig_name, driver=ctx.driver, track_key=ctx.track_key,
            track_name=ctx.track_name, session_id=ctx.session_id, lap_number=event.lap, lap_ms=event.lap_ms,
            sectors_ms=event.sectors_ms, valid=event.valid, out_lap=event.out_lap, tyre=ctx.tyre,
            personal_best=False, session_best=False, completed_at=round(self._clock() * 1000),
            trace=rig.traces.get(event.lap),
            lap_class=PRO_CLASS if event.lap in rig.pro_laps and event.lap not in rig.assisted_laps else OPEN_CLASS,
            driver_id=ctx.driver_id,
        )
        record.minis = mini_sector_times(record.trace, ctx.track_length_m, record.lap_ms)
        record.analysis = lap_analysis(record.trace, ctx.track_length_m) if record.minis else None
        broken = self._records_broken(record) if record.counted else []
        session = self._session.setdefault(record.track_key, Bests())
        personal = self._personal.setdefault((record.track_key, record.driver_key), Bests())
        if record.sectors_ms:
            today = self.today_sector_bests(record.track_key)
            own = self.own_sector_bests(rig_id, record.session_id, record.driver_key, record.track_key)
            record.sector_ratings = tuple(
                self._rate(i, ms, today, own) if record.counted else None
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
        if self.store is not None:
            record.db_id = self.store.add(record)
        self.laps.append(record)
        self._lap_version += 1
        self.recent.appendleft(record)
        lap_debug.info("rig=%s recorded lap=%d time=%s valid=%s out_lap=%s counted=%s personal_best=%s "
                       "session_best=%s ratings=%s", rig_id, record.lap_number, fmt_ms(record.lap_ms), record.valid,
                       record.out_lap, record.counted, record.personal_best, record.session_best,
                       list(record.sector_ratings))
        self._publish("lap_completed", {"lap": record.to_schema()})
        if broken:
            self.publish_moment("record", rig_id=rig_id, driver=record.driver, track_key=record.track_key,
                                track_name=record.track_name, lap_ms=record.lap_ms, lap_class=record.lap_class,
                                records=broken)
        if record.counted:
            self._bump_board(record.track_key)
            if record.minis and record.analysis:
                self._keep_analysis(record)
        self._learn_outline(record, ctx)
        if rig.best.get(record.track_key) is not record:
            record.trace = None  # only a rig's best lap keeps its trace (live deltas)
        return record

    def _retract(self, rig_id: str, rig: RigLaps, ctx: LapContext, event: LapRetracted) -> None:
        match = next((r for r in reversed(self.laps)
                      if r.rig_id == rig_id and r.lap_number == event.lap and r.session_id == ctx.session_id), None)
        if match is None:
            return
        self.laps.remove(match)
        self._lap_version += 1
        if self.store is not None and match.db_id is not None:
            self.store.delete(match.db_id)
        if match in self.recent:
            self.recent.remove(match)
        self._rebuild_bests()
        self._bump_board(match.track_key)
        lap_debug.info("rig=%s removed lap=%d time=%s; bests recomputed", rig_id, match.lap_number,
                       fmt_ms(match.lap_ms))

    def forget_driver(self, driver_id: int) -> None:
        """A deleted profile: drop its laps from this hub session too (the store has deleted them)."""
        gone = [r for r in self.laps if r.driver_id == driver_id]
        for key in [k for k in self._analyses if k[2] == f"profile:{driver_id}"]:
            del self._analyses[key]
        self.analysis_version += 1
        if not gone:
            return
        for record in gone:
            self.laps.remove(record)
            if record in self.recent:
                self.recent.remove(record)
        self._lap_version += 1
        self._rebuild_bests()
        for track_key in {r.track_key for r in gone}:
            self._bump_board(track_key)

    def move_rig(self, old_rig_id: str, new_rig_id: str, since_ms: int) -> None:
        """A rig got a new address ("same rig as…"): its open session's laps move to the new rig id, here and
        in the store, so the session's card and check-in page still see them."""
        moved = [r for r in self.laps if r.rig_id == old_rig_id and r.completed_at >= since_ms]
        old_key, new_key = f"rig:{old_rig_id}", f"rig:{new_rig_id}"
        for record in moved:
            record.rig_id = new_rig_id
        for key in [k for k in self._analyses if k[2] == old_key]:
            entry = self._analyses.pop(key)
            if entry["completed_at"] >= since_ms:
                new = (key[0], key[1], new_key)
                if new not in self._analyses or entry["lap_ms"] < self._analyses[new]["lap_ms"]:
                    self._analyses[new] = {**entry, "driver_key": new_key, "rig_id": new_rig_id}
            else:
                self._analyses[key] = entry
        self.rigs.pop(old_rig_id, None)
        if self.store is not None:
            self.store.move_laps(old_rig_id, new_rig_id, since_ms)
        self._lap_version += 1
        self.analysis_version += 1
        self._rebuild_bests()
        for track_key in {r.track_key for r in moved}:
            self._bump_board(track_key)

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

    def today_best_minis(self, track_key: str) -> list[int] | None:
        """Fastest time in each mini-sector on a track today (laps this hub session saw with a full trace)."""
        since = self.period_starts()["today"] or 0
        minis = [r.minis for r in self.laps if r.counted and r.minis and r.track_key == track_key
                 and r.completed_at >= since]
        return [min(ms) for ms in zip(*minis)] if minis else None

    # --- head to head (persisted per track and day) -------------------------------------------

    def _keep_analysis(self, record: LapRecord) -> None:
        """Keep the driver's best traced lap of the day on this track for head to head."""
        day = self._today()
        entry = {"track_key": record.track_key, "track_name": record.track_name, "day": day,
                 "driver_key": record.driver_key, "driver": record.driver, "rig_id": record.rig_id,
                 "lap_ms": record.lap_ms, "lap_number": record.lap_number, "lap_class": record.lap_class,
                 "minis": record.minis, "speed": record.analysis["speed"], "share": record.analysis["share"],
                 "completed_at": record.completed_at}
        if self.store is not None:
            self.store.save_analysis(entry)
        else:
            key = (record.track_key, day, record.driver_key)
            old = self._analyses.get(key)
            if old is None or entry["lap_ms"] < old["lap_ms"]:
                self._analyses[key] = entry
        self.analysis_version += 1

    def _today(self) -> str:
        start = self.period_starts()["today"] or 0
        return dt.datetime.fromtimestamp(start / 1000).date().isoformat()

    def head_to_head(self, track_key: str | None) -> dict[str, Any] | None:
        """Schema HeadToHead for a track today: the two drivers whose best traced laps are closest."""
        if track_key is None:
            return None
        day = self._today()
        if self.store is not None:
            laps = self.store.analyses(track_key, day)
        else:
            laps = [e for (t, d, _), e in self._analyses.items() if t == track_key and d == day]
        laps = sorted(laps, key=lambda e: (e["lap_ms"], e["completed_at"]))
        if len(laps) < 2:
            return None
        pair = (laps[0], laps[1])
        for a, b in zip(laps[1:], laps[2:]):
            if b["lap_ms"] - a["lap_ms"] < pair[1]["lap_ms"] - pair[0]["lap_ms"]:
                pair = (a, b)
        side = lambda e: {k: e[k] for k in ("rig_id", "driver", "lap_ms", "lap_number", "lap_class", "minis",
                                            "speed", "share")}
        return {"track_key": track_key, "track_name": pair[0]["track_name"], "day": day,
                "a": side(pair[0]), "b": side(pair[1])}

    # --- records -----------------------------------------------------------------------------

    def record_holder(self, track_key: str, period: str, lap_class: str = OPEN_CLASS) -> dict[str, Any] | None:
        """Top entry of a board (period "today" / "week" / "all_time", class "open" / "pro"), or None."""
        since = self.period_starts()[period]
        board = self.board(track_key, period, since, lap_class, limit=1)
        return board["entries"][0] if board["entries"] else None

    def _records_broken(self, record: LapRecord) -> list[dict[str, Any]]:
        """Records this lap beats, checked before it is stored: all time first, then today; Pro, then Open."""
        classes = [PRO_CLASS, OPEN_CLASS] if record.lap_class == PRO_CLASS else [OPEN_CLASS]
        broken = []
        for period in ("all_time", "today"):
            for lap_class in classes:
                prev = self.record_holder(record.track_key, period, lap_class)
                if prev is not None and record.lap_ms < prev["lap_ms"]:
                    broken.append({"period": period, "lap_class": lap_class, "previous_ms": prev["lap_ms"],
                                   "previous_driver": prev["driver"] or prev["rig_name"],
                                   "gap_ms": record.lap_ms - prev["lap_ms"]})
        return broken

    # --- track outline -----------------------------------------------------------------------

    def _learn_outline(self, record: LapRecord, ctx: LapContext) -> None:
        """Build the outline from any complete lap path (valid or not) and refine it with the next few."""
        current = self.outlines.get(record.track_key)
        if current is not None and current.get("source") == "bundled":
            return  # a bundled track file is the curated shape
        learned = current is not None and current.get("step_m") == OUTLINE_STEP_M
        laps = int(current.get("laps", 1)) if learned and current else 0
        if laps >= OUTLINE_MAX_LAPS:
            return
        trace = record.trace
        why = None
        if trace is None or not trace.d:
            why = "no trace"
        elif trace.flashback:
            why = "flashback during the lap"
        elif not trace.complete(ctx.track_length_m):
            why = f"trace {len(trace.d)} points, {trace.d[0]:.0f}-{trace.d[-1]:.0f} m"
        if why or trace is None:
            lap_debug.info("rig=%s lap=%d not used for the track outline (%s)", record.rig_id, record.lap_number, why)
            return
        length = ctx.track_length_m or trace.d[-1]
        count = max(OUTLINE_MIN_POINTS, round(length / OUTLINE_STEP_M))
        path = [trace.position_at(k * length / count) for k in range(count)]
        if learned and current is not None and len(current["points"]) == count:
            old = current["points"]
            worst = max(math.hypot(x - ox, z - oz) for (x, z), (ox, oz) in zip(path, old))
            if worst > OUTLINE_MAX_DEVIATION_M:
                lap_debug.info("rig=%s lap=%d not used for the track outline (%.0f m off the outline)",
                               record.rig_id, record.lap_number, worst)
                return
            path = [((ox * laps + x) / (laps + 1), (oz * laps + z) / (laps + 1)) for (x, z), (ox, oz) in zip(path, old)]
        else:
            laps = 0  # first lap, or an outline from an older hub version: start again from this lap
        sector_starts = None
        if ctx.sector_starts_m:
            sector_starts = [0] + [min(count - 1, round(start * count / length)) for start in ctx.sector_starts_m[1:]]
        outline = {
            "track_key": record.track_key,
            "track_name": record.track_name,
            "points": [[round(x, 1), round(z, 1)] for x, z in path],
            "source": "laps",
            "laps": laps + 1,
            "step_m": OUTLINE_STEP_M,
            "length_m": round(length, 1),
            "sector_starts": sector_starts,
            "display": dict(self.outline_display),
        }
        self.outlines[record.track_key] = outline
        if self.store is not None:
            self.store.save_outline(outline, record.completed_at)
        self._publish("track_outline", {"outline": outline})
        lap_debug.info("rig=%s lap=%d %s the outline of %s (%d points, %d laps)", record.rig_id, record.lap_number,
                       "started" if laps == 0 else "refined", record.track_key, count, laps + 1)

    # --- comparison --------------------------------------------------------------------------

    def comparison(self, track_key: str, rig_ids: list[str]) -> dict[str, Any] | None:
        """Schema Comparison for rigs on one track: each against the fastest other rig's best lap."""
        if len(rig_ids) < 2:
            return None
        entries = []
        for rig_id in rig_ids:
            others = [(best, other) for other in rig_ids if other != rig_id
                      if (best := self.rig_best(other, track_key)) is not None]
            ref, ref_id = min(others, key=lambda pair: pair[0].lap_ms) if others else (None, None)
            mine = self.rig_best(rig_id, track_key)
            entries.append({
                "rig_id": rig_id,
                "reference_rig_id": ref_id,
                "best_gap_ms": mine.lap_ms - ref.lap_ms if mine and ref else None,
                "live_delta_ms": self._live_delta(rig_id, ref),
            })
        return {"track_key": track_key, "rigs": entries}

    def _live_delta(self, rig_id: str, ref: LapRecord | None) -> int | None:
        rig = self.rigs.get(rig_id)
        live = rig.live if rig else None
        if ref is None or ref.trace is None or live is None or not live.valid or live.out_lap:
            return None
        ref_t = ref.trace.time_at(live.distance_m)
        return None if ref_t is None else round(live.current_ms - ref_t)

    # --- ratings ---------------------------------------------------------------------------

    @staticmethod
    def _rate(i: int, ms: int, today: list[int | None], own: list[int | None]) -> str:
        if today[i] is None or ms <= today[i]:
            return SESSION_BEST       # purple: fastest on this track today
        if own[i] is None or ms <= own[i]:
            return PERSONAL_BEST      # green: this driver's best this session
        return NORMAL

    def today_sector_bests(self, track_key: str) -> list[int | None]:
        """Fastest S1/S2/S3 on a track today, all rigs (cached until a lap is added/removed or the day ends)."""
        since = self.period_starts()["today"]
        return self._sector_bests(("today", track_key, since), track_key, since)

    def own_sector_bests(self, rig_id: str, session_id: str | None, driver_key_: str, track_key: str) -> list[int | None]:
        """Fastest S1/S2/S3 of one driver in their current session (rig + game session + driver)."""
        return self._sector_bests(("own", track_key, rig_id, session_id, driver_key_), track_key, None,
                                  rig_id, session_id, driver_key_)

    def _sector_bests(self, key: tuple, track_key: str, since_ms: int | None, rig_id: str | None = None,
                      session_id: str | None = None, dkey: str | None = None) -> list[int | None]:
        key = key + (self._lap_version,)
        cached = self._sector_cache.get(key)
        if cached is not None:
            return cached
        if self.store is not None:
            result = self.store.sector_bests(track_key, since_ms, rig_id, session_id, dkey)
        else:  # no database (unit tests): this hub session's laps
            result = [None, None, None]
            for r in self.laps:
                if not (r.counted and r.sectors_ms and r.track_key == track_key):
                    continue
                if since_ms is not None and r.completed_at < since_ms:
                    continue
                if dkey is not None and (r.rig_id, r.session_id, r.driver_key) != (rig_id, session_id, dkey):
                    continue
                result = [ms if best is None or ms < best else best for ms, best in zip(r.sectors_ms, result)]
        if len(self._sector_cache) > 500:
            self._sector_cache.clear()
        self._sector_cache[key] = result
        return result

    @staticmethod
    def _sector_list(sectors_ms, ratings) -> list[dict[str, Any] | None] | None:
        if not sectors_ms:
            return None
        return [{"ms": ms, "rating": ratings[i]} for i, ms in enumerate(sectors_ms)]

    # --- views -----------------------------------------------------------------------------

    def recent_laps(self) -> list[dict[str, Any]]:
        return [r.to_schema() for r in self.recent]

    def period_starts(self) -> dict[str, int | None]:
        """Unix ms where each leaderboard period begins (local time of the hub PC)."""
        from .store import PERIODS, period_start
        now = dt.datetime.fromtimestamp(self._clock())
        starts = {}
        for period in PERIODS:
            start = period_start(period, now, self.day_start_hour)
            starts[period] = round(start.timestamp() * 1000) if start else None
        return starts

    def boards(self, track_key: str, lap_class: str = OPEN_CLASS) -> list[dict[str, Any]]:
        """Schema Leaderboard for each period ("today", "week", "all_time") of one track."""
        return [self.board(track_key, period, since, lap_class) for period, since in self.period_starts().items()]

    def board(self, track_key: str, period: str, since_ms: int | None, lap_class: str = OPEN_CLASS,
              limit: int | None = None) -> dict[str, Any]:
        if self.store is not None:
            rows = self.store.board(track_key, since_ms, lap_class=lap_class,
                                    **({"limit": limit} if limit is not None else {}))
        else:  # no database (unit tests): this hub session's laps
            rows = [{"rig_id": r.rig_id, "rig_name": r.rig_name, "driver": r.driver, "lap_ms": r.lap_ms,
                     "s1_ms": r.sectors_ms[0] if r.sectors_ms else None,
                     "s2_ms": r.sectors_ms[1] if r.sectors_ms else None,
                     "s3_ms": r.sectors_ms[2] if r.sectors_ms else None, "track_name": r.track_name,
                     "tyre": json.dumps(r.tyre) if r.tyre else None, "lap_number": r.lap_number,
                     "completed_at": r.completed_at}
                    for r in self.leaderboard(track_key, lap_class)
                    if since_ms is None or r.completed_at >= since_ms][:limit]
        leader = rows[0]["lap_ms"] if rows else 0
        entries = []
        for i, row in enumerate(rows):
            sectors = [row["s1_ms"], row["s2_ms"], row["s3_ms"]]
            entries.append({
                "rank": i + 1, "rig_id": row["rig_id"], "rig_name": row["rig_name"], "driver": row["driver"],
                "lap_ms": row["lap_ms"], "sectors_ms": sectors if all(s is not None for s in sectors) else None,
                "gap_ms": row["lap_ms"] - leader, "tyre": json.loads(row["tyre"]) if row["tyre"] else None,
                "lap_number": row["lap_number"], "set_at": row["completed_at"],
            })
        track_name = next((row["track_name"] for row in rows if row["track_name"]), None)
        board = {"track_key": track_key, "track_name": track_name, "period": period, "since": since_ms,
                 "lap_class": lap_class, "entries": entries}
        if period == "today" and entries:
            board["record_minis"] = self._record_minis(track_key, entries[0])
            board["mini_owners"] = self._mini_owners(track_key)
        return board

    def _mini_owners(self, track_key: str) -> list[str] | None:
        """Per mini-sector, the rig of the driver fastest through it today (from each driver's best traced lap)."""
        day = self._today()
        if self.store is not None:
            laps = self.store.analyses(track_key, day)
        else:
            laps = [e for (t, d, _), e in self._analyses.items() if t == track_key and d == day]
        laps = [e for e in laps if e.get("minis")]
        if not laps:
            return None
        return [min(laps, key=lambda e: e["minis"][i])["rig_id"] for i in range(len(laps[0]["minis"]))]

    def _record_minis(self, track_key: str, top: dict[str, Any]) -> list[int] | None:
        """Mini-sector times of today's record lap, if the hub traced it (the TV's record ghost and delta)."""
        day = self._today()
        if self.store is not None:
            laps = self.store.analyses(track_key, day)
        else:
            laps = [e for (t, d, _), e in self._analyses.items() if t == track_key and d == day]
        match = next((e for e in laps if e["lap_ms"] == top["lap_ms"] and e.get("rig_id") == top["rig_id"]), None)
        return list(match["minis"]) if match and match.get("minis") else None

    def session_story(self, track_key: str | None, since_ms: int | None = None) -> list[dict[str, Any]]:
        """Every lap on a track in the last hour (or since since_ms), oldest first: the TV's session story."""
        if track_key is None:
            return []
        if since_ms is None:
            since_ms = round(self._clock() * 1000) - STORY_WINDOW_MS
        if self.store is not None:
            now = round(self._clock() * 1000) + 1
            rows = [r for r in self.store.laps_between(since_ms, now) if r["track_key"] == track_key]
        else:
            rows = [{"rig_id": r.rig_id, "driver": r.driver, "lap_ms": r.lap_ms, "valid": r.valid,
                     "out_lap": r.out_lap, "lap_class": r.lap_class, "completed_at": r.completed_at}
                    for r in self.laps if r.track_key == track_key and r.completed_at >= since_ms]
        return [{"rig_id": r["rig_id"], "driver": r["driver"], "track_key": track_key, "lap_ms": r["lap_ms"],
                 "valid": bool(r["valid"]),
                 "out_lap": bool(r["out_lap"]), "lap_class": r["lap_class"], "completed_at": r["completed_at"]}
                for r in rows][-STORY_LAPS_MAX:]

    def driver_best(self, track_key: str | None, dkey: str) -> dict[str, Any] | None:
        """Schema BestLap: a driver's fastest counted lap on a track ever (lap database), or None."""
        if track_key is None:
            return None
        cache_key = ("driver_best", track_key, dkey, self._lap_version)
        if cache_key in self._sector_cache:
            return self._sector_cache[cache_key]  # type: ignore[return-value]
        best = None
        if self.store is not None:
            row = self.store.driver_best(track_key, dkey)
            if row:
                sectors = [row["s1_ms"], row["s2_ms"], row["s3_ms"]]
                best = {"lap_ms": row["lap_ms"], "sectors_ms": sectors if None not in sectors else None,
                        "lap_number": row["lap_number"], "set_at": row["completed_at"]}
        else:
            mine = [r for r in self.laps if r.counted and r.track_key == track_key and r.driver_key == dkey]
            if mine:
                best = min(mine, key=lambda r: (r.lap_ms, r.completed_at)).best_schema()
        self._sector_cache[cache_key] = best  # type: ignore[assignment]
        return best

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
        sectors: list[dict[str, Any] | None] = [None, None, None]
        rated = live.valid and not live.out_lap and rig.track_key is not None
        if rated:
            today = self.today_sector_bests(rig.track_key)
            own = self.own_sector_bests(rig_id, rig.session_id, driver_key(rig.driver, rig_id, rig.driver_id),
                                        rig.track_key)
        for i, ms in enumerate((live.sector1_ms, live.sector2_ms)):
            if ms is not None and live.sector > i:
                sectors[i] = {"ms": ms, "rating": self._rate(i, ms, today, own) if rated else None}
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

    def leaderboard(self, track_key: str, lap_class: str = OPEN_CLASS) -> list[LapRecord]:
        """Best counted lap per driver on a track this hub session, fastest first."""
        best: dict[str, LapRecord] = {}
        for record in self.laps:
            if record.counted and record.track_key == track_key and (
                    lap_class == OPEN_CLASS or record.lap_class == lap_class):
                current = best.get(record.driver_key)
                if current is None or record.lap_ms < current.lap_ms:
                    best[record.driver_key] = record
        return sorted(best.values(), key=lambda r: (r.lap_ms, r.completed_at))


def mini_sector_times(trace: Trace | None, track_length: float | None, lap_ms: int) -> list[int] | None:
    """Time in each of MINI_SECTORS equal-distance parts of a lap, from its trace; None if the trace is partial."""
    if trace is None or not track_length or not trace.complete(track_length):
        return None
    edges = [0.0]
    for k in range(1, MINI_SECTORS):
        t = trace.time_at(track_length * k / MINI_SECTORS)
        if t is None:
            return None
        edges.append(t)
    edges.append(float(lap_ms))
    times = [round(b - a) for a, b in zip(edges, edges[1:])]
    return times if all(t > 0 for t in times) else None


def lap_analysis(trace: Trace | None, track_length: float | None) -> dict[str, Any] | None:
    """Speed trace (km/h per 0.5 % of the lap) and lap share (% of samples) from a complete lap trace."""
    if trace is None or not track_length or not trace.complete(track_length):
        return None
    speed: list[float | None] = []
    for i in range(SPEED_BINS):
        d0, d1 = track_length * i / SPEED_BINS, track_length * (i + 1) / SPEED_BINS
        t0, t1 = trace.time_at(max(d0, trace.d[0])), trace.time_at(min(d1, trace.d[-1]))
        if t0 is None or t1 is None or t1 <= t0:
            speed.append(None)
            continue
        span = min(d1, trace.d[-1]) - max(d0, trace.d[0])
        speed.append(round(span / (t1 - t0) * 3600, 1) if span > 0 else None)  # m/ms -> km/h

    def share(values: list[float | None], hit) -> float | None:
        known = [v for v in values if v is not None]
        return round(100 * sum(1 for v in known if hit(v)) / len(known), 1) if known else None

    return {"speed": speed, "share": {
        "full_throttle": share(trace.thr, lambda v: v >= FULL_THROTTLE),
        "heavy_braking": share(trace.brk, lambda v: v >= HEAVY_BRAKING),
        "cornering": share(trace.glat, lambda v: abs(v) >= CORNERING_G),
    }}
