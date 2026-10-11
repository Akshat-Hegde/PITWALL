"""SQLite lap store: every recorded lap and every track outline, so boards survive restarts.

One file (<data_dir>/laps.db). Laps are written when they complete and deleted if the game
retracts them. Leaderboards are queries over it: the best counted lap (valid, not an out lap)
per driver on a track since a point in time ("today", "this week", all time).
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import sqlite3
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .laps import LapRecord

if TYPE_CHECKING:
    from .drivers import Assignment

log = logging.getLogger(__name__)

PERIODS = ("today", "week", "all_time")
BOARD_LIMIT = 100

_SCHEMA = """
CREATE TABLE IF NOT EXISTS laps (
    id           INTEGER PRIMARY KEY,
    rig_id       TEXT NOT NULL,
    rig_name     TEXT NOT NULL,
    driver       TEXT,
    driver_key   TEXT NOT NULL,
    track_key    TEXT NOT NULL,
    track_name   TEXT,
    session_id   TEXT,
    lap_number   INTEGER NOT NULL,
    lap_ms       INTEGER NOT NULL,
    s1_ms        INTEGER,
    s2_ms        INTEGER,
    s3_ms        INTEGER,
    valid        INTEGER NOT NULL,
    out_lap      INTEGER NOT NULL,
    tyre         TEXT,
    completed_at INTEGER NOT NULL,
    lap_class    TEXT
);
CREATE INDEX IF NOT EXISTS laps_board ON laps (track_key, completed_at);
CREATE TABLE IF NOT EXISTS driver_sessions (
    id         INTEGER PRIMARY KEY,
    rig_id     TEXT NOT NULL,
    name       TEXT NOT NULL,
    phone      TEXT,
    email      TEXT,
    started_at INTEGER NOT NULL,
    ended_at   INTEGER
);
CREATE INDEX IF NOT EXISTS driver_sessions_open ON driver_sessions (rig_id, ended_at);
CREATE TABLE IF NOT EXISTS drivers (
    id         INTEGER PRIMARY KEY,
    name       TEXT NOT NULL,
    phone      TEXT NOT NULL UNIQUE,
    consent_at INTEGER NOT NULL,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS queue (
    id        INTEGER PRIMARY KEY,
    name      TEXT NOT NULL,
    driver_id INTEGER,
    added_at  INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS cards (
    token      TEXT PRIMARY KEY,
    rig_id     TEXT NOT NULL,
    driver_id  INTEGER,
    data       TEXT NOT NULL,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS challenges (
    id         INTEGER PRIMARY KEY,
    title      TEXT NOT NULL,
    track_key  TEXT NOT NULL,
    track_name TEXT,
    lap_class  TEXT NOT NULL,
    starts_at  INTEGER NOT NULL,
    ends_at    INTEGER NOT NULL,
    prize      TEXT NOT NULL DEFAULT '',
    created_at INTEGER NOT NULL,
    announced  INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS events (
    id         INTEGER PRIMARY KEY,
    name       TEXT NOT NULL,
    company    TEXT NOT NULL,
    accent     TEXT,
    logo       TEXT,
    track_key  TEXT,
    track_name TEXT,
    best_n     INTEGER NOT NULL,
    starts_at  INTEGER NOT NULL,
    ended_at   INTEGER
);
CREATE TABLE IF NOT EXISTS teams (
    id       INTEGER PRIMARY KEY,
    event_id INTEGER NOT NULL,
    name     TEXT NOT NULL,
    logo     TEXT
);
CREATE TABLE IF NOT EXISTS team_members (
    id         INTEGER PRIMARY KEY,
    team_id    INTEGER NOT NULL,
    name       TEXT NOT NULL,
    driver_key TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS outlines (
    track_key  TEXT PRIMARY KEY,
    outline    TEXT NOT NULL,
    created_at INTEGER NOT NULL
);
"""


def period_start(period: str, now: dt.datetime, day_start_hour: int = 0) -> dt.datetime | None:
    """Local start of "today" / "this week" (Monday) for `now`; None for all time.

    The day starts at day_start_hour, so a session running past midnight stays on one day.
    """
    if period == "all_time":
        return None
    day = now.replace(hour=day_start_hour, minute=0, second=0, microsecond=0)
    if now < day:
        day -= dt.timedelta(days=1)
    if period == "today":
        return day
    if period == "week":
        return day - dt.timedelta(days=day.weekday())
    raise ValueError(f"unknown period {period!r}")


class LapStore:
    def __init__(self, path: Path | None) -> None:
        """path None: a throwaway in-memory database (replays don't touch the real boards)."""
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        # The API server may run handlers on other threads (and tests do): one connection, one lock.
        self._db = sqlite3.connect(path if path is not None else ":memory:", check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock, self._db:
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.executescript(_SCHEMA)
            # Columns added after the first release; older databases get them here.
            for table, column in (("laps", "lap_class TEXT"), ("laps", "driver_id INTEGER"),
                                  ("driver_sessions", "driver_id INTEGER"), ("driver_sessions", "ends_at INTEGER")):
                existing = {row[1] for row in self._db.execute(f"PRAGMA table_info({table})")}
                if column.split()[0] not in existing:
                    self._db.execute(f"ALTER TABLE {table} ADD COLUMN {column}")
            self._db.execute("CREATE INDEX IF NOT EXISTS laps_driver ON laps (driver_id)")
        log.info("Lap database: %s (%d laps)", path or "in memory, not saved", self.count())

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def count(self) -> int:
        with self._lock:
            return self._db.execute("SELECT COUNT(*) FROM laps").fetchone()[0]

    # --- laps -------------------------------------------------------------------------------

    def add(self, r: LapRecord) -> int:
        s1, s2, s3 = r.sectors_ms or (None, None, None)
        with self._lock, self._db:
            cur = self._db.execute(
                "INSERT INTO laps (rig_id, rig_name, driver, driver_key, track_key, track_name, session_id,"
                " lap_number, lap_ms, s1_ms, s2_ms, s3_ms, valid, out_lap, tyre, completed_at, lap_class,"
                " driver_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (r.rig_id, r.rig_name, r.driver, r.driver_key, r.track_key, r.track_name, r.session_id,
                 r.lap_number, r.lap_ms, s1, s2, s3, int(r.valid), int(r.out_lap),
                 json.dumps(r.tyre) if r.tyre else None, r.completed_at, r.lap_class, r.driver_id))
            return int(cur.lastrowid)

    def delete(self, lap_id: int) -> None:
        with self._lock, self._db:
            self._db.execute("DELETE FROM laps WHERE id = ?", (lap_id,))

    def board(self, track_key: str, since_ms: int | None, limit: int = BOARD_LIMIT,
              lap_class: str = "open", until_ms: int | None = None) -> list[dict[str, Any]]:
        """Best counted lap per driver on a track since a time, fastest first (ties: earliest).

        lap_class "open": every lap (Pro laps count on the Open boards too); "pro": Pro laps only.
        """
        pro = " AND lap_class = 'pro'" if lap_class == "pro" else ""
        until = f" AND completed_at < {int(until_ms)}" if until_ms is not None else ""
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM (SELECT *, ROW_NUMBER() OVER (PARTITION BY driver_key"
                "  ORDER BY lap_ms, completed_at) AS n FROM laps"
                "  WHERE track_key = ? AND valid = 1 AND out_lap = 0 AND completed_at >= ?" + pro + until + ")"
                " WHERE n = 1 ORDER BY lap_ms, completed_at LIMIT ?",
                (track_key, since_ms if since_ms is not None else 0, limit)).fetchall()
        return [dict(row) for row in rows]

    def sector_bests(self, track_key: str, since_ms: int | None, rig_id: str | None = None,
                     session_id: str | None = None, driver_key: str | None = None) -> list[int | None]:
        """Fastest S1/S2/S3 of counted laps on a track since a time, optionally for one driver's session."""
        sql = ("SELECT MIN(s1_ms), MIN(s2_ms), MIN(s3_ms) FROM laps"
               " WHERE track_key = ? AND valid = 1 AND out_lap = 0 AND completed_at >= ?")
        args: list = [track_key, since_ms if since_ms is not None else 0]
        if driver_key is not None:
            sql += " AND rig_id = ? AND session_id IS ? AND driver_key = ?"
            args += [rig_id, session_id, driver_key]
        with self._lock:
            row = self._db.execute(sql, args).fetchone()
        return list(row)

    def driver_best(self, track_key: str, driver_key: str) -> dict[str, Any] | None:
        """A driver's fastest counted lap on a track, ever."""
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM laps WHERE track_key = ? AND driver_key = ? AND valid = 1 AND out_lap = 0"
                " ORDER BY lap_ms, completed_at LIMIT 1", (track_key, driver_key)).fetchone()
        return dict(row) if row else None

    # --- driver sessions (names assigned on the staff page) --------------------------------

    def start_driver_session(self, rig_id: str, a: Assignment) -> None:
        with self._lock, self._db:
            self._db.execute("UPDATE driver_sessions SET ended_at = ? WHERE rig_id = ? AND ended_at IS NULL",
                             (a.started_at, rig_id))
            self._db.execute("INSERT INTO driver_sessions (rig_id, name, driver_id, started_at, ends_at)"
                             " VALUES (?,?,?,?,?)", (rig_id, a.name, a.driver_id, a.started_at, a.ends_at))

    def set_session_end(self, rig_id: str, ends_at: int | None) -> None:
        with self._lock, self._db:
            self._db.execute("UPDATE driver_sessions SET ends_at = ? WHERE rig_id = ? AND ended_at IS NULL",
                             (ends_at, rig_id))

    def end_driver_session(self, rig_id: str, ended_at: int) -> None:
        with self._lock, self._db:
            self._db.execute("UPDATE driver_sessions SET ended_at = ? WHERE rig_id = ? AND ended_at IS NULL",
                             (ended_at, rig_id))

    def current_driver_sessions(self) -> dict[str, Assignment]:
        from .drivers import Assignment
        with self._lock:
            rows = self._db.execute("SELECT * FROM driver_sessions WHERE ended_at IS NULL ORDER BY id").fetchall()
        return {r["rig_id"]: Assignment(r["name"], r["started_at"], r["driver_id"], r["ends_at"]) for r in rows}

    def driver_sessions(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self._db.execute("SELECT * FROM driver_sessions ORDER BY id").fetchall()]

    # --- driver profiles (phone numbers only with consent) ----------------------------------

    def create_driver(self, name: str, phone: str, consent_at: int, created_at: int) -> dict[str, Any]:
        with self._lock, self._db:
            cur = self._db.execute("INSERT INTO drivers (name, phone, consent_at, created_at) VALUES (?,?,?,?)",
                                   (name, phone, consent_at, created_at))
            driver_id = int(cur.lastrowid)
        return {"id": driver_id, "name": name, "phone": phone, "consent_at": consent_at, "created_at": created_at}

    def get_driver(self, driver_id: int) -> dict[str, Any] | None:
        with self._lock:
            row = self._db.execute("SELECT * FROM drivers WHERE id = ?", (driver_id,)).fetchone()
        return dict(row) if row else None

    def find_driver_by_phone(self, phone: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._db.execute("SELECT * FROM drivers WHERE phone = ?", (phone,)).fetchone()
        return dict(row) if row else None

    def search_drivers(self, digits: str, limit: int = 10) -> list[dict[str, Any]]:
        """Profiles whose phone number contains these digits (staff type the last few)."""
        with self._lock:
            rows = self._db.execute("SELECT * FROM drivers WHERE replace(phone, '+', '') LIKE ? ORDER BY name LIMIT ?",
                                    (f"%{digits}%", limit)).fetchall()
        return [dict(r) for r in rows]

    def delete_driver(self, driver_id: int) -> dict[str, int]:
        """Delete a profile with its laps, sessions and queue entries. Returns what was removed."""
        with self._lock, self._db:
            laps = self._db.execute("DELETE FROM laps WHERE driver_id = ?", (driver_id,)).rowcount
            sessions = self._db.execute("DELETE FROM driver_sessions WHERE driver_id = ?", (driver_id,)).rowcount
            self._db.execute("DELETE FROM queue WHERE driver_id = ?", (driver_id,))
            self._db.execute("DELETE FROM cards WHERE driver_id = ?", (driver_id,))
            self._db.execute("DELETE FROM drivers WHERE id = ?", (driver_id,))
        return {"laps": laps, "sessions": sessions}

    def driver_visits(self, driver_id: int, day_start_hour: int = 0) -> list[dict[str, Any]]:
        """One entry per day the driver came in (newest first): sessions, minutes on a rig, laps."""
        days: dict[str, dict[str, Any]] = {}
        with self._lock:
            sessions = self._db.execute("SELECT started_at, ended_at FROM driver_sessions WHERE driver_id = ?",
                                        (driver_id,)).fetchall()
            laps = self._db.execute("SELECT completed_at FROM laps WHERE driver_id = ?", (driver_id,)).fetchall()
        for row in sessions:
            day = _day(row["started_at"], day_start_hour)
            entry = days.setdefault(day, {"date": day, "sessions": 0, "minutes": 0, "laps": 0})
            entry["sessions"] += 1
            if row["ended_at"]:
                entry["minutes"] += round((row["ended_at"] - row["started_at"]) / 60000)
        for row in laps:
            day = _day(row["completed_at"], day_start_hour)
            days.setdefault(day, {"date": day, "sessions": 0, "minutes": 0, "laps": 0})["laps"] += 1
        return sorted(days.values(), key=lambda d: d["date"], reverse=True)

    def driver_track_bests(self, driver_id: int) -> list[dict[str, Any]]:
        """The driver's fastest counted lap per track, fastest tracks first by name."""
        with self._lock:
            rows = self._db.execute(
                "SELECT track_key, track_name, MIN(lap_ms) AS lap_ms, COUNT(*) AS laps FROM laps"
                " WHERE driver_id = ? AND valid = 1 AND out_lap = 0 GROUP BY track_key ORDER BY track_name",
                (driver_id,)).fetchall()
        return [dict(r) for r in rows]

    def driver_improvement(self, driver_id: int, day_start_hour: int = 0) -> list[dict[str, Any]]:
        """Per track: best lap on the latest visit day vs the best before that day (negative = faster)."""
        with self._lock:
            rows = self._db.execute(
                "SELECT track_key, track_name, lap_ms, completed_at FROM laps"
                " WHERE driver_id = ? AND valid = 1 AND out_lap = 0", (driver_id,)).fetchall()
        by_track: dict[str, list] = {}
        for r in rows:
            by_track.setdefault(r["track_key"], []).append(r)
        result = []
        for track_key, laps in by_track.items():
            latest_day = max(_day(r["completed_at"], day_start_hour) for r in laps)
            latest = [r["lap_ms"] for r in laps if _day(r["completed_at"], day_start_hour) == latest_day]
            before = [r["lap_ms"] for r in laps if _day(r["completed_at"], day_start_hour) < latest_day]
            if not before:
                continue
            result.append({"track_key": track_key, "track_name": laps[0]["track_name"], "visit": latest_day,
                           "best_ms": min(latest), "previous_best_ms": min(before),
                           "delta_ms": min(latest) - min(before)})
        return sorted(result, key=lambda r: r["delta_ms"])

    def tracks(self) -> list[dict[str, Any]]:
        """Every track with at least one lap, by name."""
        with self._lock:
            rows = self._db.execute("SELECT track_key, MAX(track_name) AS track_name FROM laps GROUP BY track_key"
                                    " ORDER BY track_name").fetchall()
        return [{"track_key": r["track_key"], "track_name": r["track_name"] or r["track_key"]} for r in rows]

    def best_laps_for(self, track_key: str, driver_keys: list[str], since_ms: int) -> dict[str, int]:
        """Best counted lap per driver key on a track since a time (team scores)."""
        if not driver_keys:
            return {}
        marks = ",".join("?" * len(driver_keys))
        with self._lock:
            rows = self._db.execute(
                f"SELECT driver_key, MIN(lap_ms) AS lap_ms FROM laps WHERE track_key = ? AND valid = 1"
                f" AND out_lap = 0 AND completed_at >= ? AND driver_key IN ({marks}) GROUP BY driver_key",
                (track_key, since_ms, *driver_keys)).fetchall()
        return {r["driver_key"]: r["lap_ms"] for r in rows}

    # --- owner analytics -------------------------------------------------------------------------

    def sessions_between(self, start_ms: int, end_ms: int) -> list[dict[str, Any]]:
        """Staff sessions overlapping [start, end), oldest first."""
        with self._lock:
            rows = self._db.execute(
                "SELECT rig_id, name, driver_id, started_at, ended_at FROM driver_sessions"
                " WHERE started_at < ? AND (ended_at IS NULL OR ended_at > ?) ORDER BY started_at",
                (end_ms, start_ms)).fetchall()
        return [dict(r) for r in rows]

    def laps_between(self, start_ms: int, end_ms: int) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute(
                "SELECT rig_id, rig_name, driver, driver_key, track_key, track_name, lap_ms, valid, out_lap,"
                " lap_class, completed_at FROM laps WHERE completed_at >= ? AND completed_at < ? ORDER BY completed_at",
                (start_ms, end_ms)).fetchall()
        return [dict(r) for r in rows]

    def first_session_per_driver(self) -> dict[str, int]:
        """When each driver (profile, else name) first had a session: new vs returning drivers."""
        with self._lock:
            rows = self._db.execute("SELECT name, driver_id, MIN(started_at) AS first FROM driver_sessions"
                                    " GROUP BY name, driver_id").fetchall()
        first: dict[str, int] = {}
        for r in rows:
            key = f"profile:{r['driver_id']}" if r["driver_id"] else f"name:{r['name'].casefold()}"
            first[key] = min(first.get(key, r["first"]), r["first"])
        return first

    # --- challenges ----------------------------------------------------------------------------

    def create_challenge(self, **c: Any) -> dict[str, Any]:
        with self._lock, self._db:
            cur = self._db.execute(
                "INSERT INTO challenges (title, track_key, track_name, lap_class, starts_at, ends_at, prize, created_at)"
                " VALUES (:title, :track_key, :track_name, :lap_class, :starts_at, :ends_at, :prize, :created_at)", c)
        return {"id": int(cur.lastrowid), **c, "announced": 0}

    def challenges(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self._db.execute("SELECT * FROM challenges ORDER BY starts_at, id").fetchall()]

    def delete_challenge(self, challenge_id: int) -> bool:
        with self._lock, self._db:
            return self._db.execute("DELETE FROM challenges WHERE id = ?", (challenge_id,)).rowcount > 0

    def mark_challenge_announced(self, challenge_id: int) -> None:
        with self._lock, self._db:
            self._db.execute("UPDATE challenges SET announced = 1 WHERE id = ?", (challenge_id,))

    # --- corporate events ------------------------------------------------------------------------

    def create_event(self, **e: Any) -> dict[str, Any]:
        with self._lock, self._db:
            cur = self._db.execute(
                "INSERT INTO events (name, company, accent, track_key, track_name, best_n, starts_at)"
                " VALUES (:name, :company, :accent, :track_key, :track_name, :best_n, :starts_at)", e)
        return {"id": int(cur.lastrowid), **e, "logo": None, "ended_at": None}

    def event(self, event_id: int) -> dict[str, Any] | None:
        with self._lock:
            row = self._db.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
        return dict(row) if row else None

    def active_event(self) -> dict[str, Any] | None:
        with self._lock:
            row = self._db.execute("SELECT * FROM events WHERE ended_at IS NULL ORDER BY id DESC LIMIT 1").fetchone()
        return dict(row) if row else None

    def end_event(self, event_id: int, ended_at: int) -> None:
        with self._lock, self._db:
            self._db.execute("UPDATE events SET ended_at = ? WHERE id = ? AND ended_at IS NULL", (ended_at, event_id))

    def add_team(self, event_id: int, name: str) -> dict[str, Any]:
        with self._lock, self._db:
            cur = self._db.execute("INSERT INTO teams (event_id, name) VALUES (?, ?)", (event_id, name))
        return {"id": int(cur.lastrowid), "event_id": event_id, "name": name, "logo": None}

    def team(self, team_id: int) -> dict[str, Any] | None:
        with self._lock:
            row = self._db.execute("SELECT * FROM teams WHERE id = ?", (team_id,)).fetchone()
        return dict(row) if row else None

    def teams(self, event_id: int) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self._db.execute("SELECT * FROM teams WHERE event_id = ? ORDER BY id",
                                                      (event_id,)).fetchall()]

    def remove_team(self, team_id: int) -> None:
        with self._lock, self._db:
            self._db.execute("DELETE FROM team_members WHERE team_id = ?", (team_id,))
            self._db.execute("DELETE FROM teams WHERE id = ?", (team_id,))

    def add_member(self, team_id: int, name: str, driver_key: str) -> dict[str, Any]:
        with self._lock, self._db:
            cur = self._db.execute("INSERT INTO team_members (team_id, name, driver_key) VALUES (?,?,?)",
                                   (team_id, name, driver_key))
        return {"id": int(cur.lastrowid), "team_id": team_id, "name": name, "driver_key": driver_key}

    def members(self, team_id: int) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self._db.execute("SELECT * FROM team_members WHERE team_id = ? ORDER BY id",
                                                      (team_id,)).fetchall()]

    def remove_member(self, member_id: int) -> None:
        with self._lock, self._db:
            self._db.execute("DELETE FROM team_members WHERE id = ?", (member_id,))

    def set_logo(self, kind: str, owner_id: int, name: str) -> None:
        table = "events" if kind == "event" else "teams"
        with self._lock, self._db:
            self._db.execute(f"UPDATE {table} SET logo = ? WHERE id = ?", (name, owner_id))

    # --- story cards ---------------------------------------------------------------------------

    def save_card(self, rig_id: str, driver_id: int | None, card: dict[str, Any]) -> None:
        with self._lock, self._db:
            self._db.execute("INSERT INTO cards (token, rig_id, driver_id, data, created_at) VALUES (?,?,?,?,?)",
                             (card["token"], rig_id, driver_id, json.dumps(card), card["created_at"]))

    def card(self, token: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._db.execute("SELECT data FROM cards WHERE token = ?", (token,)).fetchone()
        return json.loads(row["data"]) if row else None

    # --- waiting queue -----------------------------------------------------------------------

    def queue(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self._db.execute("SELECT * FROM queue ORDER BY added_at, id").fetchall()]

    def queue_add(self, name: str, driver_id: int | None, added_at: int) -> dict[str, Any]:
        with self._lock, self._db:
            cur = self._db.execute("INSERT INTO queue (name, driver_id, added_at) VALUES (?,?,?)",
                                   (name, driver_id, added_at))
        return {"id": int(cur.lastrowid), "name": name, "driver_id": driver_id, "added_at": added_at}

    def queue_remove(self, entry_id: int) -> bool:
        with self._lock, self._db:
            return self._db.execute("DELETE FROM queue WHERE id = ?", (entry_id,)).rowcount > 0

    # --- outlines ---------------------------------------------------------------------------

    def save_outline(self, outline: dict[str, Any], created_at_ms: int) -> None:
        with self._lock, self._db:
            self._db.execute("INSERT OR REPLACE INTO outlines (track_key, outline, created_at) VALUES (?,?,?)",
                             (outline["track_key"], json.dumps(outline), created_at_ms))

    def outlines(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            rows = self._db.execute("SELECT track_key, outline FROM outlines").fetchall()
        return {row["track_key"]: json.loads(row["outline"]) for row in rows}


def _day(ms: int, day_start_hour: int = 0) -> str:
    """Local date (YYYY-MM-DD) of a Unix ms time, with days starting at day_start_hour."""
    when = dt.datetime.fromtimestamp(ms / 1000) - dt.timedelta(hours=day_start_hour)
    return when.date().isoformat()
