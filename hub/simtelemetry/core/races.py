"""Races: each rig reports its own player's result; results on one track close together form one race.

Rulings (R12): reports for the same track within RACE_GROUP_WINDOW_S of the first one belong to one race.
Participants of a track are the rigs seen in a race session on it within the last RACE_GROUP_WINDOW_S (a rig on its
results screen still counts). The race is due at once when the participants are known and every one has reported;
else, with other participants still unreported, at max(last report + RACE_SETTLE_S, first report + RACE_GROUP_WINDOW_S);
with no participants known at all (demo, tests) RACE_SETTLE_S after the last report.
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
        self._racing: dict[tuple[str, str], float] = {}         # (rig, track) -> last seen in a race session

    def note_racing(self, rig_id: str, track_key: str, now: float | None = None) -> None:
        """The rig is in a race session on this track right now (called for every packet / tick)."""
        self._racing[(rig_id, track_key)] = self._clock() if now is None else now

    def participants(self, track_key: str, now: float) -> set[str]:
        return {rig for (rig, track), t in self._racing.items()
                if track == track_key and 0 <= now - t <= RACE_GROUP_WINDOW_S}

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

    def due(self, now: float) -> list[Race]:
        """Races to publish now (removed from the book), each with its results ranked."""
        out = []
        for race in list(self._open):
            people = self.participants(race.track_key, now)
            reported = race.rigs()
            if people:
                ready = people == reported or now >= max(race.finished_at + RACE_SETTLE_S,
                                                         race.first_at + RACE_GROUP_WINDOW_S)
            else:
                ready = now - race.finished_at >= RACE_SETTLE_S
            if ready:
                self._open.remove(race)
                race.results = race.ranked()
                for rig, r in race.results:
                    if r.session_uid is not None:
                        self._settled[(rig, race.track_key, r.session_uid)] = now
                out.append(race)
        self._settled = {k: t for k, t in self._settled.items() if now - t < _SETTLED_KEEP_S}
        self._racing = {k: t for k, t in self._racing.items() if now - t <= RACE_GROUP_WINDOW_S}
        return out
