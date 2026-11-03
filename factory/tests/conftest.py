"""`python -m pytest factory -q` from the repo root: the repo root (for `factory`) and hub/ (for `simtelemetry`,
also when it isn't pip-installed) are importable."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "hub"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
