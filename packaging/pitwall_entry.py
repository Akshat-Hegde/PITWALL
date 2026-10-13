"""PyInstaller entry point: the product exe -> simtelemetry CLI (no arguments = run the hub)."""

import sys

from simtelemetry.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
