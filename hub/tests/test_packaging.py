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
    assert r"{commonappdata}\{#AppName}" in iss             # cafe files outside Program Files
    assert "[UninstallDelete]" not in iss                   # uninstall never deletes the cafe's data
    build = (PKG / "build.ps1").read_text(encoding="utf-8")
    assert "/DAppName=" in build and "/DExeName=" in build and "/DTaskName=" in build


def test_installer_ports_and_setup_code():
    iss = _iss()
    net = AppConfig().network
    assert f"localport={net.udp_port}" in iss and f'#define HttpPort "{net.http_port}"' in iss
    assert "localport={#HttpPort}" in iss
    assert "setup-code --new" in iss                         # the one-time code is made at install
    assert "setup-code.txt" in iss                           # ...and read back to show on the last page


def test_boot_task_restarts_and_runs_without_login():
    ns = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
    root = ET.parse(PKG / "pitwall-task.xml").getroot()
    assert root.find(".//t:BootTrigger", ns) is not None
    rep = root.find(".//t:TimeTrigger/t:Repetition", ns)            # a hub that dies while running is started again
    assert rep is not None and rep.find("t:Interval", ns).text == "PT1M"
    assert rep.find("t:Duration", ns) is None                          # no end: repeats indefinitely
    assert root.find(".//t:Settings/t:MultipleInstancesPolicy", ns).text == "IgnoreNew"
    assert root.find(".//t:RestartOnFailure/t:Count", ns).text == "999"
    assert root.find(".//t:Principal/t:UserId", ns).text == "S-1-5-18"      # SYSTEM: runs before anyone logs in
    assert root.find(".//t:ExecutionTimeLimit", ns).text == "PT0S"         # never killed for running too long
    assert "__EXE__" in (PKG / "pitwall-task.xml").read_text(encoding="utf-8")


def test_task_xml_is_installed_and_the_setup_steps_are_called():
    """Without this [Files] line nothing writes the task XML and AfterAllFiles never runs: no task, no hub, no code."""
    iss = _iss()
    last = [ln for ln in _section("Files").splitlines() if ln.startswith("Source:")][-1]
    assert 'Source: "pitwall-task.xml"' in last and "AfterInstall: AfterAllFiles" in last
    assert "procedure AfterAllFiles" in iss


def test_task_runs_at_normal_priority():
    ns = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
    root = ET.parse(PKG / "pitwall-task.xml").getroot()
    assert root.find(".//t:Settings/t:Priority", ns).text == "5"            # normal CPU and I/O, not below normal


def _section(name: str) -> str:
    """The lines of one [Section] of the installer script."""
    return _iss().split(f"[{name}]\n", 1)[1].split("\n[", 1)[0]


def _lines(name: str, *needles: str) -> list[str]:
    return [ln for ln in _section(name).splitlines()
            if not ln.startswith(";") and all(n in ln for n in needles)]


def test_starter_config_is_shipped_without_overwriting():
    lines = _lines("Files", "hub.example.toml")
    assert len(lines) == 2
    starter = [ln for ln in lines if 'DestName: "hub.toml"' in ln]
    assert len(starter) == 1
    assert r"{commonappdata}\{#AppName}\config" in starter[0]
    assert "onlyifdoesntexist" in starter[0] and "uninsneveruninstall" in starter[0]
    reference = [ln for ln in lines if "DestName" not in ln]          # hub.example.toml itself: always the new one
    assert len(reference) == 1 and "onlyifdoesntexist" not in reference[0]
    assert r"{commonappdata}\{#AppName}\config" in reference[0] and "ignoreversion" in reference[0]


# --- Task 7: installer and packaging (K13, U8) ------------------------------------------------------------------

def test_repeat_trigger_starts_in_the_past():
    """A StartBoundary in the future (a PC with a wrong clock) would keep the restart-every-minute trigger off."""
    ns = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
    root = ET.parse(PKG / "pitwall-task.xml").getroot()
    assert root.find(".//t:TimeTrigger/t:StartBoundary", ns).text == "2000-01-01T00:00:00"


def test_old_program_files_are_removed_and_one_installer_runs_at_a_time():
    assert _lines("InstallDelete", r"{app}\_internal", "filesandordirs", "Components: hub")
    setup = _section("Setup")
    assert "SetupMutex=" in setup and r"Global\{#ExeName}SetupMutex" in setup


def test_keep_awake_task_is_ticked_and_sets_power_to_never():
    task = _lines("Tasks", 'Name: "keepawake"')
    assert len(task) == 1 and "Keep this PC awake (recommended for the hub and TV PC)" in task[0]
    assert "unchecked" not in task[0]
    iss = _iss()
    for setting in ("standby-timeout-ac 0", "hibernate-timeout-ac 0", "monitor-timeout-ac 0"):
        assert f"'/change {setting}'" in iss
    assert "WizardIsTaskSelected('keepawake')" in iss


def test_tv_only_install_has_no_hub_parts():
    assert _lines("Components", 'Name: "tvonly"', "This PC only shows the TV (the hub runs on another PC)")
    # Everything that makes a PC a hub is limited to the hub component.
    for line in _lines("Files"):
        if r"..\tools\windows" not in line and "pitwall.ico" not in line:
            assert "Components: hub" in line, line
    assert "Components: hub" in _lines("Files", "pitwall-task.xml")[0]           # no task, firewall or hub start
    assert "if IsHub then StopHub" in _iss()
    for name in ("Staff", "Owner", "Setup", "Show setup code", "Reset owner PIN", "Open backups folder",
                 "Open logs folder"):
        (line,) = _lines("Icons", f"{{#AppName}} {name}\"")
        assert "Components: hub" in line, name
    iss = _iss()
    assert "CreateInputQueryPage(wpSelectComponents" in iss and "Hub PC address or name" in iss
    assert "(PageID = HubAddrPage.ID) and not IsTvOnly" in iss


def test_tv_shortcuts_start_the_launcher_hidden_with_the_right_hub():
    tv = _lines("Icons", "{#AppName} TV\"")
    assert len(tv) == 3                                                      # Start menu, desktop, sign-in
    for line in tv:
        assert "powershell.exe" in line and "{code:TvLauncherParams}" in line and "runminimized" in line
    iss = _iss()
    params = iss.split("function TvLauncherParams", 1)[1].split("end;", 1)[0]
    assert "-WindowStyle Hidden" in params and "tv-launcher.ps1" in params and "-Url" in params
    assert "'http://localhost:{#HttpPort}/'" in iss and "HubHostPort(HubAddrPage.Values[0])" in iss


def test_admin_shortcuts_run_elevated_with_an_explanation():
    for name, command in (("Show setup code", "setup-code"), ("Reset owner PIN", "setup-code --reset")):
        (line,) = _lines("Icons", f"{{#AppName}} {name}\"")
        assert 'Filename: "{cmd}"' in line and '"/k ""echo ' in line
        assert f'""{{app}}\\{{#ExeName}}.exe"" {command}"""' in line
        assert f"RunAsAdministrator('{{autoprograms}}\\{{#AppName}} {name}.lnk')" in line
    assert "Lnk[22] := Chr(Ord(Lnk[22]) or $20)" in _iss()                    # the shell link RunAsUser flag
    for which in ("backups", "logs"):
        (line,) = _lines("Icons", f"Open {which} folder")
        assert "open-folder.ps1" in line and f"-Which {which}" in line


def test_waiting_for_the_hub_and_the_finish_page():
    iss = _iss()
    assert "HUB_WAIT_MS = 90000" in iss
    assert "last-start-error.txt" in iss and "StartErrorLine" in iss
    offer = iss.split("function OfferSetupPage", 1)[1].split("end;", 1)[0]
    assert "HubAnswered" in offer and "not SetupDone" in offer                  # no setup page when the hub is down
    assert _lines("Run", "Check: OfferSetupPage")
    assert "'\"setup_done\":true'" in iss                                        # "Already set up" only when it is


def test_data_folder_permissions_use_language_neutral_sids():
    perms = _iss().split("procedure SetDataPermissions", 1)[1].split("end;", 1)[0]
    assert "/inheritance:r" in perms
    assert "*S-1-5-18:(OI)(CI)F" in perms and "*S-1-5-32-544:(OI)(CI)F" in perms   # SYSTEM, Administrators
    assert "*S-1-5-32-545:(OI)(CI)RX" in perms                                      # Users: read only...
    assert "\\logs\" /grant *S-1-5-32-545:(OI)(CI)M" in perms                      # ...except the logs
    assert "users-modify" not in _iss()


def test_ready_page_warns_about_updates():
    assert "Install updates when nobody is driving: the hub restarts." in _iss()


def test_version_info_and_optional_signing():
    setup = _section("Setup")
    assert "VersionInfoCompany={#Company}" in setup and "VersionInfoProductName={#AppName}" in setup
    assert "AppPublisher={#Company}" in setup and "#ifdef SignInstaller" in setup
    build = (PKG / "build.ps1").read_text(encoding="utf-8")
    assert "/DCompany=$($brand.COMPANY)" in build
    assert "_SIGN_CERT" in build and "_SIGN_PASS" in build and "if ($signCert -and $signPass)" in build
    spec = (PKG / "pitwall.spec").read_text(encoding="utf-8")
    assert "version=VERSION_INFO" in spec and "brand.COMPANY" in spec and "brand.PRODUCT_NAME" in spec
