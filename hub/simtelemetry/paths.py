"""Where the program's files live.

App files (TV pages, HTML, bundled tracks) ship with the program and are replaced by updates.
Cafe files (config, laps.db, settings, branding, backups) belong to the cafe and are never touched by updates.

- From a source checkout: app files come from the repo, cafe files from the current folder (as before).
- Installed (PyInstaller, sys.frozen): app files next to the exe, cafe files in %ProgramData%\<brand.PRODUCT_NAME>.
- The brand.HOME_ENV environment variable overrides where cafe files live (tests, a second hub on one PC).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from . import brand

REPO_ROOT = Path(__file__).resolve().parents[2]


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_dir() -> Path:
    """Read-only program files: the PyInstaller bundle, or the repo root from source."""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return REPO_ROOT


def dashboard_dir() -> Path:
    """The built TV dashboard (index.html + assets)."""
    return app_dir() / "dashboard" if is_frozen() else REPO_ROOT / "dashboard" / "dist"


def home() -> Path:
    """The cafe's folder: config/, data/ and backups/ live under it."""
    override = os.environ.get(brand.HOME_ENV)
    if override:
        return Path(override)
    if is_frozen():
        return Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / brand.PRODUCT_NAME
    return Path.cwd()


def config_path() -> Path:
    return home() / "config" / "hub.toml"
