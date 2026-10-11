"""Owner analytics from the local lap database: sessions (staff-started), laps and drivers.

Everything is computed on request over a window of whole days ending today (local time, days starting at
[leaderboard] day_start_hour). Rig utilisation is session time over the cafe's opening hours
([owner] open_hour..close_hour) per rig per day.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import time
from collections import defaultdict
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from .store import LapStore

WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def _local(ms: int) -> dt.datetime:
    return dt.datetime.fromtimestamp(ms / 1000)


class Analytics:
    def __init__(self, store: LapStore, day_start_hour: int = 0, open_hour: int = 10, close_hour: int = 22,
                 clock=time.time, rig_label: Callable[[str], str] | None = None) -> None:
        self.store = store
        # Rigs are shown by name ("Rig 1"); without a hub, the name stored with their laps.
        self.rig_label = rig_label or (lambda rig_id: store.rig_names().get(rig_id) or rig_id)
        self.day_start_hour = day_start_hour
        self.open_hour = open_hour
        self.close_hour = close_hour
        self._clock = clock

    # --- window ------------------------------------------------------------------------------

    def _day_of(self, when: dt.datetime) -> dt.date:
        return (when - dt.timedelta(hours=self.day_start_hour)).date()

    def window(self, days: int) -> tuple[list[dt.date], int, int]:
        """The last `days` days (oldest first) and the window in Unix ms [start, end)."""
        now = dt.datetime.fromtimestamp(self._clock())
        today = self._day_of(now)
        dates = [today - dt.timedelta(days=i) for i in range(days - 1, -1, -1)]
        start = dt.datetime.combine(dates[0], dt.time(self.day_start_hour))
        return dates, round(start.timestamp() * 1000), round(self._clock() * 1000)

    def _sessions(self, start_ms: int, end_ms: int) -> list[dict[str, Any]]:
        rows = self.store.sessions_between(start_ms, end_ms)
        out = []
        for r in rows:
            s = max(r["started_at"], start_ms)
            e = min(r["ended_at"] or end_ms, end_ms)
            if e > s:
                out.append({**r, "s": s, "e": e})
        return out

    # --- report ------------------------------------------------------------------------------

    def report(self, days: int = 30) -> dict[str, Any]:
        days = max(1, min(366, days))
        dates, start_ms, end_ms = self.window(days)
        sessions = self._sessions(start_ms, end_ms)
        laps = self.store.laps_between(start_ms, end_ms)
        rigs = sorted({r["rig_id"] for r in sessions} | {r["rig_id"] for r in laps},
                      key=lambda rig: _natural(self.rig_label(rig)))
        open_min = max(1, (self.close_hour - self.open_hour) * 60)

        daily = {d: {"date": d.isoformat(), "weekday": WEEKDAYS[d.weekday()], "sessions": 0, "minutes": 0,
                     "laps": 0, "new": 0, "returning": 0} for d in dates}
        rig_minutes: dict[tuple[str, dt.date], float] = defaultdict(float)
        heat = [[0.0] * 24 for _ in range(7)]  # weekday x hour: rig-minutes
        for r in sessions:
            day = self._day_of(_local(r["started_at"]))
            if day in daily:
                daily[day]["sessions"] += 1
            # Split the session over clock hours for the heatmap and over days for utilisation.
            t = r["s"]
            while t < r["e"]:
                here = _local(t)
                next_hour = (here.replace(minute=0, second=0, microsecond=0) + dt.timedelta(hours=1)).timestamp() * 1000
                chunk_end = min(r["e"], round(next_hour))
                minutes = (chunk_end - t) / 60000
                heat[here.weekday()][here.hour] += minutes
                d = self._day_of(here)
                if d in daily:
                    daily[d]["minutes"] += minutes
                    rig_minutes[(r["rig_id"], d)] += minutes
                t = chunk_end

        # New vs returning: a driver is new on the day of their first session ever.
        first_seen = self.store.first_session_per_driver()
        seen_today: dict[dt.date, set[str]] = defaultdict(set)
        for r in sessions:
            who = _identity(r)
            day = self._day_of(_local(r["started_at"]))
            if day not in daily or who in seen_today[day]:
                continue
            seen_today[day].add(who)
            first = first_seen.get(who)
            new = first is not None and self._day_of(_local(first)) == day
            daily[day]["new" if new else "returning"] += 1

        tracks: dict[str, dict[str, Any]] = {}
        for lap in laps:
            day = self._day_of(_local(lap["completed_at"]))
            if day in daily:
                daily[day]["laps"] += 1
            t = tracks.setdefault(lap["track_key"], {"track_key": lap["track_key"], "track_name": lap["track_name"]
                                                     or lap["track_key"], "laps": 0, "drivers": set(), "best_ms": None})
            t["laps"] += 1
            t["drivers"].add(lap["driver_key"])
            if lap["valid"] and not lap["out_lap"] and (t["best_ms"] is None or lap["lap_ms"] < t["best_ms"]):
                t["best_ms"] = lap["lap_ms"]
        popular = sorted(({**t, "drivers": len(t["drivers"])} for t in tracks.values()),
                         key=lambda t: (-t["laps"], t["track_name"]))

        weekday_count = [sum(1 for d in dates if d.weekday() == w) for w in range(7)]
        heatmap = [[round(heat[w][h] / 60 / weekday_count[w], 2) if weekday_count[w] else 0.0 for h in range(24)]
                   for w in range(7)]
        utilisation = [{"rig_id": rig, "rig_name": self.rig_label(rig), "days": [round(100 * rig_minutes[(rig, d)] / open_min, 1) for d in dates]}
                       for rig in rigs]
        day_rows = []
        for d in dates:
            row = daily[d]
            row["hours"] = round(row.pop("minutes") / 60, 2)
            row["utilisation_pct"] = round(100 * row["hours"] * 60 / (open_min * len(rigs)), 1) if rigs else 0.0
            day_rows.append(row)
        total_hours = sum(r["hours"] for r in day_rows)
        drivers = {_identity(r) for r in sessions}
        return {
            "days": days, "from": dates[0].isoformat(), "to": dates[-1].isoformat(),
            "open_hours": [self.open_hour, self.close_hour], "rigs": [self.rig_label(r) for r in rigs],
            "summary": {
                "sessions": len(sessions),
                "hours": round(total_hours, 1),
                "avg_session_min": round(total_hours * 60 / len(sessions), 1) if sessions else None,
                "drivers": len(drivers),
                "new_drivers": sum(r["new"] for r in day_rows),
                "laps": len(laps),
                "utilisation_pct": round(100 * total_hours * 60 / (open_min * len(rigs) * days), 1) if rigs else 0.0,
            },
            "daily": day_rows,
            "heatmap": {"weekdays": list(WEEKDAYS), "rigs_in_use": heatmap},
            "utilisation": utilisation,
            "tracks": popular[:10],
            "busiest_days": sorted((r for r in day_rows if r["hours"] > 0), key=lambda r: -r["hours"])[:5],
        }

    # --- CSV -----------------------------------------------------------------------------------

    def csv(self, kind: str, days: int = 30) -> str:
        out = io.StringIO()
        w = csv.writer(out)
        if kind == "daily":
            rows = self.report(days)["daily"]
            w.writerow(["date", "weekday", "sessions", "hours", "utilisation_pct", "new_drivers",
                        "returning_drivers", "laps"])
            for r in rows:
                w.writerow([r["date"], r["weekday"], r["sessions"], r["hours"], r["utilisation_pct"], r["new"],
                            r["returning"], r["laps"]])
        elif kind == "sessions":
            _, start, end = self.window(days)
            w.writerow(["rig", "driver", "profile", "started", "ended", "minutes"])
            for r in self.store.sessions_between(start, end):
                ended = r["ended_at"]
                w.writerow([self.rig_label(r["rig_id"]), r["name"], "yes" if r["driver_id"] else "no", _iso(r["started_at"]),
                            _iso(ended) if ended else "", round(((ended or end) - r["started_at"]) / 60000, 1)])
        elif kind == "laps":
            _, start, end = self.window(days)
            w.writerow(["completed", "rig", "driver", "track", "lap_ms", "valid", "out_lap", "class"])
            for r in self.store.laps_between(start, end):
                w.writerow([_iso(r["completed_at"]), r["rig_name"], r["driver"] or "", r["track_name"] or r["track_key"],
                            r["lap_ms"], int(r["valid"]), int(r["out_lap"]), r["lap_class"] or "open"])
        else:
            raise ValueError(kind)
        return out.getvalue()


def _natural(text: str) -> list:
    """Sort key that puts "Rig 2" before "Rig 10"."""
    import re
    return [int(part) if part.isdigit() else part.casefold() for part in re.split(r"(\d+)", text)]


def _identity(session: dict[str, Any]) -> str:
    return f"profile:{session['driver_id']}" if session.get("driver_id") else f"name:{session['name'].casefold()}"


def _iso(ms: int) -> str:
    return _local(ms).isoformat(timespec="minutes")
