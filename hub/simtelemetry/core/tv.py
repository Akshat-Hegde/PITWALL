"""What the TV shows, as chosen on the staff page: the page (LIVE or MULTIVIEW), the rig pinned to the LIVE
trace strip, and a staff-triggered view shown over the page (head to head, teams). Kept in data/tv.json so a
hub restart or TV reload keeps the choice.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

PAGES = ("live", "multi")
OVERLAYS = ("head_to_head", "teams")
_UNSET: Any = object()


class TvError(ValueError):
    """Bad TV setting; the message is shown to staff as-is."""


class TvControl:
    def __init__(self, path: Path | None = None, clock=time.time) -> None:
        self._path = path
        self._clock = clock
        self.page = "live"
        self.pinned_rig: str | None = None
        self.overlay: str | None = None
        self.updated_at = 0
        if path is not None and path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                self.page = data["page"] if data.get("page") in PAGES else "live"
                self.pinned_rig = data.get("pinned_rig") or None
                self.updated_at = int(data.get("updated_at") or 0)
            except (OSError, ValueError) as exc:
                log.warning("Ignoring %s: %s", path, exc)

    def to_json(self) -> dict[str, Any]:
        return {"page": self.page, "pinned_rig": self.pinned_rig, "overlay": self.overlay,
                "updated_at": self.updated_at}

    def set(self, page: Any = _UNSET, pinned_rig: Any = _UNSET, overlay: Any = _UNSET) -> dict[str, Any]:
        if page is not _UNSET:
            if page not in PAGES:
                raise TvError("Choose LIVE or MULTIVIEW.")
            self.page = page
        if pinned_rig is not _UNSET:
            self.pinned_rig = str(pinned_rig) if pinned_rig else None
        if overlay is not _UNSET:
            if overlay not in (None, "", *OVERLAYS):
                raise TvError("Unknown view.")
            self.overlay = overlay or None
        self.updated_at = round(self._clock() * 1000)
        self._save()
        return self.to_json()

    def _save(self) -> None:
        if self._path is None:
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            # The overlay is a moment's choice: it isn't restored after a restart.
            data = {"page": self.page, "pinned_rig": self.pinned_rig, "updated_at": self.updated_at}
            self._path.write_text(json.dumps(data) + "\n", encoding="utf-8")
        except OSError as exc:
            log.warning("Could not save the TV setting to %s: %s", self._path, exc)
