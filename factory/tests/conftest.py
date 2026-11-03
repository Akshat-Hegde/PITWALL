"""`python -m pytest factory -q` from the repo root: the repo root (for `factory`) and hub/ (for `simtelemetry`,
also when it isn't pip-installed) are importable.

On Windows the suite runs on the developer's own PC, so a safety net stops any test from reaching the desktop or
the system: icacls never runs (keys.py's `_run` is a fake that succeeds, unless a test sets its own), and Explorer
or a browser can never open (os.startfile and webbrowser.open fail the test instead)."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "hub"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


@pytest.fixture(autouse=True)
def _never_touch_the_desktop(monkeypatch):
    import webbrowser

    from factory import keys as K

    def no_desktop(*a, **k):
        raise AssertionError("a test tried to open Explorer or a browser window")

    monkeypatch.setattr(webbrowser, "open", no_desktop)
    monkeypatch.setattr(webbrowser, "open_new", no_desktop)
    monkeypatch.setattr(webbrowser, "open_new_tab", no_desktop)
    if hasattr(os, "startfile"):
        monkeypatch.setattr(os, "startfile", no_desktop)
    if os.name == "nt":
        # icacls must never run on the developer's PC: the key folder stays as Windows made it.
        monkeypatch.setattr(K, "_run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0))
    yield
