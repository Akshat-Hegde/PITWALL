"""The Windows TV launcher script: valid PowerShell, kiosk + autoplay flags, start-at-login shortcut."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from simtelemetry import brand

SCRIPT = Path(__file__).resolve().parents[2] / "tools" / "windows" / "tv-launcher.ps1"
pytestmark = pytest.mark.skipif(sys.platform != "win32" or shutil.which("powershell") is None,
                                reason="Windows PowerShell only")


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT), *args],
                          capture_output=True, text=True, timeout=60)


def test_script_parses():
    check = ("$errors = $null; [System.Management.Automation.Language.Parser]::ParseFile("
             f"'{SCRIPT}', [ref]$null, [ref]$errors) | Out-Null; $errors.Count")
    out = subprocess.run(["powershell", "-NoProfile", "-Command", check], capture_output=True, text=True, timeout=60)
    assert out.stdout.strip() == "0", out.stdout + out.stderr


def test_dry_run_opens_kiosk_with_autoplay():
    out = run("-DryRun", "-Url", "http://192.168.1.64:8000/portrait")
    if out.returncode == 2:
        pytest.skip("no Edge or Chrome on this PC")
    assert out.returncode == 0, out.stderr
    assert "--kiosk http://192.168.1.64:8000/portrait" in out.stdout
    assert "--autoplay-policy=no-user-gesture-required" in out.stdout
    assert "SimTelemetryTV" in out.stdout                              # its own profile folder


def test_start_on_login_dry_run():
    out = run("-DryRun", "-StartOnLogin", "-Url", "http://hub:8000/")
    assert "SHORTCUT" in out.stdout and f"{brand.PRODUCT_NAME} TV.lnk" in out.stdout and "-Url" in out.stdout
