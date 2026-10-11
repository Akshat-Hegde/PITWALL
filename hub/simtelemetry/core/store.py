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
            columns = {row[1] for row in self._db.execute("PRAGMA table_info(laps)")}
            if "lap_class" not in columns:  # databases from before Pro / Open: those laps count as Open
                self._db.execute("ALTER TABLE laps ADD COLUMN lap_class TEXT")
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
                " lap_number, lap_ms, s1_ms, s2_ms, s3_ms, valid, out_lap, tyre, completed_at, lap_class)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (r.rig_id, r.rig_name, r.driver, r.driver_key, r.track_key, r.track_name, r.session_id,
                 r.lap_number, r.lap_ms, s1, s2, s3, int(r.valid), int(r.out_lap),
                 json.dumps(r.tyre) if r.tyre else None, r.completed_at, r.lap_class))
            return int(cur.lastrowid)

    def delete(self, lap_id: int) -> None:
        with self._lock, self._db:
            self._db.execute("DELETE FROM laps WHERE id = ?", (lap_id,))

    def board(self, track_key: str, since_ms: int | None, limit: int = BOARD_LIMIT,
              lap_class: str = "open") -> list[dict[str, Any]]:
        """Best counted lap per driver on a track since a time, fastest first (ties: earliest).

        lap_class "open": every lap (Pro laps count on the Open boards too); "pro": Pro laps only.
        """
        pro = " AND lap_class = 'pro'" if lap_class == "pro" else ""
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM (SELECT *, ROW_NUMBER() OVER (PARTITION BY driver_key"
                "  ORDER BY lap_ms, completed_at) AS n FROM laps"
                "  WHERE track_key = ? AND valid = 1 AND out_lap = 0 AND completed_at >= ?" + pro + ")"
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
            self._db.execute("INSERT INTO driver_sessions (rig_id, name, phone, email, started_at)"
                             " VALUES (?,?,?,?,?)", (rig_id, a.name, a.phone, a.email, a.started_at))

    def end_driver_session(self, rig_id: str, ended_at: int) -> None:
        with self._lock, self._db:
            self._db.execute("UPDATE driver_sessions SET ended_at = ? WHERE rig_id = ? AND ended_at IS NULL",
                             (ended_at, rig_id))

    def current_driver_sessions(self) -> dict[str, Assignment]:
        from .drivers import Assignment
        with self._lock:
            rows = self._db.execute("SELECT * FROM driver_sessions WHERE ended_at IS NULL ORDER BY id").fetchall()
        return {r["rig_id"]: Assignment(r["name"], r["phone"], r["email"], r["started_at"]) for r in rows}

    def driver_sessions(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self._db.execute("SELECT * FROM driver_sessions ORDER BY id").fetchall()]

    # --- outlines ---------------------------------------------------------------------------

    def save_outline(self, outline: dict[str, Any], created_at_ms: int) -> None:
        with self._lock, self._db:
            self._db.execute("INSERT OR REPLACE INTO outlines (track_key, outline, created_at) VALUES (?,?,?)",
                             (outline["track_key"], json.dumps(outline), created_at_ms))

    def outlines(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            rows = self._db.execute("SELECT track_key, outline FROM outlines").fetchall()
        return {row["track_key"]: json.loads(row["outline"]) for row in rows}
