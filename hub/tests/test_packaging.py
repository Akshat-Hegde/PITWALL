"""The installer script and boot task stay in step with the app (names, version, ports, data folder)."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from simtelemetry.config import AppConfig

PKG = Path(__file__).resolve().parents[2] / "packaging"


def _iss() -> str:
    return (PKG / "pitwall.iss").read_text(encoding="utf-8")


def test_installer_takes_every_name_from_the_build():
    iss = _iss()
    for define in ("AppName", "ExeName", "TaskName", "AppVersion"):
        assert f"#ifndef {define}" in iss, define           # build.ps1 passes /D<name>=...; no defaults baked in
    assert "{commonappdata}\{#AppName}" in iss              # cafe files outside Program Files
    assert "[UninstallDelete]" not in iss                   # uninstall never deletes the cafe's data
    build = (PKG / "build.ps1").read_text(encoding="utf-8")
    assert "/DAppName=" in build and "/DExeName=" in build and "/DTaskName=" in build


def test_installer_ports_and_setup_code():
    iss = _iss()
    net = AppConfig().network
    assert f"localport={net.udp_port}" in iss and f"localport={net.http_port}" in iss
    assert "setup-code --new" in iss                         # the one-time code is made at install
    assert "setup-code.txt" in iss                           # ...and read back to show on the last page


def test_boot_task_restarts_and_runs_without_login():
    ns = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
    root = ET.parse(PKG / "pitwall-task.xml").getroot()
    assert root.find(".//t:BootTrigger", ns) is not None
    assert root.find(".//t:RestartOnFailure/t:Count", ns).text == "999"
    assert root.find(".//t:Principal/t:UserId", ns).text == "S-1-5-18"      # SYSTEM: runs before anyone logs in
    assert root.find(".//t:ExecutionTimeLimit", ns).text == "PT0S"         # never killed for running too long
    assert "__EXE__" in (PKG / "pitwall-task.xml").read_text(encoding="utf-8")
