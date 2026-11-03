"""Competitions: weekly challenges and corporate events with team leaderboards.

- **Challenge:** staff set a track, a class (Pro or Open), start and end dates and a prize text. The board is the
  best counted lap per driver in that window. The TV shows the challenge (attract, portrait, leaderboard
  view) and announces the winner when it ends.
- **Corporate event:** a company's session with teams. Each team has drivers (walk-in names or profiles); the
  team score is the average of its best `best_n` drivers' best laps on the event track since the event
  started. While an event runs, the TV shows the company's name, colour and logo and the team leaderboard.

Tournaments (brackets, knockouts) are not implemented; the dashboard only has a static preview screen.
"""

from __future__ import annotations

import base64
import binascii
import datetime as dt
import re
import secrets
import time
from collections.abc import Collection
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .drivers import DriverError
from .laps import CLASSES, OPEN_CLASS, driver_key

if TYPE_CHECKING:
    from .store import LapStore

TITLE_MAX = 40
PRIZE_MAX = 80
LOGO_MAX_BYTES = 512 * 1024
LOGO_TYPES = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}  # no SVG: it can carry script
_COLOUR = re.compile(r"^#[0-9a-fA-F]{6}$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def clean_text(value: Any, what: str, limit: int, required: bool = True) -> str:
    text = " ".join(str(value or "").split())
    if required and not text:
        raise DriverError(f"Enter the {what}.")
    if len(text) > limit:
        raise DriverError(f"The {what} can be at most {limit} characters.")
    return text


def day_start_ms(date: Any, day_start_hour: int) -> int:
    """'2026-10-12' -> Unix ms when that day starts (local time, at the cafe's day start hour)."""
    text = str(date or "")
    if not _DATE.match(text):
        raise DriverError("Dates look like 2026-10-12.")
    day = dt.datetime.strptime(text, "%Y-%m-%d").replace(hour=day_start_hour)
    return round(day.timestamp() * 1000)


class Competitions:
    def __init__(self, store: LapStore, data_dir: Path, day_start_hour: int = 0, clock=time.time) -> None:
        self.store = store
        self.logo_dir = data_dir / "logos"
        self.day_start_hour = day_start_hour
        self._clock = clock
        self.version = 0  # bumps on every change (the TV feed re-sends the competition state)

    def _now_ms(self) -> int:
        return round(self._clock() * 1000)

    def _changed(self) -> None:
        self.version += 1

    # --- challenges ------------------------------------------------------------------------

    def create_challenge(self, body: dict[str, Any]) -> dict[str, Any]:
        track_key = str(body.get("track_key") or "")
        track = next((t for t in self.store.tracks() if t["track_key"] == track_key), None)
        if track is None:
            raise DriverError("Choose a track that has been driven at least once.")
        lap_class = body.get("lap_class") or OPEN_CLASS
        if lap_class not in CLASSES:
            raise DriverError("The class is Pro or Open.")
        starts = day_start_ms(body.get("starts"), self.day_start_hour)
        ends = day_start_ms(body.get("ends"), self.day_start_hour) + 24 * 3600_000  # through the end date
        if ends <= starts:
            raise DriverError("The challenge must end on or after its start date.")
        challenge = self.store.create_challenge(
            title=clean_text(body.get("title"), "title", TITLE_MAX, required=False) or f"{track['track_name']} challenge",
            track_key=track_key, track_name=track["track_name"], lap_class=lap_class, starts_at=starts, ends_at=ends,
            prize=clean_text(body.get("prize"), "prize", PRIZE_MAX, required=False), created_at=self._now_ms())
        self._changed()
        return challenge

    def delete_challenge(self, challenge_id: int) -> bool:
        gone = self.store.delete_challenge(challenge_id)
        self._changed()
        return gone

    def challenges(self) -> list[dict[str, Any]]:
        return [self._with_board(c) for c in self.store.challenges()]

    def current_challenge(self, exclude: Collection[str] = ()) -> dict[str, Any] | None:
        """The running challenge that ends first, else the next one to start (for the TV, whose boards leave out
        laps from `exclude` rigs: those beyond the licensed rig count)."""
        now = self._now_ms()
        items = self.store.challenges()
        running = sorted((c for c in items if c["starts_at"] <= now < c["ends_at"]), key=lambda c: c["ends_at"])
        upcoming = sorted((c for c in items if c["starts_at"] > now), key=lambda c: c["starts_at"])
        pick = (running or upcoming or [None])[0]
        return self._with_board(pick, limit=5, exclude=exclude) if pick else None

    def _with_board(self, c: dict[str, Any], limit: int = 10, exclude: Collection[str] = ()) -> dict[str, Any]:
        rows = self.store.board(c["track_key"], c["starts_at"], limit=limit, lap_class=c["lap_class"],
                                until_ms=c["ends_at"], exclude_rigs=exclude)
        leader = rows[0]["lap_ms"] if rows else 0
        entries = [{"rank": i + 1, "driver": r["driver"] or r["rig_name"], "lap_ms": r["lap_ms"],
                    "gap_ms": r["lap_ms"] - leader} for i, r in enumerate(rows)]
        now = self._now_ms()
        state = "upcoming" if now < c["starts_at"] else "running" if now < c["ends_at"] else "ended"
        return {**c, "state": state, "entries": entries}

    def due_winners(self, exclude: Collection[str] = ()) -> list[dict[str, Any]]:
        """Challenges that have ended and whose winner hasn't been announced; marks them announced. For the TV's
        winner moment, so laps from `exclude` rigs don't count (as on the TV's challenge board)."""
        now = self._now_ms()
        due = [c for c in self.store.challenges() if c["ends_at"] <= now and not c["announced"]]
        out = []
        for c in due:
            self.store.mark_challenge_announced(c["id"])
            out.append(self._with_board(c, limit=3, exclude=exclude))
        if due:
            self._changed()
        return out

    # --- corporate events ------------------------------------------------------------------

    def create_event(self, body: dict[str, Any]) -> dict[str, Any]:
        if self.store.active_event() is not None:
            raise DriverError("An event is already running. End it first.")
        track_key = body.get("track_key") or None
        track = next((t for t in self.store.tracks() if t["track_key"] == track_key), None) if track_key else None
        if track_key and track is None:
            raise DriverError("Choose a track that has been driven at least once, or none.")
        accent = str(body.get("accent") or "").strip()
        if accent and not _COLOUR.match(accent):
            raise DriverError("The company colour looks like #0a7cff.")
        try:
            best_n = int(body.get("best_n") or 3)
        except (TypeError, ValueError):
            raise DriverError("Best N is a number of drivers.") from None
        if not 1 <= best_n <= 10:
            raise DriverError("Team scores use the best 1 to 10 drivers.")
        event = self.store.create_event(
            name=clean_text(body.get("name"), "event name", TITLE_MAX),
            company=clean_text(body.get("company"), "company name", TITLE_MAX),
            accent=accent or None, track_key=track_key, track_name=track["track_name"] if track else None,
            best_n=best_n, starts_at=self._now_ms())
        self._changed()
        return event

    def end_event(self, event_id: int) -> None:
        self.store.end_event(event_id, self._now_ms())
        self._changed()

    def add_team(self, event_id: int, name: Any) -> dict[str, Any]:
        self._event(event_id)
        team = self.store.add_team(event_id, clean_text(name, "team name", TITLE_MAX))
        self._changed()
        return team

    def remove_team(self, team_id: int) -> None:
        self.store.remove_team(team_id)
        self._changed()

    def add_member(self, team_id: int, driver_id: Any) -> dict[str, Any]:
        """Team members are driver profiles (search, or a quick name-only profile for walk-ins), so their laps
        are matched by profile, never by a typed name."""
        if self.store.team(team_id) is None:
            raise DriverError("That team doesn't exist any more.")
        if driver_id in (None, ""):
            raise DriverError("Choose a driver profile (search, or add a quick profile for a walk-in).")
        profile = self.store.get_driver(int(driver_id))
        if profile is None:
            raise DriverError("That driver profile doesn't exist any more.")
        key = driver_key(profile["name"], "", profile["id"])
        if any(m["driver_key"] == key for m in self.store.members(team_id)):
            raise DriverError(f"{profile['name']} is already in this team.")
        member = self.store.add_member(team_id, profile["name"], key)
        self._changed()
        return member

    def remove_member(self, member_id: int) -> None:
        self.store.remove_member(member_id)
        self._changed()

    def save_logo(self, kind: str, owner_id: int, data_url: Any) -> str:
        """Store an uploaded logo (a data: URL from the staff page); returns its file name."""
        m = re.match(r"^data:([\w/+.-]+);base64,(.*)$", str(data_url or ""), re.S)
        if not m or m[1] not in LOGO_TYPES:
            raise DriverError("Logos must be PNG, JPEG or WebP images.")
        try:
            raw = base64.b64decode(m[2], validate=True)
        except (binascii.Error, ValueError):
            raise DriverError("That image couldn't be read.") from None
        if len(raw) > LOGO_MAX_BYTES:
            raise DriverError("Logos can be at most 512 KB.")
        if kind == "event":
            self._event(owner_id)
        elif self.store.team(owner_id) is None:
            raise DriverError("That team doesn't exist any more.")
        self.logo_dir.mkdir(parents=True, exist_ok=True)
        name = f"{kind}-{owner_id}-{secrets.token_hex(4)}.{LOGO_TYPES[m[1]]}"
        (self.logo_dir / name).write_bytes(raw)
        self.store.set_logo(kind, owner_id, name)
        self._changed()
        return name

    def logo_path(self, name: str) -> Path | None:
        if not re.fullmatch(r"(event|team)-\d+-[0-9a-f]{8}\.(png|jpg|webp)", name):
            return None
        path = self.logo_dir / name
        return path if path.is_file() else None

    def _event(self, event_id: int) -> dict[str, Any]:
        event = self.store.event(event_id)
        if event is None:
            raise DriverError("That event doesn't exist.")
        return event

    def active_event(self, track_key: str | None = None) -> dict[str, Any] | None:
        """The running event with its team leaderboard (on its track, else the given / shown track)."""
        event = self.store.active_event()
        if event is None:
            return None
        track = event["track_key"] or track_key
        teams = []
        for team in self.store.teams(event["id"]):
            members = self.store.members(team["id"])
            bests = self.store.best_laps_for(track, [m["driver_key"] for m in members], event["starts_at"]) if track else {}
            ranked = sorted(bests.values())[: event["best_n"]]
            teams.append({
                "id": team["id"], "name": team["name"], "logo": _logo_url(team["logo"]),
                "members": [{"id": m["id"], "name": m["name"], "best_ms": bests.get(m["driver_key"])} for m in members],
                "counted": len(ranked),
                "average_ms": round(sum(ranked) / len(ranked)) if ranked else None,
            })
        # Complete teams (best_n laps) first, by average; then the rest by average.
        teams.sort(key=lambda t: (t["counted"] < event["best_n"], t["average_ms"] is None, t["average_ms"] or 0))
        for i, t in enumerate(teams):
            t["rank"] = i + 1
        return {**event, "logo": _logo_url(event["logo"]), "track_key": track, "teams": teams}


def _logo_url(name: str | None) -> str | None:
    return f"/api/logos/{name}" if name else None
