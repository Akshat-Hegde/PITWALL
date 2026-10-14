"""Self check-in: one random code per rig (printed as a QR sticker), per-session secrets and a rate limit.

Codes live in <data_dir>/checkin.json as {rig_id: code}. A secret is handed to the phone that started a session; it
proves "this is my session" for the status and "I'm done" calls and is kept in memory only.
"""

from __future__ import annotations

import json
import logging
import secrets
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .drivers import Assignment
from .laps import driver_key

if TYPE_CHECKING:
    from ..hub import Hub

log = logging.getLogger(__name__)

CHECKIN_TAKEOVER_IDLE_S = 120.0      # a session not DRIVING for this long can be replaced by a new check-in
RATE_LIMIT = 10                      # check-in POSTs per client per minute
RATE_WINDOW_S = 60.0
ENDED_KEEP_S = 2 * 3600.0            # an ended session's card link stays available this long
CODE_BYTES = 6                       # token_urlsafe(6) is exactly 8 characters


@dataclass
class CheckinSession:
    rig_id: str
    started_at: int                  # the Assignment's started_at (Unix ms): identifies the session
    name: str
    driver_id: int | None = None
    ended_at: float | None = None    # wall clock (s) when this hub saw it end
    card_url: str | None = None


class CheckinService:
    def __init__(self, hub: Hub, clock=time.monotonic, wall=time.time) -> None:
        self._hub = hub
        self.clock = clock           # rate limit and health "now" (monotonic)
        self.wall = wall             # session age and ended-session expiry (Unix seconds)
        self.secrets: dict[str, CheckinSession] = {}
        self._posts: dict[str, deque[float]] = defaultdict(deque)
        self._codes: dict[str, str] | None = None

    # --- codes -----------------------------------------------------------------------------

    @property
    def _path(self):
        return self._hub.config.data_dir / "checkin.json"

    def _load(self) -> dict[str, str]:
        if self._codes is None:
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                self._codes = {str(k): str(v) for k, v in data.items()}
            except (OSError, ValueError, AttributeError):
                self._codes = {}
        return self._codes

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._codes, indent=2), encoding="utf-8")
            tmp.replace(self._path)
        except OSError:
            log.exception("Could not save %s", self._path)

    def codes(self) -> dict[str, str]:
        """{rig_id: code} for every known rig; new rigs get a code the first time they are seen."""
        codes = self._load()
        added = False
        for rig in self._hub.registry.all():
            if rig.ip not in codes:
                codes[rig.ip] = secrets.token_urlsafe(CODE_BYTES)
                added = True
        if added:
            self._save()
        return dict(codes)

    def regenerate(self, rig_id: str) -> str | None:
        """A new code for the rig (the old sticker stops working); None for an unknown rig."""
        if self._hub.registry.get(rig_id) is None:
            return None
        self.codes()
        code = secrets.token_urlsafe(CODE_BYTES)
        self._codes[rig_id] = code
        self._save()
        return code

    def rig_for(self, code: str) -> str | None:
        return next((rig for rig, c in self.codes().items() if secrets.compare_digest(c, code)
                     and self._hub.registry.get(rig) is not None), None)

    # --- rate limit ------------------------------------------------------------------------

    def allow(self, client: str) -> bool:
        now = self.clock()
        posts = self._posts[client]
        while posts and now - posts[0] > RATE_WINDOW_S:
            posts.popleft()
        if len(posts) >= RATE_LIMIT:
            return False
        posts.append(now)
        return True

    # --- sessions --------------------------------------------------------------------------

    def idle_s(self, rig_id: str, session: Assignment) -> float:
        """Seconds the rig has not been DRIVING, but never more than the session's age, so a session that
        staff just started is not taken over because of the pause before it."""
        age = self.wall() - session.started_at / 1000
        since = self._hub.health.seconds_since_driving(rig_id, self.clock())
        return age if since is None else min(since, age)

    def can_take_over(self, rig_id: str, session: Assignment) -> bool:
        return self.idle_s(rig_id, session) >= CHECKIN_TAKEOVER_IDLE_S

    def register(self, rig_id: str, session: Assignment) -> str:
        secret = secrets.token_urlsafe(16)
        self.secrets[secret] = CheckinSession(rig_id, session.started_at, session.name, session.driver_id)
        return secret

    def lookup(self, rig_id: str, secret: str | None) -> CheckinSession | None:
        """The check-in session for this secret on this rig, or None. Also drops expired ended sessions."""
        self._prune()
        rec = self.secrets.get(secret or "")
        return rec if rec is not None and rec.rig_id == rig_id else None

    def is_current(self, rec: CheckinSession) -> bool:
        current = self._hub.drivers.get(rec.rig_id)
        if current is not None and current.started_at == rec.started_at:
            return True
        if rec.ended_at is None:
            rec.ended_at = self.wall()
        return False

    def mark_ended(self, rig_id: str, started_at: int, card: dict[str, Any] | None) -> None:
        for rec in self.secrets.values():
            if rec.rig_id == rig_id and rec.started_at == started_at:
                rec.ended_at = self.wall()
                rec.card_url = card["url"] if card else None

    def laps(self, rec: CheckinSession) -> list:
        key = driver_key(rec.name, rec.rig_id, rec.driver_id)
        return [r for r in self._hub.laps.laps if r.rig_id == rec.rig_id and r.driver_key == key
                and r.completed_at >= rec.started_at and r.counted]

    def _prune(self) -> None:
        now = self.wall()
        for secret in [s for s, rec in self.secrets.items()
                       if rec.ended_at is not None and now - rec.ended_at > ENDED_KEEP_S]:
            del self.secrets[secret]
