"""Races: each rig reports its own player's result; results on one track close together form one race.

Rulings: reports for the same track within RACE_GROUP_WINDOW_S of the first one belong to one race. The race is
due RACE_SETTLE_S after the last report, or at once when every rig still driving in a race has reported.
A rig's duplicate report (the game can resend) is ignored. Ranking is by finishing position, finishers
before DNF / DSQ / not classified.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field

from .adapter import RaceFinished

RACE_GROUP_WINDOW_S = 90.0
RACE_SETTLE_S = 8.0
_SETTLED_KEEP_S = 600.0     # remember settled reports this long, so a late resend does not start a new race


@dataclass(slots=True)
class Race:
    track_key: str
    session_type: str
    first_at: float
    finished_at: float                                   # time of the last report
    track_name: str | None = None
    results: list[tuple[str, RaceFinished]] = field(default_factory=list)

    def ranked(self) -> list[tuple[str, RaceFinished]]:
        def key(item: tuple[str, RaceFinished]) -> tuple[int, int, int]:
            r = item[1]
            return (0, 0, r.position) if r.status == "finished" else (1, -r.laps, r.position)
        return sorted(self.results, key=key)

    def rigs(self) -> set[str]:
        return {rig for rig, _ in self.results}


class RaceBook:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._open: list[Race] = []
        self._settled: dict[tuple[str, str, str], float] = {}   # (rig, track, session uid) -> when

    def add(self, rig_id: str, result: RaceFinished, now: float | None = None) -> None:
        now = self._clock() if now is None else now
        if result.track_key is None:
            return
        if result.session_uid is not None and (rig_id, result.track_key, result.session_uid) in self._settled:
            return
        if result.session_uid is not None and any(
                rig_id == rig and r.session_uid == result.session_uid and race.track_key == result.track_key
                for race in self._open for rig, r in race.results):
            return                                           # a resend while its race is still open
        race = next((r for r in self._open
                     if r.track_key == result.track_key and 0 <= now - r.first_at <= RACE_GROUP_WINDOW_S), None)
        if race is None:
            race = Race(result.track_key, result.session_type, now, now)
            self._open.append(race)
        if rig_id in race.rigs():
            return
        race.results.append((rig_id, result))
        race.finished_at = now

    def due(self, now: float, driving_race_rigs: set[str]) -> list[Race]:
        """Races to publish now (removed from the book), each with its results ranked."""
        out = []
        for race in list(self._open):
            waiting = driving_race_rigs - race.rigs()
            if now - race.finished_at >= RACE_SETTLE_S or (driving_race_rigs and not waiting):
                self._open.remove(race)
                race.results = race.ranked()
                for rig, r in race.results:
                    if r.session_uid is not None:
                        self._settled[(rig, race.track_key, r.session_uid)] = now
                out.append(race)
        self._settled = {k: t for k, t in self._settled.items() if now - t < _SETTLED_KEEP_S}
        return out
