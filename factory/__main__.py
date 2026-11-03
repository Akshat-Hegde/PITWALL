"""`python -m factory` (or `pythonw -m factory` from the "Factory" shortcut): opens the factory window."""

from __future__ import annotations

import sys


def main() -> int:
    try:
        from factory.app import main as app_main
    except ModuleNotFoundError as exc:
        if exc.name not in ("factory.app", "tkinter", "_tkinter"):
            raise
        print("The factory window isn't available in this copy yet. Update the factory and try again.")
        return 1
    return app_main() or 0


if __name__ == "__main__":
    sys.exit(main())
