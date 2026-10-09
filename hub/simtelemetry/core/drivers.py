"""Driver names assigned by staff, per rig.

Staff set the current driver's name on the /staff page (with optional phone/email, stored for
later reports but not used yet) and end the session when the customer leaves. Each assignment
is a "driver session" row in the lap database, so assignments survive hub restarts and the
history stays available.

Name used for a rig's laps, in order: the assigned name, the game's player name, the rig name.
Laps take the name that applies when they complete; changing the name later doesn't rename
earlier laps.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .store import LapStore

NAME_MAX = 32
CONTACT_MAX = 100
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PHONE = re.compile(r"^[0-9+()\-. ]{5,20}$")


class DriverError(ValueError):
    """Invalid input from the staff page; the message is shown to staff as-is."""


@dataclass(frozen=True, slots=True)
class Assignment:
    name: str
    phone: str | None
    email: str | None
    started_at: int  # Unix ms

    def to_json(self) -> dict[str, Any]:
        return {"name": self.name, "phone": self.phone, "email": self.email, "started_at": self.started_at}


def clean_name(value: Any) -> str:
    name = " ".join(str(value or "").split())  # trim, collapse whitespace, no newlines/tabs
    if not name:
        raise DriverError("Enter the driver's name.")
    if len(name) > NAME_MAX:
        raise DriverError(f"Names can be at most {NAME_MAX} characters.")
    if any(ord(c) < 32 for c in name):
        raise DriverError("The name contains characters that can't be shown.")
    return name


def clean_contact(value: Any, pattern: re.Pattern[str], what: str) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    if len(text) > CONTACT_MAX or not pattern.match(text):
        raise DriverError(f"That doesn't look like a valid {what}.")
    return text


class DriverRegistry:
    def __init__(self, store: LapStore | None = None, clock=time.time) -> None:
        self._store = store
        self._clock = clock
        self._current: dict[str, Assignment] = store.current_driver_sessions() if store is not None else {}

    def assign(self, rig_id: str, name: Any, phone: Any = None, email: Any = None) -> Assignment:
        assignment = Assignment(
            name=clean_name(name),
            phone=clean_contact(phone, _PHONE, "phone number"),
            email=clean_contact(email, _EMAIL, "email address"),
            started_at=round(self._clock() * 1000),
        )
        if self._store is not None:
            self._store.start_driver_session(rig_id, assignment)
        self._current[rig_id] = assignment
        return assignment

    def end(self, rig_id: str) -> bool:
        """End the rig's driver session; False if there was none."""
        if rig_id not in self._current:
            return False
        if self._store is not None:
            self._store.end_driver_session(rig_id, round(self._clock() * 1000))
        del self._current[rig_id]
        return True

    def get(self, rig_id: str) -> Assignment | None:
        return self._current.get(rig_id)

    def display_name(self, rig_id: str, game_name: str | None) -> str | None:
        """Name for the TV: the assigned name, else the game's player name (None if neither)."""
        assigned = self._current.get(rig_id)
        return assigned.name if assigned else game_name or None

    def lap_name(self, rig_id: str, game_name: str | None, rig_name: str) -> str:
        """Name a lap is stored under: assigned name, else game player name, else rig name."""
        return self.display_name(rig_id, game_name) or rig_name
