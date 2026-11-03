"""`python -m factory` (or `pythonw -m factory` from the "Factory" shortcut): opens the factory window."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _hub_on_path() -> None:
    """The hub's package `simtelemetry` comes from the repo's hub/ folder when the venv doesn't have it installed."""
    try:
        import simtelemetry  # noqa: F401
    except ModuleNotFoundError:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "hub"))


def _tell(message: str) -> None:
    """A plain message: in a message box under pythonw (the launcher has no console), else printed."""
    if sys.stdout is None and os.name == "nt":
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, message, "Factory", 0x40)    # type: ignore[attr-defined]
            return
        except Exception:
            pass
    if sys.stdout is not None:
        print(message)


def main() -> int:
    _hub_on_path()
    try:
        from factory.app import main as app_main
    except ModuleNotFoundError as exc:
        if exc.name not in ("factory.app", "tkinter", "_tkinter"):
            raise
        if exc.name == "factory.app":
            _tell("The factory window isn't available in this copy yet. Update the factory and try again.")
        else:
            _tell("This Python can't show windows (tkinter is missing). Install Python from python.org with "
                  "\"tcl/tk and IDLE\" ticked, make the .venv folder again, then start the factory again.")
        return 1
    return app_main() or 0


if __name__ == "__main__":
    sys.exit(main())
