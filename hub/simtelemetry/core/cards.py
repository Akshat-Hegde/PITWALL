"""Session story cards: a shareable summary of one driver's session, made when staff end it.

The hub stores the card's data (`cards` table) under a random token; the dashboard serves the card page at
/card/<token>, which draws the 1080 x 1920 image in the phone's browser (save, or share on WhatsApp). The TV
shows a QR code to that page for 30 seconds and so does the staff page. Phones must be on the cafe network
to open it (docs: "Sharing").
"""

from __future__ import annotations

import secrets
import time
from collections import Counter
from typing import TYPE_CHECKING, Any

from .laps import LapRecord, driver_key

if TYPE_CHECKING:
    from ..hub import Hub
    from .adapter import RaceFinished
    from .drivers import Assignment
    from .races import Race


def new_token() -> str:
    return secrets.token_urlsafe(9)  # 12 URL-safe characters, not guessable


def mini_ratings(best: LapRecord, session: list[LapRecord], today_best: list[int] | None) -> list[dict[str, Any]] | None:
    """The best lap's 24 mini-sectors, each rated: purple = fastest anyone did today, green = this driver's best
    of the session, yellow = slower than that."""
    if not best.minis:
        return None
    own = [min(ms) for ms in zip(*(r.minis for r in session if r.minis))]
    rated = []
    for i, ms in enumerate(best.minis):
        if today_best and ms <= today_best[i]:
            rating = "purple"
        elif ms <= own[i]:
            rating = "green"
        else:
            rating = "yellow"
        rated.append({"ms": ms, "rating": rating})
    return rated


def build_card(hub: Hub, rig_id: str, session: Assignment, ended_at: int) -> dict[str, Any] | None:
    """Card data for a session that just ended, or None if the driver set no counted lap."""
    dkey = driver_key(session.name, rig_id, session.driver_id)
    laps = [r for r in hub.laps.laps
            if r.rig_id == rig_id and r.completed_at >= session.started_at and r.driver_key == dkey]
    counted = [r for r in laps if r.counted]
    if not counted:
        return None
    track_key = Counter(r.track_key for r in counted).most_common(1)[0][0]
    on_track = [r for r in counted if r.track_key == track_key]
    best = min(on_track, key=lambda r: (r.lap_ms, r.completed_at))
    sectors = [r.sectors_ms for r in on_track if r.sectors_ms]
    theoretical = sum(min(s[i] for s in sectors) for i in range(3)) if sectors else None

    since = hub.laps.period_starts()["today"]
    board = hub.laps.board(track_key, "today", since)["entries"]
    position = next((e["rank"] for e in board if e["lap_ms"] == best.lap_ms and e["driver"] == best.driver), None)
    improvement = None
    if session.driver_id is not None:
        rows = hub.drivers.profile_details(session.driver_id, hub.config.leaderboard.day_start_hour) or {}
        row = next((r for r in rows.get("improvement", []) if r["track_key"] == track_key), None)
        if row:
            improvement = {"previous_best_ms": row["previous_best_ms"], "delta_ms": row["delta_ms"]}
    outline = hub.laps.outlines.get(track_key)
    cafe = hub.config.cafe
    return {
        "token": new_token(),
        "created_at": ended_at,
        "driver": session.name,
        "rig_name": hub.rig_label(rig_id),
        "track_key": track_key,
        "track_name": best.track_name,
        "cafe": {"name": cafe.name, "branding": dict(cafe.branding)},
        "session_minutes": max(1, round((ended_at - session.started_at) / 60000)),
        "laps": len(laps),
        "best_ms": best.lap_ms,
        "best_sectors_ms": list(best.sectors_ms) if best.sectors_ms else None,
        "best_lap_class": best.lap_class,
        "theoretical_ms": theoretical,
        "top_speed_kph": hub.session_top_speed(rig_id),
        "today_position": position,
        "today_drivers": len(board),
        "today_record_ms": board[0]["lap_ms"] if board else None,
        "improvement": improvement,
        "minis": mini_ratings(best, on_track, hub.laps.today_best_minis(track_key)),
        "outline": {"points": outline["points"], "display": outline["display"]} if outline else None,
    }


def build_race_card(hub: Hub, rig_id: str, result: RaceFinished, race: Race) -> dict[str, Any] | None:
    """Card data for one rig's race result (`kind: "race"`), stored and served like a session card."""
    ranked = [rig for rig, _ in race.ranked()]
    if rig_id not in ranked:
        return None
    rig = hub.registry.get(rig_id)
    cafe = hub.config.cafe
    gained = result.grid_position - result.position if result.grid_position else None
    return {
        "kind": "race",
        "token": new_token(),
        "created_at": round(time.time() * 1000),
        "driver": hub.drivers.lap_name(rig_id, rig.driver_name if rig else None, hub.rig_label(rig_id)),
        "rig_name": hub.rig_label(rig_id),
        "track_key": race.track_key,
        "track_name": race.track_name,
        "cafe": {"name": cafe.name, "branding": dict(cafe.branding)},
        "session_type": race.session_type,
        "position": result.position,
        "grid_position": result.grid_position,
        "positions_gained": gained,
        "laps": result.laps,
        "best_ms": result.best_lap_ms,
        "best_lap_ms": result.best_lap_ms,
        "total_time_s": result.total_time_s,
        "penalties_s": result.penalties_s,
        "status": result.status,
        "num_cars": result.num_cars,
        "cafe_rank": ranked.index(rig_id) + 1,
        "cafe_drivers": len(ranked),
    }
