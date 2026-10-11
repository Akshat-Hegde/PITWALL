"""Bundled track outlines: JSON files shipped with the hub, so a track's map shows before anyone has driven it.

`simtelemetry save-outline <track>` copies the outline the hub learned from driven laps into a file here.
A bundled outline is the curated shape: the hub never replaces it with a learned one.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

BUNDLED_DIR = Path(__file__).resolve().parent.parent / "tracks"
FIELDS = ("track_key", "track_name", "points", "sector_starts", "length_m", "laps")


def file_name(track_key: str) -> str:
    """"F1:7" -> "F1-7.json"."""
    return re.sub(r"[^\w.-]+", "-", track_key).strip("-") + ".json"


def load_bundled(directory: Path = BUNDLED_DIR) -> dict[str, dict[str, Any]]:
    """track_key -> outline (source "bundled"; display is set by the hub's [map] config)."""
    outlines: dict[str, dict[str, Any]] = {}
    if not directory.is_dir():
        return outlines
    for path in sorted(directory.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data.get("track_key"), str) or len(data.get("points") or []) < 3:
                raise ValueError("needs track_key and points")
        except (OSError, ValueError) as exc:
            log.warning("Ignoring bundled track file %s: %s", path.name, exc)
            continue
        outlines[data["track_key"]] = {**data, "source": "bundled"}
    return outlines


def save_bundled(outline: dict[str, Any], directory: Path = BUNDLED_DIR) -> Path:
    """Write an outline as a bundled track file; returns its path."""
    directory.mkdir(parents=True, exist_ok=True)
    data = {k: outline[k] for k in FIELDS if outline.get(k) is not None}
    path = directory / file_name(outline["track_key"])
    path.write_text(json.dumps(data, separators=(",", ":")) + "\n", encoding="utf-8")
    return path
