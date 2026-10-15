"""Drivers: who is on each rig (sessions, booking timers), driver profiles and the waiting queue.

Staff run this from the /staff page:

- **Sessions.** Staff start a session on a rig for a walk-in name or a driver profile, optionally with a
  booking time ("20 minutes"); the TV shows the time left and, at 5 minutes left, the staff page offers to
  extend. Ending the session frees the rig. Sessions are rows in the lap database, so they survive restarts.
- **Profiles** are keyed by phone number, which is only stored after the driver agreed (consent checkbox).
  A profile collects the driver's visits and laps across days; staff can delete a profile and all its data.
- **Queue:** names waiting for a rig; starting a session from the queue removes the entry.

Name used for a rig's laps, in order: the session's driver, the game's player name, the rig name. Laps take
the name that applies when they complete; changing it later doesn't rename earlier laps.
"""

from __future__ import annotations

import re
import time
import unicodedata
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .store import LapStore

NAME_MAX = 16                      # what the TV fits (staff start, check-in, queue, profiles)
BOOKING_MAX_MIN = 12 * 60
EXTEND_PROMPT_MS = 5 * 60_000      # staff page offers to extend from 5 minutes left
_PHONE = re.compile(r"^\+?[0-9]{6,15}$")


class DriverError(ValueError):
    """Invalid input from the staff page; the message is shown to staff as-is."""


@dataclass(frozen=True, slots=True)
class Assignment:
    name: str
    started_at: int                  # Unix ms
    driver_id: int | None = None     # profile, if the driver has one
    ends_at: int | None = None       # booking end (Unix ms); None = no timer

    def to_json(self) -> dict[str, Any]:
        return {"name": self.name, "driver_id": self.driver_id, "started_at": self.started_at,
                "ends_at": self.ends_at}


ZWNJ, ZWJ = "\u200c", "\u200d"
# Blank-looking characters that aren't format characters: Hangul fillers, the blank Braille pattern and the
# combining grapheme joiner. A name made of them would look empty on the TV.
_BLANKS = frozenset("\u3164\u115f\u1160\uffa0\u2800\u034f")
_EMOJI_MODIFIERS = range(0x1F3FB, 0x1F400)      # skin tones


def _script(c: str) -> str | None:
    """The script of a letter or combining mark ("DEVANAGARI", "TAMIL"...), from its Unicode name; else None."""
    if unicodedata.category(c)[0] not in "LM":
        return None
    try:
        return unicodedata.name(c).split(" ", 1)[0]
    except ValueError:
        return None


def _keep_joiner(prev: str, joiner: str, nxt: str) -> bool:
    """ZWJ/ZWNJ shape Indic and other non-Latin scripts (the Marathi eyelash "rya" needs the ZWJ): keep one between two
    characters of the same non-Latin script, and ZWJ inside an emoji sequence (family, flag). Drop it elsewhere."""
    if not prev or not nxt:
        return False
    script = _script(prev)
    if script is not None and script != "LATIN" and script == _script(nxt):
        return True
    if joiner == ZWJ and unicodedata.category(nxt) == "So":
        return (unicodedata.category(prev) == "So" or prev == "\ufe0f" or ord(prev) in _EMOJI_MODIFIERS)
    return False


def _visible(c: str) -> bool:
    return unicodedata.category(c)[0] in "LNPS" and c not in _BLANKS


def clean_name(value: Any) -> str:
    # Invisible format characters (zero-width spaces, right-to-left overrides, byte-order marks; Unicode category
    # Cf) and blank-looking fillers would make two names look the same or flip the TV text: drop them. Joiners
    # that shape a non-Latin script or an emoji stay, so a Marathi or Hindi name is kept exactly as typed.
    text = unicodedata.normalize("NFC", str(value or ""))
    kept = []
    for i, c in enumerate(text):
        if c in _BLANKS:
            continue
        if unicodedata.category(c) == "Cf":
            if c in (ZWJ, ZWNJ) and _keep_joiner(text[i - 1] if i else "", c, text[i + 1:i + 2]):
                kept.append(c)
            continue
        kept.append(c)
    name = " ".join(unicodedata.normalize("NFC", "".join(kept)).split())  # trim, collapse whitespace, no newlines
    if not name:
        if str(value or "").strip():
            raise DriverError("Please type a name.")
        raise DriverError("Enter the driver's name.")
    if not any(_visible(c) for c in name):
        raise DriverError("Please type a name.")
    if len(name) > NAME_MAX:
        raise DriverError(f"Names can be at most {NAME_MAX} characters.")
    if any(ord(c) < 32 for c in name):
        raise DriverError("The name contains characters that can't be shown.")
    return name


def clean_phone(value: Any) -> str:
    """Digits only, with an optional leading +: "+44 7700-900 123" -> "+447700900123"."""
    text = str(value or "").strip()
    phone = ("+" if text.startswith("+") else "") + re.sub(r"\D", "", text)
    if not _PHONE.match(phone):
        raise DriverError("Enter a phone number of 6 to 15 digits.")
    return phone


def clean_minutes(value: Any) -> int | None:
    if value in (None, "", 0, "0"):
        return None
    try:
        minutes = int(value)
    except (TypeError, ValueError):
        raise DriverError("The session time must be a number of minutes.") from None
    if not 1 <= minutes <= BOOKING_MAX_MIN:
        raise DriverError(f"Session times are 1 to {BOOKING_MAX_MIN} minutes.")
    return minutes


class DriverRegistry:
    def __init__(self, store: LapStore | None = None, clock=time.time) -> None:
        if store is None:
            from .store import LapStore
            store = LapStore(None)  # in memory: profiles and the queue still work (tests, replays)
        self._store = store
        self._clock = clock
        self._current: dict[str, Assignment] = store.current_driver_sessions()

    def _now_ms(self) -> int:
        return round(self._clock() * 1000)

    @property
    def store(self) -> LapStore:
        return self._store

    # --- sessions --------------------------------------------------------------------------

    def assign(self, rig_id: str, name: Any = None, driver_id: Any = None, minutes: Any = None) -> Assignment:
        """Start a session on a rig: a walk-in name, or a profile (driver_id), with an optional booking time."""
        profile = None
        if driver_id not in (None, ""):
            profile = self.profile(int(driver_id))
            if profile is None:
                raise DriverError("That driver profile doesn't exist any more. Search again.")
        booked = clean_minutes(minutes)
        now = self._now_ms()
        assignment = Assignment(
            name=profile["name"] if profile else clean_name(name),
            started_at=now,
            driver_id=profile["id"] if profile else None,
            ends_at=now + booked * 60_000 if booked else None,
        )
        self._store.start_driver_session(rig_id, assignment)
        self._current[rig_id] = assignment
        return assignment

    def extend(self, rig_id: str, minutes: Any) -> Assignment:
        current = self._current.get(rig_id)
        if current is None:
            raise DriverError("No session on that rig.")
        extra = clean_minutes(minutes)
        if extra is None:
            raise DriverError("Choose how many minutes to add.")
        base = max(current.ends_at or self._now_ms(), self._now_ms())
        updated = Assignment(current.name, current.started_at, current.driver_id, base + extra * 60_000)
        self._store.set_session_end(rig_id, updated.ends_at)
        self._current[rig_id] = updated
        return updated

    def end(self, rig_id: str, expected_session: Assignment | None = None) -> bool:
        """End the rig's session; False if there was none. Given `expected_session`, end it only if it is still
        the rig's session (a new one started meanwhile is left alone)."""
        if rig_id not in self._current:
            return False
        if expected_session is not None and self._current.get(rig_id) is not expected_session:
            return False
        self._store.end_driver_session(rig_id, self._now_ms())
        self._current.pop(rig_id, None)                 # never a KeyError if it was ended meanwhile
        return True

    def move(self, old_rig_id: str, new_rig_id: str) -> bool:
        """Move the open session from one rig id to another (the rig got a new address); False if none."""
        if old_rig_id not in self._current:
            return False
        if new_rig_id in self._current:
            raise DriverError("Both rigs have a session. End one of them first.")
        self._store.move_driver_session(old_rig_id, new_rig_id)
        self._current[new_rig_id] = self._current.pop(old_rig_id)
        return True

    def get(self, rig_id: str) -> Assignment | None:
        return self._current.get(rig_id)

    def sessions(self) -> dict[str, Assignment]:
        """Every open session by rig (a copy)."""
        return dict(self._current)

    def time_left_ms(self, rig_id: str) -> int | None:
        a = self._current.get(rig_id)
        return None if a is None or a.ends_at is None else a.ends_at - self._now_ms()

    def display_name(self, rig_id: str, game_name: str | None) -> str | None:
        """Name for the TV: the session's driver, else the game's player name (None if neither)."""
        assigned = self._current.get(rig_id)
        return assigned.name if assigned else game_name or None

    def lap_name(self, rig_id: str, game_name: str | None, rig_name: str) -> str:
        """Name a lap is stored under: session driver, else game player name, else rig name."""
        return self.display_name(rig_id, game_name) or rig_name

    def driver_id(self, rig_id: str) -> int | None:
        assigned = self._current.get(rig_id)
        return assigned.driver_id if assigned else None

    # --- profiles --------------------------------------------------------------------------

    def create_profile(self, name: Any, phone: Any, consent: Any) -> dict[str, Any]:
        if consent is not True:
            raise DriverError("Ask the driver first: their phone number is only stored with their consent.")
        name, phone = clean_name(name), clean_phone(phone)
        if self._store.find_driver_by_phone(phone) is not None:
            raise DriverError("A driver with that phone number already exists. Search for it instead.")
        now = self._now_ms()
        return self._store.create_driver(name, phone, consent_at=now, created_at=now)

    def create_quick_profile(self, name: Any) -> dict[str, Any]:
        """A profile with a name only (walk-ins at events): no phone number, so nothing needs consent."""
        return self._store.create_driver(clean_name(name), None, consent_at=None, created_at=self._now_ms())

    def search(self, query: Any) -> list[dict[str, Any]]:
        """Profiles by phone (4+ digits, e.g. the last four) or by name (2+ letters)."""
        text = " ".join(str(query or "").split())
        digits = re.sub(r"\D", "", text)
        if len(digits) >= 4 and len(digits) >= len(text.replace(" ", "")) - 2:
            return self._store.search_drivers(digits)
        if len(text) >= 2 and not digits:
            return self._store.search_drivers_by_name(text)
        raise DriverError("Type 4 or more digits of the phone number, or 2 or more letters of the name.")

    def profile(self, driver_id: int) -> dict[str, Any] | None:
        return self._store.get_driver(driver_id)

    def profile_details(self, driver_id: int, day_start_hour: int = 0) -> dict[str, Any] | None:
        profile = self._store.get_driver(driver_id)
        if profile is None:
            return None
        return {**profile, "visits": self._store.driver_visits(driver_id, day_start_hour),
                "bests": self._store.driver_track_bests(driver_id),
                "improvement": self._store.driver_improvement(driver_id, day_start_hour)}

    def delete_profile(self, driver_id: int) -> dict[str, int]:
        """Delete a profile and everything stored for it (laps, sessions, queue entries)."""
        if self._store.get_driver(driver_id) is None:
            raise DriverError("That driver profile doesn't exist.")
        for rig_id in [r for r, a in self._current.items() if a.driver_id == driver_id]:
            self.end(rig_id)
        return self._store.delete_driver(driver_id)

    # --- story cards -------------------------------------------------------------------------

    def save_card(self, rig_id: str, driver_id: int | None, card: dict[str, Any]) -> None:
        self._store.save_card(rig_id, driver_id, card)

    def card(self, token: str) -> dict[str, Any] | None:
        return self._store.card(token)

    # --- queue -----------------------------------------------------------------------------

    def queue(self) -> list[dict[str, Any]]:
        return self._store.queue()

    def queue_add(self, name: Any = None, driver_id: Any = None) -> dict[str, Any]:
        if driver_id not in (None, ""):
            profile = self.profile(int(driver_id))
            if profile is None:
                raise DriverError("That driver profile doesn't exist any more.")
            return self._store.queue_add(profile["name"], profile["id"], self._now_ms())
        return self._store.queue_add(clean_name(name), None, self._now_ms())

    def queue_remove(self, entry_id: int) -> bool:
        return self._store.queue_remove(entry_id)

    def start_from_queue(self, entry_id: int, rig_id: str, minutes: Any = None) -> Assignment:
        entry = next((e for e in self.queue() if e["id"] == entry_id), None)
        if entry is None:
            raise DriverError("That queue entry is gone. Reload the page.")
        assignment = self.assign(rig_id, entry["name"], entry["driver_id"], minutes)
        self.queue_remove(entry_id)
        return assignment
