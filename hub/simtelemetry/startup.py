"""Start-up helpers: the last-start-error.txt note, and keeping the hub PC awake.

last-start-error.txt sits in the data folder when the hub could not start: a plain-English first line
(the installer's finish page shows it), then the technical details. A clean start deletes it.
"""

from __future__ import annotations

import datetime as dt
import logging
import os
import sys
from pathlib import Path

log = logging.getLogger(__name__)

START_ERROR_FILE = "last-start-error.txt"

# SetThreadExecutionState flags (winbase.h)
ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001


def write_start_error(data_dir: Path, headline: str, details: str = "") -> Path | None:
    """Write <data_dir>/last-start-error.txt. Never raises: it is called while something already went wrong."""
    path = data_dir / START_ERROR_FILE
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        path.write_text(f"{headline.strip()}\n\n{stamp}\n{details.strip()}\n", encoding="utf-8")
        return path
    except OSError:
        log.exception("Could not write %s", path)
        return None


def clear_start_error(data_dir: Path) -> None:
    try:
        (data_dir / START_ERROR_FILE).unlink(missing_ok=True)
    except OSError:
        log.warning("Could not delete %s", data_dir / START_ERROR_FILE)


def _under_test() -> bool:
    return "PYTEST_CURRENT_TEST" in os.environ


def keep_awake() -> bool:
    """Ask Windows not to sleep while the hub runs (the calling thread must stay alive). True when asked."""
    if sys.platform != "win32" or _under_test():
        return False
    try:
        import ctypes
        ok = ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED) != 0
    except (AttributeError, OSError):
        ok = False
    if ok:
        log.info("Keeping this PC awake while the hub runs")
    else:
        log.warning("Could not ask Windows to keep this PC awake")
    return ok


def allow_sleep() -> None:
    """Undo keep_awake."""
    if sys.platform != "win32" or _under_test():
        return
    try:
        import ctypes
        ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)
    except (AttributeError, OSError):
        pass
