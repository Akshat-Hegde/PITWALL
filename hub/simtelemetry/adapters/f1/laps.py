"""F1 lap tracking: LapData + Session History + Event packets -> game-agnostic lap events.

Every rule here rests on an assumption about real game behaviour that the spec doesn't state.
Each is listed in docs/LAP_ASSUMPTIONS.md (referenced as [A1], [A2], ...) with how to verify it
with --lap-debug.

Sources:
- Live Lap Data drives the lap in progress: lap number, distance, time, sector, validity.
- Session History (player car only, filtered in the decoder) is authoritative for completed laps:
  time, S1/S2/S3 and validity. A lap N is taken from history once LapData has moved past it and
  the history entry matches LapData's last-lap time captured at the rollover [A2, A3].
- If matching history doesn't arrive in time, the lap is completed from the LapData snapshot
  instead [A4]; history arriving later corrects it [A5].
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ...core.laps import (
    HistoryUpdate,
    LapCompleted,
    LapEvent,
    LapInvalidated,
    LapReset,
    LapRetracted,
    LapStarted,
    LiveLap,
)
from .packets import Event, LapData, LapHistory, SessionHistory

FLASHBACK_WINDOW_PACKETS = 60  # a lap-number decrease within this many LapData packets after FLBK
                               # is that flashback (counted in packets: session time rewinds) [A6]
HISTORY_WAIT_S = 3.0          # game time to wait for matching history before using LapData [A4]
HISTORY_MATCH_MS = 1          # history lap time must equal LapData's last-lap time within this [A3]
DRIVER_STATUS_OUT_LAP = 3     # m_driverStatus: 3 = out lap [A8]


@dataclass(slots=True)
class _Rollover:
    """What LapData said about lap N at the moment lap N+1 began."""

    lap: int
    game_time: float
    lap_ms: int                    # m_lastLapTimeInMS right after the rollover
    sector1_ms: int | None
    sector2_ms: int | None
    invalid: bool                  # m_currentLapInvalid on lap N's last LapData packet


@dataclass(slots=True)
class _Emitted:
    lap_ms: int
    sectors_ms: tuple[int, int, int] | None
    valid: bool
    source: str


@dataclass(slots=True)
class F1LapTracker:
    """Lap state for one rig (one source IP)."""

    session_uid: int | None = None
    current: LapData | None = None                 # latest LapData of the lap in progress
    # Laps the hub has seen in progress (lap -> started as an out lap). Only these are reported
    # as completed: older history entries predate the hub [A9].
    out_lap: dict[int, bool] = field(default_factory=dict)
    pending: dict[int, _Rollover] = field(default_factory=dict)
    emitted: dict[int, _Emitted] = field(default_factory=dict)
    history: tuple[LapHistory, ...] = ()           # last Session History laps seen (num_laps entries)
    flashback_window: int = 0                      # LapData packets left in which a lap decrease = FLBK

    # --- entry points ------------------------------------------------------------------------

    def on_packet(self, packet, session_uid: int) -> list[LapEvent]:
        events: list[LapEvent] = []
        if self.session_uid is not None and session_uid != self.session_uid:
            game_time = packet.header.session_time
            events.append(LapReset("session_changed", game_time, None,  # [A10]
                                   f"{self.session_uid:016x} -> {session_uid:016x}"))
            self._clear()
        self.session_uid = session_uid
        if isinstance(packet, LapData):
            events += self._on_lap_data(packet)
        elif isinstance(packet, SessionHistory):
            events += self._on_history(packet)
        elif isinstance(packet, Event) and packet.code == "FLBK":
            events += self._on_flashback(packet)  # [A6]
        return events

    def live(self) -> LiveLap | None:
        ld = self.current
        if ld is None:
            return None
        return LiveLap(
            number=ld.current_lap_num,
            distance_m=ld.lap_distance,
            current_ms=ld.current_lap_time_ms,
            valid=not ld.current_lap_invalid,
            sector=ld.sector,
            # Sector times count only once m_sector is past them [A12].
            sector1_ms=ld.sector1_time_ms if ld.sector >= 1 and ld.sector1_time_ms > 0 else None,
            sector2_ms=ld.sector2_time_ms if ld.sector >= 2 and ld.sector2_time_ms > 0 else None,
            last_ms=ld.last_lap_time_ms or None,
            out_lap=self.out_lap.get(ld.current_lap_num, False),
        )

    # --- Lap Data ----------------------------------------------------------------------------

    def _on_lap_data(self, ld: LapData) -> list[LapEvent]:
        events: list[LapEvent] = []
        t = ld.header.session_time
        prev = self.current
        n = ld.current_lap_num
        flashback = self.flashback_window > 0
        self.flashback_window = max(0, self.flashback_window - 1)
        if prev is None:
            self.out_lap.setdefault(n, self._is_out_lap(ld))
        elif n > prev.current_lap_num:
            if n > prev.current_lap_num + 1:
                events.append(LapReset("lap_number_jumped", t, n, f"{prev.current_lap_num} -> {n}"))
            # Lap prev.N finished: keep LapData's view of it until history confirms it [A2].
            self.pending[prev.current_lap_num] = _Rollover(
                lap=prev.current_lap_num, game_time=t, lap_ms=ld.last_lap_time_ms,
                sector1_ms=prev.sector1_time_ms or None, sector2_ms=prev.sector2_time_ms or None,
                invalid=prev.current_lap_invalid)
            self.out_lap[n] = self._is_out_lap(ld)
            events.append(LapStarted(n, t, self.out_lap[n]))
        elif n < prev.current_lap_num:
            if flashback:
                # Back across the line [A6]: lap n is in progress again; any completed lap >= n is
                # retracted when history drops it (or right away if history already has).
                events.append(LapReset("flashback", t, n, f"lap {prev.current_lap_num} -> {n}"))
                for lap in [lap for lap in self.pending if lap >= n]:
                    del self.pending[lap]
            else:
                # Restart (e.g. Time Trial "restart lap") [A7]: a new run; completed laps stay recorded.
                events.append(LapReset("lap_number_decreased", t, n, f"lap {prev.current_lap_num} -> {n}"))
                self.pending.clear()
                self.emitted.clear()
                self.history = ()
            self.out_lap[n] = self._is_out_lap(ld)
        else:
            if ld.current_lap_invalid and not prev.current_lap_invalid:
                events.append(LapInvalidated(n, t))  # [A11]
            # m_lastLapTimeInMS may settle a packet after the rollover: keep the latest value [A2].
            waiting = self.pending.get(n - 1)
            if waiting is not None and ld.last_lap_time_ms > 0:
                waiting.lap_ms = ld.last_lap_time_ms
        self.current = ld
        events += self._expire_pending(t)
        return events

    @staticmethod
    def _is_out_lap(ld: LapData) -> bool:
        return ld.driver_status == DRIVER_STATUS_OUT_LAP or ld.pit_status != 0

    def _expire_pending(self, t: float) -> list[LapEvent]:
        """No matching history in time: complete the lap from the LapData snapshot [A4]."""
        events: list[LapEvent] = []
        for lap, r in sorted(self.pending.items()):
            if t - r.game_time < HISTORY_WAIT_S:
                continue
            del self.pending[lap]
            if lap in self.emitted or r.lap_ms <= 0:
                continue
            sectors = None
            if r.sector1_ms and r.sector2_ms and r.lap_ms > r.sector1_ms + r.sector2_ms:
                sectors = (r.sector1_ms, r.sector2_ms, r.lap_ms - r.sector1_ms - r.sector2_ms)
            events.append(self._emit(lap, t, r.lap_ms, sectors, not r.invalid, "lap_data_fallback"))
        return events

    # --- Session History ---------------------------------------------------------------------

    def _on_history(self, sh: SessionHistory) -> list[LapEvent]:
        t = sh.header.session_time
        laps = sh.laps
        events: list[LapEvent] = []
        changed = tuple(i + 1 for i in range(max(len(laps), len(self.history)))
                        if i >= len(laps) or i >= len(self.history) or laps[i] != self.history[i])
        if changed:
            events.append(HistoryUpdate(t, sh.num_laps, changed))
        self.history = laps
        current_lap = self.current.current_lap_num if self.current else len(laps)
        for i, h in enumerate(laps):
            lap = i + 1
            if lap >= current_lap or h.lap_time_ms <= 0:
                continue  # in progress, or not filled in yet [A2]
            sectors = (h.sector1_time_ms, h.sector2_time_ms, h.sector3_time_ms)
            sectors = sectors if all(s > 0 for s in sectors) else None
            done = self.emitted.get(lap)
            if done is None:
                pending = self.pending.get(lap)
                if lap not in self.out_lap:
                    continue  # completed before the hub saw it: not reported [A9]
                if pending is not None and abs(pending.lap_ms - h.lap_time_ms) > HISTORY_MATCH_MS:
                    continue  # stale entry from before a restart, or not updated yet [A3]
                self.pending.pop(lap, None)
                events.append(self._emit(lap, t, h.lap_time_ms, sectors, h.lap_valid, "session_history"))
            elif (done.lap_ms, done.sectors_ms, done.valid) != (h.lap_time_ms, sectors, h.lap_valid):
                # History disagrees with what we reported (e.g. fallback numbers, or the game
                # changed validity afterwards) [A5]: replace the lap.
                events.append(LapRetracted(lap, t, f"corrected by session history (was {done.source})"))
                del self.emitted[lap]
                events.append(self._emit(lap, t, h.lap_time_ms, sectors, h.lap_valid, "session_history"))
        # Completed laps the history no longer has: undone by a flashback [A6].
        for lap in sorted(self.emitted):
            if lap > len(laps) or laps[lap - 1].lap_time_ms <= 0 or lap >= current_lap:
                del self.emitted[lap]
                events.append(LapRetracted(lap, t, "no longer in session history"))
        return events

    # --- Events ------------------------------------------------------------------------------

    def _on_flashback(self, ev: Event) -> list[LapEvent]:
        t = ev.header.session_time
        self.flashback_window = FLASHBACK_WINDOW_PACKETS
        detail = ""
        if ev.details is not None:
            detail = f"to frame {ev.details.frame_identifier} game_t={ev.details.session_time:.3f}"
        lap = self.current.current_lap_num if self.current else None
        return [LapReset("flashback", t, lap, detail)]

    # --- helpers -----------------------------------------------------------------------------

    def _emit(self, lap: int, t: float, lap_ms: int, sectors, valid: bool, source: str) -> LapCompleted:
        self.emitted[lap] = _Emitted(lap_ms, sectors, valid, source)
        return LapCompleted(lap, t, lap_ms, sectors, valid, self.out_lap.get(lap, False), source)

    def _clear(self) -> None:
        self.current = None
        self.out_lap.clear()
        self.pending.clear()
        self.emitted.clear()
        self.history = ()
        self.flashback_window = 0
