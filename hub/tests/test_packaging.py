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
    for define in ("AppName", "ExeName", "TaskName", "AppVersion", "Vendor"):
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
    for line in _lines("Files", "Source:"):
        if r"..\tools\windows" not in line and "pitwall.ico" not in line and "dontcopy" not in line:
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
    # The backups folder is closed to ordinary users (guest phone numbers, the Wi-Fi password): its shortcut runs
    # elevated. The logs folder is open to them, so its shortcut doesn't ask.
    (backups,) = _lines("Icons", "Open backups folder")
    assert "RunAsAdministrator('{autoprograms}\\{#AppName} Open backups folder.lnk')" in backups
    (logs,) = _lines("Icons", "Open logs folder")
    assert "RunAsAdministrator" not in logs


def test_waiting_for_the_hub_and_the_finish_page():
    iss = _iss()
    assert "HUB_WAIT_MS = 90000" in iss
    assert "last-start-error.txt" in iss and "StartErrorLine" in iss
    offer = iss.split("function OfferSetupPage", 1)[1].split("end;", 1)[0]
    assert "HubAnswered" in offer and "not SetupDone" in offer                  # no setup page when the hub is down
    assert _lines("Run", "Check: OfferSetupPage")
    assert "'\"setup_done\":true'" in iss                                        # "Already set up" only when it is


def test_data_folder_permissions_use_language_neutral_sids():
    perms = _iss().split("procedure SetDataPermissions", 1)[1].split("\nend;", 1)[0]
    assert "/inheritance:r" in perms
    assert "*S-1-5-18:(OI)(CI)F" in perms and "*S-1-5-32-544:(OI)(CI)F" in perms   # SYSTEM, Administrators
    assert "*S-1-5-32-545:(OI)(CI)RX" in perms                                      # Users: read the cafe folder...
    data = perms.split("DataDir + '\" /inheritance:r", 1)[1].split("\n", 1)[0]
    assert "*S-1-5-18:(OI)(CI)F *S-1-5-32-544:(OI)(CI)F /Q" in data and "545" not in data   # ...not data...
    assert "\\logs\" /grant *S-1-5-32-545:(OI)(CI)RX" in perms                     # ...except the logs, read only
    iss = _iss()
    assert "(OI)(CI)M" not in iss and "users-modify" not in iss                   # no Users write anywhere
    assert "IcaclsFailed := True" in iss and "IsHub and IcaclsFailed" in iss      # a failure is shown at the end
    assert "if not SafeToLock(DataDir)" in perms                                  # never a drive or Windows folder
    # The default backups folder (next to data, like core config.default_backups_dir): SYSTEM + Administrators only
    assert "BackupDir := AddBackslash(ExtractFileDir(RemoveBackslashUnlessRoot(DataDir))) + 'backups'" in perms
    backups = perms.split("BackupDir + '\" /inheritance:r", 1)[1].split("\n", 1)[0]
    assert "*S-1-5-18:(OI)(CI)F *S-1-5-32-544:(OI)(CI)F /Q" in backups and "545" not in backups
    assert "if not SafeToLock(BackupDir)" in perms
    assert perms.index("ForceDirectories(BackupDir)") < perms.index("BackupDir + '\" /inheritance:r")


def test_data_folder_comes_from_the_hub_program():
    """A data_dir changed in hub.toml is honoured: the installer asks the program, else uses the default."""
    iss = _iss()
    resolve = iss.split("function ResolveDataDir", 1)[1].split("\nend;", 1)[0]
    assert "folder data" in resolve and "HomeDir + '\\data'" in resolve
    detect = iss.split("procedure DetectInstallState", 1)[1].split("\nend;", 1)[0]
    assert "DataPath := ResolveDataDir" in detect and "settings.json" in detect
    after = iss.split("procedure AfterAllFiles", 1)[1]
    assert after.index("DetectInstallState") < after.index("SetDataPermissions") < after.index("setup-code --new")
    assert "LoadStringsFromFile(DataDir + '\\last-start-error.txt'" in iss        # UTF-8 aware


def test_hub_address_accepts_only_host_and_port():
    valid = _iss().split("function ValidHostPort", 1)[1].split("\nend;", 1)[0]
    assert "IsHostChar" in valid and "65535" in valid and "Length(Port) > 5" in valid
    host = _iss().split("function IsHostChar", 1)[1].split("\nend;", 1)[0]
    assert "(C = '.') or (C = '-')" in host


def test_switching_to_tv_only_and_silent_tv_installs():
    iss = _iss()
    prep = iss.split("function PrepareToInstall", 1)[1].split("\nend;", 1)[0]
    assert "/HUB=" in prep and "else if HubInstalledHere then" in prep and "RemoveHubFromThisPC" in prep
    remove = iss.split("procedure RemoveHubFromThisPC", 1)[1].split("\nend;", 1)[0]
    assert "/Delete /F /TN" in remove and "DeleteFirewallRules" in remove
    assert "This PC will stop being the hub" in iss
    assert _lines("InstallDelete", r"{app}\{#ExeName}.exe", "Components: tvonly")
    assert "{param:HUB|}" in iss
    (startup,) = _lines("Icons", "{commonstartup}")
    assert "Check: WantStartupTv" in startup
    want = iss.split("function WantStartupTv", 1)[1].split("\nend;", 1)[0]
    assert "WizardSilent and IsTvOnly" in want
    assert r"{userstartup}\{#AppName} TV.lnk" in iss                             # no second TV window at sign-in


def test_waiting_keeps_the_wizard_responsive():
    wait = _iss().split("procedure WaitForHub", 1)[1].split("\nend;", 1)[0]
    assert "Sleep(" not in wait and "PumpWait(1)" in wait and "npbstMarquee" in wait


def test_ready_page_warns_about_updates():
    assert "Install updates when nobody is driving: the hub restarts." in _iss()


def test_version_info_and_optional_signing():
    setup = _section("Setup")
    assert "VersionInfoCompany={#Vendor}" in setup and "VersionInfoProductName={#AppName}" in setup
    assert "AppPublisher={#Vendor}" in setup and "#ifdef SignInstaller" in setup
    build = (PKG / "build.ps1").read_text(encoding="utf-8")
    assert "/DVendor=$Vendor" in build and "$Vendor = $brand.COMPANY" in build
    assert "_SIGN_CERT" in build and "_SIGN_PASS" in build and "if ($signCert) {" in build
    assert "timestamp.digicert.com" in build and '-eq "none"' in build
    assert "$q" in build and "sign.ps1" in build and "/p `\"" not in build        # password never on ISCC's line
    sign = (PKG / "sign.ps1").read_text(encoding="utf-8")
    assert "if ($env:SIGN_CERT_PASS)" in sign                                     # a .pfx without a password works
    spec = (PKG / "pitwall.spec").read_text(encoding="utf-8")
    assert "version=VERSION_INFO" in spec and "brand.PRODUCT_NAME" in spec


def test_program_file_details_name_no_company():
    """Decision 8.8 (user, 2026-11-03): Pitwall.exe's own details are neutral for every build (one program serves
    both variants): product name from brand, no company or copyright. The 9T7 installer's publisher stays."""
    spec = (PKG / "pitwall.spec").read_text(encoding="utf-8")
    code = "\n".join(line.split("#", 1)[0] for line in spec.splitlines())       # the code, not the comments
    assert "brand.COMPANY" not in code and "9T7" not in code.upper()
    assert "CompanyName" not in code and "LegalCopyright" not in code
    assert 'StringStruct("ProductName", brand.PRODUCT_NAME)' in code
    iss = (PKG / "pitwall.iss").read_text(encoding="utf-8")
    assert "AppPublisher={#Vendor}" in iss and "VersionInfoCompany={#Vendor}" in iss


# --- Factory C6: cafe installers (spec 2.4, 2.5, F5) --------------------------------------------------------------

GENERIC = {"AppName": "Pitwall", "ExeName": "Pitwall", "TaskName": "Pitwall Hub", "AppVersion": "0.6.0",
           "Vendor": "9T7 Racing"}
CAFE = {**GENERIC, "ProfileDir": r"C:\Shipments\profiles\apex", "CafeSlug": "Apex-Lounge"}
UNBRANDED = {**CAFE, "Vendor": ""}


def _preprocess(defines: dict[str, str]) -> str:
    """The installer script as Inno Setup's preprocessor leaves it for these /D defines: only the #ifdef / #ifndef /
    #if Vendor / #else / #endif lines it uses here (anything else starting with # stays; an active #error raises)."""
    out: list[str] = []
    stack: list[tuple[bool, bool]] = []          # (this branch active, parent active)
    active = True
    for line in _iss().splitlines():
        word = line.strip().split(" ", 1)
        cmd, arg = word[0], (word[1].strip() if len(word) > 1 else "")
        if cmd in ("#ifdef", "#ifndef", "#if"):
            if cmd == "#if":
                assert arg == 'Vendor != ""', f"the test doesn't know: {line}"
                cond = defines.get("Vendor", "") != ""
            else:
                cond = (arg in defines) == (cmd == "#ifdef")
            stack.append((cond, active))
            active = active and cond
        elif cmd == "#else":
            cond, parent = stack.pop()
            stack.append((not cond, parent))
            active = parent and not cond
        elif cmd == "#endif":
            _, active = stack.pop()
        elif active:
            if cmd == "#error":
                raise AssertionError(f"compile error with {defines}: {arg}")
            out.append(line)
    assert not stack
    return "\n".join(out) + "\n"


def _proc(text: str, name: str) -> str:
    return text.split(f"\n{name}", 1)[1].split("\nend;", 1)[0]


def test_generic_installer_is_unchanged_without_a_profile():
    iss = _preprocess(GENERIC)
    code = "\n".join(ln for ln in iss.splitlines() if not ln.lstrip().startswith((";", "//")))
    for word in ("provision", "ProfileDir", "CafeSlug", "FORCEOTHERCAFE", "ExtractTemporaryFiles", "dontcopy"):
        assert word not in code, word
    assert "OutputBaseFilename={#ExeName}-Setup-{#AppVersion}" in iss
    assert "AppPublisher={#Vendor}" in iss and "VersionInfoCompany={#Vendor}" in iss
    # the program build's stamp never goes to a cafe
    (program,) = [ln for ln in iss.splitlines() if ln.startswith(r'Source: "..\dist\{#ExeName}\*"')]
    assert 'Excludes: "build-stamp.json"' in program


def test_cafe_installer_needs_its_names_and_bakes_the_profile():
    with __import__("pytest").raises(AssertionError, match="Build with"):
        _preprocess({k: v for k, v in GENERIC.items() if k != "Vendor"})
    with __import__("pytest").raises(AssertionError, match="CafeSlug"):
        _preprocess({k: v for k, v in CAFE.items() if k != "CafeSlug"})
    iss = _preprocess(CAFE)
    assert "OutputBaseFilename={#ExeName}-Setup-{#CafeSlug}" in iss
    assert "OutputBaseFilename={#ExeName}-Setup-{#AppVersion}" not in iss
    files = _section("Files")
    (baked,) = [ln for ln in iss.splitlines() if "{#ProfileDir}" in ln and ln.startswith("Source:")]
    assert baked == r'Source: "{#ProfileDir}\*"; DestDir: "{tmp}\profile"; Flags: dontcopy'
    # the first file (solid compression: taking it out early decompresses everything listed before it), and before
    # the task XML line, whose AfterInstall must stay last
    sources = [ln for ln in iss.split("[Files]", 1)[1].split("\n[", 1)[0].splitlines() if ln.startswith("Source:")]
    assert sources[0] == baked
    assert files.index("{#ProfileDir}") < files.index('Source: "pitwall-task.xml"')
    # taken out in PrepareToInstall (dontcopy files are only in the installer until then), literally '{tmp}\...'
    assert "ExtractTemporaryFiles('{tmp}\\profile\\*')" in _proc(iss, "function ExtractProfile")


def test_whose_pc_check_runs_before_the_hub_is_stopped():
    iss = _preprocess(CAFE)
    prep = _proc(iss, "function PrepareToInstall")
    assert prep.index("ExtractProfile") < prep.index("CheckWhosePC") < prep.index("if IsHub then StopHub")
    assert "Result := 'This installer is damaged" in prep                    # no profile: refuse, nothing changed
    check = _proc(iss, "function CheckWhosePC")
    # the hub program already installed answers, reading only; no program yet = nothing to check
    assert "ExpandConstant('{app}\\{#ExeName}.exe')" in check and "if not FileExists(Exe) then" in check
    assert "RunProvision(Exe, ' --check', Output) = PROVISION_OTHER_CAFE" in check
    assert "Result := Output;" in check and "Nothing was changed on this PC." in check
    # the seller's override skips the check and is passed on to provision
    assert check.index("if ForceOtherCafe then") < check.index("RunProvision")
    assert "'/FORCEOTHERCAFE'" in _proc(iss, "function ForceOtherCafe")
    assert "--force-other-cafe" in _proc(iss, "function RunProvision")


def test_only_exit_code_3_refuses():
    """An installed 0.5.0 program has no provision command: argparse exits 2. Only 3 means another cafe's PC."""
    iss = _preprocess(CAFE)
    assert "PROVISION_OTHER_CAFE = 3;" in iss
    code = iss.split("[Code]", 1)[1]
    import re
    # every test of provision's exit code: the check's call, and ProvisionCafe's Code
    compares = re.findall(r"(?:RunProvision\([^;]*?\)|\bCode)\s*(=|<>|<|>)\s*(\w+)", code)
    assert sorted(set(compares)) == [("=", "0"), ("=", "PROVISION_OTHER_CAFE")]
    for exit_code in ("1", "2"):
        assert f"= {exit_code} then" not in _proc(iss, "function CheckWhosePC")
        assert f"Code = {exit_code}" not in _proc(iss, "procedure ProvisionCafe")


def test_provision_output_is_stdout_only_and_utf8():
    run = _proc(_preprocess(CAFE), "function RunProvision")
    assert "set PYTHONIOENCODING=utf-8&&" in run
    assert "' > \"' +" in run and "2>nul" in run                              # stdout to a file, stderr dropped
    assert "'provision \"' + ProfileFolder + '\"' + Extra" in run
    assert "Output := TextOf(OutFile)" in run and "ResultCode := -1" in run


def test_provision_runs_after_permissions_and_before_the_hub_starts():
    iss = _preprocess(CAFE)
    after = _proc(iss, "procedure AfterAllFiles")
    order = ["DetectInstallState", "SetDataPermissions", "ProvisionCafe", "setup-code --new", "/Create /F /TN",
             "/Run /TN"]
    assert [after.index(step) for step in order] == sorted(after.index(step) for step in order)
    prov = _proc(iss, "procedure ProvisionCafe")
    assert "RunProvision(ExpandConstant('{app}\\{#ExeName}.exe'), ''" in prov
    # never stops the install (files are already replaced): shows the reason, the hub still starts
    assert "if Code = 0 then Exit;" in prov and "SuppressibleMsgBox(Shown" in prov
    assert "The hub starts" in prov and "Abort" not in prov and "RaiseException" not in prov


def test_publisher_comes_only_from_the_vendor_define():
    from simtelemetry import brand
    raw = _iss()
    assert "9t7" not in raw.lower() and brand.COMPANY.lower() not in raw.lower()
    assert "{#Company}" not in raw and "AppPublisherURL" not in raw and "AppCopyright" not in raw
    for defines in (GENERIC, CAFE):
        setup = _preprocess(defines).split("[Setup]\n", 1)[1].split("\n[", 1)[0]
        for key in ("AppPublisher", "VersionInfoCompany", "VersionInfoCopyright"):
            assert f"{key}={{#Vendor}}" in setup
    setup = _preprocess(UNBRANDED).split("[Setup]\n", 1)[1].split("\n[", 1)[0]
    for key in ("AppPublisher=", "VersionInfoCompany=", "VersionInfoCopyright="):
        assert key not in setup                                               # no company string at all
    assert "{#Vendor}" not in _preprocess(UNBRANDED)
    # {#Vendor} is used nowhere but those three lines
    assert raw.count("{#Vendor}") == 3


def test_build_script_cafe_parameters_and_program_stamp():
    build = (PKG / "build.ps1").read_text(encoding="utf-8")
    params = build.split("param(", 1)[1].split("\n)", 1)[0]
    for name in ("[string]$ProfileDir", "[string]$CafeSlug", "[string]$Vendor", "[switch]$InstallerOnly"):
        assert name in params, name
    assert build.index("param(") < build.index("$ErrorActionPreference")      # param must come first
    # publisher: brand.COMPANY unless -Vendor is given; "none" (or empty) = unbranded
    assert 'if (-not $PSBoundParameters.ContainsKey("Vendor")) { $Vendor = $brand.COMPANY }' in build
    assert 'if ($Vendor -eq "none") { $Vendor = "" }' in build
    assert '"/DProfileDir=$ProfileDir"' in build and '"/DCafeSlug=$CafeSlug"' in build
    assert "-ProfileDir needs -CafeSlug" in build and "'^[A-Za-z0-9][A-Za-z0-9-]{0,59}$'" in build
    assert '(Resolve-Path -LiteralPath $ProfileDir).Path.TrimEnd("\\")' in build   # no trailing backslash before a quote
    assert '"$root\\dist\\$($brand.EXE_NAME)-Setup-$CafeSlug.exe"' in build
    # the stamp: removed before a program build, written last after the smoke test, compared for -InstallerOnly
    assert "build-stamp.json" in build
    assert build.index("Remove-Item -LiteralPath $stampFile") < build.index("PyInstaller --noconfirm")
    assert build.index("Logo upload OK") < build.index("[IO.File]::WriteAllText($stampFile")
    stamp = build.split("$stampJson = [ordered]@{", 1)[1].split("}", 1)[0]
    for key in ("version = $sourceVersion", "commit = $commit", "dirty = $dirty", "built = "):
        assert key in stamp, key
    reuse = build.split("if ($InstallerOnly) {", 1)[1].split("\nif (-not $reuse) {", 1)[0]
    for check in ("$stamp.version -ne $sourceVersion", "$stamp.commit -ne $commit", "elseif ($dirty)",
                  "Test-Path -LiteralPath $exe"):
        assert check in reuse, check
    assert "git -C $root rev-parse HEAD" in build
    assert build.index("if ($signCert) {") < build.index("if ($InstallerOnly) {")   # signing is known before
    assert "if (-not $reuse) {" in build and build.index("if (-not $reuse) {") < build.index("npm ci")
    assert build.index("if ($version -ne $sourceVersion)") < build.index("& $iscc")


def test_factory_is_never_bundled_into_the_program():
    spec = (PKG / "pitwall.spec").read_text(encoding="utf-8")
    excludes = spec.split("excludes=[", 1)[1].split("]", 1)[0]
    assert '"factory"' in excludes
