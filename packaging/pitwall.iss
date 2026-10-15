; Installer for the hub. Every name comes from hub\simtelemetry\brand.py via packaging\build.ps1 (/D defines).
#ifndef AppName
  #error Build with packaging\build.ps1
#endif
#ifndef ExeName
  #error Build with packaging\build.ps1
#endif
#ifndef TaskName
  #error Build with packaging\build.ps1
#endif
#ifndef AppVersion
  #error Build with packaging\build.ps1
#endif
#ifndef Company
  #error Build with packaging\build.ps1
#endif
#define HttpPort "8000"

[Setup]
AppId={{B7C1E0A4-5D2F-4C57-9A53-2E6F4D8A9C11}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#Company}
VersionInfoCompany={#Company}
VersionInfoProductName={#AppName}
VersionInfoProductVersion={#AppVersion}
VersionInfoVersion={#AppVersion}
VersionInfoDescription={#AppName} installer
VersionInfoCopyright={#Company}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename={#ExeName}-Setup-{#AppVersion}
SetupIconFile=pitwall.ico
UninstallDisplayIcon={app}\{#ExeName}.ico
WizardStyle=modern
CloseApplications=yes
SetupLogging=yes
Compression=lzma2
SolidCompression=yes
; Only one copy of this installer at a time. (No AppMutex: the hub runs in the background as SYSTEM, which the
; owner can't close; the installer stops it itself in PrepareToInstall and starts it again afterwards.)
SetupMutex={#ExeName}SetupMutex,Global\{#ExeName}SetupMutex
#ifdef SignInstaller
; build.ps1 passes /DSignInstaller and /Ssigntool=... when a code-signing certificate is configured.
SignTool=signtool
SignedUninstaller=yes
#endif

[Types]
Name: "hub"; Description: "Hub PC: runs {#AppName} for the cafe (it can show the TV too)"
Name: "tv"; Description: "This PC only shows the TV (the hub runs on another PC)"

[Components]
Name: "hub"; Description: "{#AppName} hub: rigs, TV, staff, owner and setup pages"; Types: hub; Flags: fixed
Name: "tvonly"; Description: "This PC only shows the TV (the hub runs on another PC)"; Types: tv; Flags: fixed

[Tasks]
Name: "keepawake"; Description: "Keep this PC awake (recommended for the hub and TV PC)"
Name: "startuptv"; Description: "Open the TV page when this PC signs in"; Flags: unchecked

[InstallDelete]
; Program files of the previous version: old libraries must not mix with the new ones. (The cafe's data lives in
; ProgramData and is never touched.)
Type: filesandordirs; Name: "{app}\_internal"; Components: hub
; A hub PC switched to TV-only: its hub program and hub shortcuts go (the hub was stopped and its boot task and
; firewall rules removed in PrepareToInstall). The cafe's data stays in ProgramData.
Type: filesandordirs; Name: "{app}\_internal"; Components: tvonly
Type: files; Name: "{app}\{#ExeName}.exe"; Components: tvonly
Type: files; Name: "{autoprograms}\{#AppName} Staff.*"; Components: tvonly
Type: files; Name: "{autoprograms}\{#AppName} Owner.*"; Components: tvonly
Type: files; Name: "{autoprograms}\{#AppName} Setup.*"; Components: tvonly
Type: files; Name: "{autoprograms}\{#AppName} Show setup code.lnk"; Components: tvonly
Type: files; Name: "{autoprograms}\{#AppName} Reset owner PIN.lnk"; Components: tvonly
Type: files; Name: "{autoprograms}\{#AppName} Open backups folder.lnk"; Components: tvonly
Type: files; Name: "{autoprograms}\{#AppName} Open logs folder.lnk"; Components: tvonly

[Files]
Source: "..\dist\{#ExeName}\*"; DestDir: "{app}"; Components: hub; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "..\tools\windows\*"; DestDir: "{app}\tools"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "pitwall.ico"; DestDir: "{app}"; DestName: "{#ExeName}.ico"; Flags: ignoreversion
; The commented reference config, always the current version's, next to hub.toml.
Source: "..\config\hub.example.toml"; DestDir: "{commonappdata}\{#AppName}\config"; Components: hub; Flags: ignoreversion uninsneveruninstall
; A commented starter config for a fresh install; an existing hub.toml (even after an uninstall) is never touched.
Source: "..\config\hub.example.toml"; DestDir: "{commonappdata}\{#AppName}\config"; DestName: "hub.toml"; Components: hub; Flags: onlyifdoesntexist uninsneveruninstall
; Last, so AfterInstall runs once the exe and everything else is in place. It writes the task XML, sets the data
; folder's permissions, makes the setup code, sets up the firewall and the boot task, and starts the hub.
Source: "pitwall-task.xml"; DestDir: "{tmp}"; Components: hub; Flags: ignoreversion deleteafterinstall; AfterInstall: AfterAllFiles

[Icons]
; The TV launcher runs hidden; it opens the TV page, or a local waiting page until the hub answers.
Name: "{autoprograms}\{#AppName} TV"; Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "{code:TvLauncherParams}"; WorkingDir: "{app}\tools"; IconFilename: "{app}\{#ExeName}.ico"; Flags: runminimized
Name: "{autodesktop}\{#AppName} TV"; Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "{code:TvLauncherParams}"; WorkingDir: "{app}\tools"; IconFilename: "{app}\{#ExeName}.ico"; Flags: runminimized
Name: "{commonstartup}\{#AppName} TV"; Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "{code:TvLauncherParams}"; WorkingDir: "{app}\tools"; IconFilename: "{app}\{#ExeName}.ico"; Flags: runminimized; Check: WantStartupTv
Name: "{autoprograms}\{#AppName} Staff"; Filename: "http://localhost:{#HttpPort}/staff"; Components: hub
Name: "{autoprograms}\{#AppName} Owner"; Filename: "http://localhost:{#HttpPort}/owner"; Components: hub
Name: "{autoprograms}\{#AppName} Setup"; Filename: "http://localhost:{#HttpPort}/setup"; Components: hub
; Admin commands: a command window that asks for administrator rights (the cafe's data folder is protected), says
; in one line what it does, and stays open so the result can be read.
Name: "{autoprograms}\{#AppName} Show setup code"; Filename: "{cmd}"; Parameters: "/k ""echo This shows the one-time code for the setup page. Once setup is done, use your owner PIN instead. & echo. & ""{app}\{#ExeName}.exe"" setup-code"""; WorkingDir: "{app}"; IconFilename: "{app}\{#ExeName}.ico"; Components: hub; AfterInstall: RunAsAdministrator('{autoprograms}\{#AppName} Show setup code.lnk')
Name: "{autoprograms}\{#AppName} Reset owner PIN"; Filename: "{cmd}"; Parameters: "/k ""echo Forgot the owner PIN? This opens the setup page again so you can choose a new owner PIN. Laps, rigs and settings are kept. & echo To cancel, close this window. & pause & ""{app}\{#ExeName}.exe"" setup-code --reset"""; WorkingDir: "{app}"; IconFilename: "{app}\{#ExeName}.ico"; Components: hub; AfterInstall: RunAsAdministrator('{autoprograms}\{#AppName} Reset owner PIN.lnk')
Name: "{autoprograms}\{#AppName} Open backups folder"; Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File ""{app}\tools\open-folder.ps1"" -Which backups -Exe ""{app}\{#ExeName}.exe"""; WorkingDir: "{app}\tools"; IconFilename: "{sys}\shell32.dll"; IconIndex: 3; Flags: runminimized; Components: hub
Name: "{autoprograms}\{#AppName} Open logs folder"; Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File ""{app}\tools\open-folder.ps1"" -Which logs -Exe ""{app}\{#ExeName}.exe"""; WorkingDir: "{app}\tools"; IconFilename: "{sys}\shell32.dll"; IconIndex: 3; Flags: runminimized; Components: hub
Name: "{autoprograms}\Uninstall {#AppName}"; Filename: "{uninstallexe}"

[Run]
; Stopping the old hub, the firewall rules, the boot task and starting the hub are done in [Code] (AfterAllFiles),
; so a failure is logged and shown instead of passing silently.
Filename: "http://localhost:{#HttpPort}/setup"; Description: "Open the setup page"; Flags: shellexec postinstall skipifsilent; Check: OfferSetupPage
Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "{code:TvLauncherParams}"; WorkingDir: "{app}\tools"; Description: "Open the TV now"; Flags: postinstall skipifsilent nowait runhidden runasoriginaluser; Components: tvonly

[UninstallRun]
Filename: "schtasks.exe"; Parameters: "/End /TN ""{#TaskName}"""; Flags: runhidden; RunOnceId: "EndTask"
Filename: "schtasks.exe"; Parameters: "/Delete /F /TN ""{#TaskName}"""; Flags: runhidden; RunOnceId: "DeleteTask"
Filename: "netsh.exe"; Parameters: "advfirewall firewall delete rule name=""{#AppName} hub"""; Flags: runhidden; RunOnceId: "FwHub"
Filename: "netsh.exe"; Parameters: "advfirewall firewall delete rule name=""{#AppName} telemetry"""; Flags: runhidden; RunOnceId: "FwTelemetry"
Filename: "netsh.exe"; Parameters: "advfirewall firewall delete rule name=""{#AppName} pages"""; Flags: runhidden; RunOnceId: "FwPages"

[Code]
const
  HUB_WAIT_MS = 90000;           // how long the installer waits for a freshly started hub to answer

var
  FreshInstall, SetupDone, HubAnswered, StartupTvDefaulted, IcaclsFailed: Boolean;
  SetupCodeText, StartErrorLine, DataPath: String;
  TaskDisabled, TaskRecreated: Boolean;
  CodeLabel, HelpLabel, WarnLabel: TNewStaticText;
  HubAddrPage: TInputQueryWizardPage;

function HomeDir: String;
begin
  Result := ExpandConstant('{commonappdata}\{#AppName}');
end;

// The cafe's data folder: hub.toml's data_dir as the hub program reports it (ResolveDataDir, once the new program is
// in place), else the default <ProgramData>\<name>\data.
function DataDir: String;
begin
  if DataPath <> '' then
    Result := DataPath
  else
    Result := HomeDir + '\data';
end;

function IsHub: Boolean;
begin
  Result := WizardIsComponentSelected('hub');
end;

function IsTvOnly: Boolean;
begin
  Result := WizardIsComponentSelected('tvonly');
end;

// The last non-empty line of a text file (UTF-8 with or without a BOM, or plain ASCII), trimmed; '' when none.
function LastLineOf(FileName: String): String;
var
  Lines: TArrayOfString;
  I: Integer;
begin
  Result := '';
  if not LoadStringsFromFile(FileName, Lines) then Exit;
  for I := GetArrayLength(Lines) - 1 downto 0 do
    if Trim(Lines[I]) <> '' then
    begin
      Result := Trim(Lines[I]);
      Break;
    end;
end;

// Asks the installed hub program where its data folder is ("<exe> folder data": reads hub.toml, writes nothing), so
// a data_dir changed in hub.toml is honoured. Falls back to the default folder when the program can't answer.
function ResolveDataDir: String;
var
  Exe, OutFile, Line: String;
  ResultCode: Integer;
begin
  Result := HomeDir + '\data';
  Exe := ExpandConstant('{app}\{#ExeName}.exe');
  if not FileExists(Exe) then
  begin
    Log('No hub program yet: data folder ' + Result);
    Exit;
  end;
  OutFile := ExpandConstant('{tmp}\data-folder.txt');
  DeleteFile(OutFile);
  // cmd strips the outer quotes of /c "..."; UTF-8 output so a folder name in any language comes back intact.
  if not Exec(ExpandConstant('{cmd}'), '/c "set PYTHONIOENCODING=utf-8&& "' + Exe + '" folder data > "' + OutFile +
      '" 2>nul"', '', SW_HIDE, ewWaitUntilTerminated, ResultCode) or (ResultCode <> 0) then
  begin
    Log('"folder data" failed (exit code ' + IntToStr(ResultCode) + '): data folder ' + Result);
    Exit;
  end;
  Line := LastLineOf(OutFile);
  if (Length(Line) > 3) and ((Copy(Line, 2, 2) = ':\') or (Copy(Line, 1, 2) = '\\')) then
    Result := RemoveBackslashUnlessRoot(Line)
  else
    Log('"folder data" gave no usable folder (' + Line + ')');
  Log('Data folder: ' + Result);
end;

// settings.json says setup_done = true (it is written with json.dumps(indent=2); spaces and line breaks ignored).
function ReadSetupDone: Boolean;
var
  Raw: AnsiString;
  Text: String;
begin
  Result := False;
  if not LoadStringFromFile(DataDir + '\settings.json', Raw) then Exit;
  Text := String(Raw);
  StringChangeEx(Text, ' ', '', True);
  StringChangeEx(Text, #9, '', True);
  StringChangeEx(Text, #13, '', True);
  StringChangeEx(Text, #10, '', True);
  Result := Pos('"setup_done":true', Text) > 0;
end;

// Decided once the new program is in place but before the hub has started again (it was stopped in
// PrepareToInstall): settings.json only exists once a previous install was set up.
procedure DetectInstallState;
begin
  DataPath := ResolveDataDir;
  FreshInstall := not FileExists(DataDir + '\settings.json');
  SetupDone := ReadSetupDone;
  Log('Fresh install: ' + IntToStr(Ord(FreshInstall)) + ', setup done: ' + IntToStr(Ord(SetupDone)));
end;

// --- TV-only PCs: the hub PC's address ------------------------------------------------------------------------

function IsHostChar(C: Char): Boolean;
begin
  Result := ((C >= 'A') and (C <= 'Z')) or ((C >= 'a') and (C <= 'z')) or ((C >= '0') and (C <= '9')) or
    (C = '.') or (C = '-');
end;

// host or host:port, host = letters, digits, dots and dashes, port = 1 to 5 digits (1-65535).
function ValidHostPort(S: String): Boolean;
var
  I, Colon: Integer;
  Host, Port: String;
begin
  Result := False;
  Colon := Pos(':', S);
  if Colon > 0 then
  begin
    Host := Copy(S, 1, Colon - 1);
    Port := Copy(S, Colon + 1, Length(S));
    if (Length(Port) < 1) or (Length(Port) > 5) then Exit;
    for I := 1 to Length(Port) do
      if (Port[I] < '0') or (Port[I] > '9') then Exit;
    if (StrToIntDef(Port, 0) < 1) or (StrToIntDef(Port, 0) > 65535) then Exit;
  end
  else
    Host := S;
  if Host = '' then Exit;
  for I := 1 to Length(Host) do
    if not IsHostChar(Host[I]) then Exit;
  Result := True;
end;

// "192.168.1.20", "hubpc", "http://192.168.1.20:8000/staff" -> "192.168.1.20:8000"; '' when it isn't an address.
function HubHostPort(Typed: String): String;
var
  P: Integer;
begin
  Result := Trim(Typed);
  if Pos('http://', Lowercase(Result)) = 1 then Delete(Result, 1, 7)
  else if Pos('https://', Lowercase(Result)) = 1 then Delete(Result, 1, 8);
  P := Pos('/', Result);                       // a trailing slash, or a pasted page such as /staff
  if P > 0 then Result := Copy(Result, 1, P - 1);
  if not ValidHostPort(Result) then
  begin
    Result := '';
    Exit;
  end;
  if Pos(':', Result) = 0 then Result := Result + ':{#HttpPort}';
end;

function TvUrl: String;
begin
  if IsTvOnly then
    Result := 'http://' + HubHostPort(HubAddrPage.Values[0]) + '/'
  else
    Result := 'http://localhost:{#HttpPort}/';
end;

function TvLauncherParams(Param: String): String;
begin
  Result := '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + ExpandConstant('{app}\tools\tv-launcher.ps1') +
    '" -Url "' + TvUrl + '"';
end;

// The TV opens at sign-in: the task is ticked, or a silent TV-only install that didn't choose its tasks (a TV-only
// PC is there to show the TV).
function WantStartupTv: Boolean;
begin
  Result := WizardIsTaskSelected('startuptv') or
    (WizardSilent and IsTvOnly and (ExpandConstant('{param:TASKS|}') = '') and (ExpandConstant('{param:MERGETASKS|}') = ''));
end;

function UrlAnswers(Url: String; TimeoutMs: Integer): Boolean;
var
  Req: Variant;
begin
  Result := False;
  try
    Req := CreateOleObject('WinHttp.WinHttpRequest.5.1');
    Req.Open('GET', Url, False);
    Req.SetTimeouts(TimeoutMs, TimeoutMs, TimeoutMs, TimeoutMs);
    Req.Send('');
    Result := (Req.Status = 200);
  except
    Result := False;
  end;
end;

procedure InitializeWizard;
begin
  HubAddrPage := CreateInputQueryPage(wpSelectComponents, 'The hub PC',
    'Which PC runs the hub?',
    'Type the hub PC''s address as its setup page shows it (for example 192.168.1.20), or the hub PC''s name. ' +
    'This PC''s TV then shows that hub.');
  HubAddrPage.Add('Hub PC address or name:', False);
  HubAddrPage.Values[0] := GetPreviousData('HubAddress', '');
  // Silent TV-only install: /HUB=192.168.1.20 (required, see PrepareToInstall).
  if ExpandConstant('{param:HUB|}') <> '' then
    HubAddrPage.Values[0] := ExpandConstant('{param:HUB|}');
end;

procedure RegisterPreviousData(PreviousDataKey: Integer);
begin
  SetPreviousData(PreviousDataKey, 'HubAddress', HubAddrPage.Values[0]);
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := (PageID = HubAddrPage.ID) and not IsTvOnly;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  HostPort: String;
begin
  Result := True;
  if (CurPageID <> HubAddrPage.ID) or WizardSilent then Exit;
  if Trim(HubAddrPage.Values[0]) = '' then
  begin
    MsgBox('Type the hub PC''s address, for example 192.168.1.20, or its name.', mbError, MB_OK);
    Result := False;
    Exit;
  end;
  HostPort := HubHostPort(HubAddrPage.Values[0]);
  if HostPort = '' then
  begin
    MsgBox('That isn''t a PC address. Type it like 192.168.1.20 or hubpc: only letters, digits, dots and dashes, ' +
      'with :8000 at the end only if the hub uses another port.', mbError, MB_OK);
    Result := False;
    Exit;
  end;
  if not UrlAnswers('http://' + HostPort + '/api/health', 3000) then
    Result := MsgBox('The hub at ' + HostPort + ' doesn''t answer right now. Check that the hub PC is switched on ' +
      'and on the same network, and that the address is right.' + #13#10#13#10 + 'Use this address anyway?',
      mbConfirmation, MB_YESNO) = IDYES;
end;

// --- Stopping and starting the hub ----------------------------------------------------------------------------

function GetTickCount: Cardinal;
  external 'GetTickCount@kernel32.dll stdcall';

// Waits about Seconds seconds without freezing the wizard: Exec keeps the window painted and responsive while it
// waits for ping (Sleep would not).
procedure PumpWait(Seconds: Integer);
var
  ResultCode: Integer;
begin
  Exec(ExpandConstant('{sys}\ping.exe'), '-n ' + IntToStr(Seconds + 1) + ' 127.0.0.1', '', SW_HIDE,
    ewWaitUntilTerminated, ResultCode);
end;

function HubRunning: Boolean;
var
  ResultCode: Integer;
begin
  // find exits 0 when the exe is in the tasklist
  Result := Exec(ExpandConstant('{sys}\cmd.exe'), '/c tasklist /FI "IMAGENAME eq {#ExeName}.exe" | find /I "{#ExeName}.exe" >nul',
    '', SW_HIDE, ewWaitUntilTerminated, ResultCode) and (ResultCode = 0);
end;

function HubTaskExists: Boolean;
var
  ResultCode: Integer;
begin
  Result := Exec('schtasks.exe', '/Query /TN "{#TaskName}"', '', SW_HIDE, ewWaitUntilTerminated, ResultCode) and
    (ResultCode = 0);
end;

// This PC runs (or ran) the hub: its program or its boot task is here.
function HubInstalledHere: Boolean;
begin
  Result := FileExists(ExpandConstant('{app}\{#ExeName}.exe')) or HubTaskExists;
end;

procedure StopHub;
var
  ResultCode, I: Integer;
begin
  // The hub runs as SYSTEM, which the wizard cannot close. Disable the task first, or its every-minute trigger
  // starts the old exe again while files are being replaced; then end it, wait, and kill what is left.
  Exec('schtasks.exe', '/Change /TN "{#TaskName}" /Disable', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Log('schtasks /Change /Disable -> ' + IntToStr(ResultCode));
  if ResultCode = 0 then TaskDisabled := True;
  Exec('schtasks.exe', '/End /TN "{#TaskName}"', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  for I := 1 to 15 do
  begin
    if not HubRunning then Break;
    PumpWait(1);
  end;
  if HubRunning then
  begin
    Log('Hub still running after the task was ended: taskkill');
    Exec('taskkill.exe', '/F /IM {#ExeName}.exe', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
    PumpWait(1);
  end;
end;

procedure Netsh(Params: String);
var
  ResultCode: Integer;
begin
  Exec('netsh.exe', Params, '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Log('netsh ' + Params + ' -> ' + IntToStr(ResultCode));
end;

procedure DeleteFirewallRules;
begin
  Netsh('advfirewall firewall delete rule name="{#AppName} hub"');
  Netsh('advfirewall firewall delete rule name="{#AppName} telemetry"');
  Netsh('advfirewall firewall delete rule name="{#AppName} pages"');
end;

// A hub PC switched to TV-only: what the uninstaller does ([UninstallRun]): the boot task and the firewall rules go.
// (The hub was stopped first; its program files go in [InstallDelete]; the cafe's data is kept.)
procedure RemoveHubFromThisPC;
var
  ResultCode: Integer;
begin
  Exec('schtasks.exe', '/End /TN "{#TaskName}"', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Exec('schtasks.exe', '/Delete /F /TN "{#TaskName}"', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Log('Switched to TV-only: schtasks /Delete -> ' + IntToStr(ResultCode));
  TaskDisabled := False;                // nothing to turn back on if the install is cancelled now
  DeleteFirewallRules;
end;

procedure DeinitializeSetup;
var
  ResultCode: Integer;
begin
  // A cancelled or failed upgrade must not leave the cafe without its hub: turn the old task back on.
  if TaskDisabled and not TaskRecreated then
  begin
    Exec('schtasks.exe', '/Change /TN "{#TaskName}" /Enable', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
    Log('Install did not finish: re-enabled the old task -> ' + IntToStr(ResultCode));
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  if IsTvOnly and (HubHostPort(HubAddrPage.Values[0]) = '') then
  begin
    // Only possible in a silent install, which has no address page: it must be given on the command line.
    Result := 'A TV-only install needs the hub PC''s address. Run it with /HUB=<address>, for example /HUB=192.168.1.20.';
    Log(Result);
    Exit;
  end;
  if IsHub then StopHub          // a TV-only PC has no hub to stop...
  else if HubInstalledHere then  // ...unless it was the hub until now
  begin
    Log('This PC was the hub and becomes TV-only: stopping and removing the hub.');
    StopHub;
    RemoveHubFromThisPC;
  end;
end;

procedure WriteTaskXml;
var
  Task: AnsiString;
  Text: String;
  Lines: TArrayOfString;
  Exe, Data: String;
begin
  if not LoadStringFromFile(ExpandConstant('{tmp}\pitwall-task.xml'), Task) then
  begin
    Log('Could not read the hub start-up task definition.');
    Exit;
  end;
  Exe := ExpandConstant('{app}\{#ExeName}.exe');
  Data := HomeDir;
  StringChangeEx(Exe, '&', '&amp;', True);
  StringChangeEx(Data, '&', '&amp;', True);
  Text := String(Task);
  StringChangeEx(Text, '__EXE__', Exe, True);
  StringChangeEx(Text, '__DATA__', Data, True);
  SetArrayLength(Lines, 1);
  Lines[0] := Text;
  SaveStringsToUTF8File(ExpandConstant('{tmp}\pitwall-task.xml'), Lines, False);   // matches the XML declaration
end;

procedure WaitForHub;
var
  Started: Cardinal;
begin
  // Up to 90 s, measured on the clock (each probe can itself take a second): a first start on a slow PC, with
  // the virus scanner looking at every new file, takes a while. The wizard stays responsive (PumpWait) and the
  // progress bar moves while it waits.
  HubAnswered := False;
  WizardForm.StatusLabel.Caption := 'Starting the hub' + #$2026 + ' this can take a minute';
  WizardForm.ProgressGauge.Style := npbstMarquee;
  Started := GetTickCount;
  while not HubAnswered and ((GetTickCount - Started) < HUB_WAIT_MS) do
  begin
    if UrlAnswers('http://localhost:{#HttpPort}/api/health', 1000) then
    begin
      HubAnswered := True;
      Log('The hub answers after ' + IntToStr((GetTickCount - Started) div 1000) + ' s.');
    end
    else
      PumpWait(1);
  end;
  WizardForm.ProgressGauge.Style := npbstNormal;
  if not HubAnswered then
    Log('The hub did not answer on port {#HttpPort} within 90 s.');
end;

// The first line of <data>\last-start-error.txt (the hub writes the plain-English reason there, UTF-8), or ''.
function ReadStartError: String;
var
  Lines: TArrayOfString;
  I: Integer;
begin
  Result := '';
  if not LoadStringsFromFile(DataDir + '\last-start-error.txt', Lines) then Exit;
  for I := 0 to GetArrayLength(Lines) - 1 do
    if Trim(Lines[I]) <> '' then
    begin
      Result := Trim(Lines[I]);
      Break;
    end;
  if Length(Result) > 220 then Result := Copy(Result, 1, 217) + '...';
end;

procedure Icacls(Params: String);
var
  ResultCode: Integer;
begin
  if not Exec(ExpandConstant('{sys}\icacls.exe'), Params, '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
    ResultCode := -1;
  Log('icacls ' + Params + ' -> ' + IntToStr(ResultCode));
  if ResultCode <> 0 then IcaclsFailed := True;      // the finish page says so
end;

// A data_dir set in hub.toml to a drive or a Windows folder must never have its permissions replaced.
function SafeToLock(Folder: String): Boolean;
var
  F: String;
begin
  F := Lowercase(RemoveBackslashUnlessRoot(Folder));
  Result := (Length(F) > 3) and (F <> Lowercase(ExpandConstant('{win}'))) and
    (F <> Lowercase(ExpandConstant('{commonpf}'))) and (F <> Lowercase(ExpandConstant('{commonappdata}'))) and
    (F <> Lowercase(RemoveBackslashUnlessRoot(GetEnv('USERPROFILE')))) and (F <> Lowercase(GetEnv('SystemDrive') + '\users'));
end;

// Who may do what (well-known SIDs, so it works in every Windows language; nobody but SYSTEM and Administrators
// may write anywhere):
//   <ProgramData>\<name>, config, backups: SYSTEM and Administrators full control, Users read.
//   data (laps.db with guests' phone numbers, settings.json, setup-code.txt): SYSTEM and Administrators only.
//   data\logs: also Users read (the "Open logs folder" shortcut; Windows lets anyone pass through data to it).
// Inheritance from ProgramData is cut (it lets every user create files); everything below is reset to inherit from
// these folders. The hub runs as SYSTEM and the admin shortcuts run elevated, so they can still write everything.
procedure SetDataPermissions;
begin
  IcaclsFailed := False;
  ForceDirectories(HomeDir);
  ForceDirectories(DataDir + '\logs');
  Icacls('"' + HomeDir + '" /inheritance:r /grant:r *S-1-5-18:(OI)(CI)F *S-1-5-32-544:(OI)(CI)F *S-1-5-32-545:(OI)(CI)RX /Q');
  Icacls('"' + HomeDir + '\*" /reset /T /C /Q');
  if not SafeToLock(DataDir) then
  begin
    Log('Data folder ' + DataDir + ' is a drive or a Windows folder: its permissions are left alone.');
    IcaclsFailed := True;
    Exit;
  end;
  Icacls('"' + DataDir + '" /reset /Q');                    // no leftover explicit entries (a data_dir elsewhere)
  Icacls('"' + DataDir + '" /inheritance:r /grant:r *S-1-5-18:(OI)(CI)F *S-1-5-32-544:(OI)(CI)F /Q');
  Icacls('"' + DataDir + '\*" /reset /T /C /Q');
  Icacls('"' + DataDir + '\logs" /grant *S-1-5-32-545:(OI)(CI)RX /Q');
end;

procedure RunAsAdministrator(LinkPath: String);
var
  Lnk: AnsiString;
  Path: String;
begin
  // Shell link header: LinkFlags is the DWORD at offset 20; RunAsUser is 0x00002000, i.e. bit 0x20 of byte 21
  // (Pascal strings start at 1). Windows then asks for administrator rights whenever the shortcut is opened.
  Path := ExpandConstant(LinkPath);
  if not LoadStringFromFile(Path, Lnk) or (Length(Lnk) < 24) then
  begin
    Log('Could not mark ' + Path + ' to run as administrator.');
    Exit;
  end;
  Lnk[22] := Chr(Ord(Lnk[22]) or $20);
  if SaveStringToFile(Path, Lnk, False) then
    Log('Marked ' + Path + ' to run as administrator.')
  else
    Log('Could not save ' + Path);
end;

procedure AfterAllFiles;
var
  ResultCode: Integer;
  Code: AnsiString;
  Ok: Boolean;
begin
  WizardForm.StatusLabel.Caption := 'Setting up the hub...';
  DetectInstallState;
  WriteTaskXml;
  SetDataPermissions;
  if FreshInstall or not SetupDone then
  begin
    // A fresh install gets a new code; an install that was never set up keeps the code it has (or gets one).
    if FreshInstall then
      Ok := Exec(ExpandConstant('{app}\{#ExeName}.exe'), 'setup-code --new', '', SW_HIDE, ewWaitUntilTerminated, ResultCode)
    else
      Ok := Exec(ExpandConstant('{app}\{#ExeName}.exe'), 'setup-code', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
    if not Ok or (ResultCode <> 0) then
      Log('setup-code failed, exit code ' + IntToStr(ResultCode));
    if LoadStringFromFile(DataDir + '\setup-code.txt', Code) then
    begin
      SetupCodeText := Trim(String(Code));
      Log('Setup code made: it is on the last page and never in this log.');
    end
    else
      Log('Could not read setup-code.txt');
  end
  else
    Log('Upgrade over an existing setup: no new setup code.');

  // Firewall: old rules out, then the program rule plus port rules (in case the network profile is Public).
  DeleteFirewallRules;
  Netsh('advfirewall firewall add rule name="{#AppName} hub" dir=in action=allow program="' + ExpandConstant('{app}\{#ExeName}.exe') + '" enable=yes profile=private,domain');
  Netsh('advfirewall firewall add rule name="{#AppName} telemetry" dir=in action=allow protocol=UDP localport=20777 enable=yes profile=any');
  Netsh('advfirewall firewall add rule name="{#AppName} pages" dir=in action=allow protocol=TCP localport={#HttpPort} enable=yes profile=any');

  // Boot task, then start the hub now. An old start-up problem must not be shown as this start's.
  DeleteFile(DataDir + '\last-start-error.txt');
  Ok := Exec('schtasks.exe', '/Create /F /TN "{#TaskName}" /XML "' + ExpandConstant('{tmp}\pitwall-task.xml') + '"', '',
    SW_HIDE, ewWaitUntilTerminated, ResultCode) and (ResultCode = 0);
  Log('schtasks /Create -> ' + IntToStr(ResultCode));
  if Ok then TaskRecreated := True;     // registered again, enabled
  if not Ok then
  begin
    SuppressibleMsgBox('The hub could not be set to start with this PC (error ' + IntToStr(ResultCode) +
      '). The install log has the details. The hub will not start by itself until this is fixed.', mbError, MB_OK, IDOK);
    Exit;
  end;
  WizardForm.StatusLabel.Caption := 'Starting the hub' + #$2026 + ' this can take a minute';
  Ok := Exec('schtasks.exe', '/Run /TN "{#TaskName}"', '', SW_HIDE, ewWaitUntilTerminated, ResultCode) and (ResultCode = 0);
  Log('schtasks /Run -> ' + IntToStr(ResultCode));
  if Ok then
    WaitForHub
  else
    Log('The hub task was created but could not be started: it starts when this PC restarts.');
  if not HubAnswered then
  begin
    StartErrorLine := ReadStartError;
    if StartErrorLine <> '' then Log('last-start-error.txt: ' + StartErrorLine);
  end;
end;

procedure KeepAwake;
var
  ResultCode: Integer;
begin
  // On mains power: never sleep, never hibernate, never switch the screen off (the TV is a screen too).
  Exec('powercfg.exe', '/change standby-timeout-ac 0', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Log('powercfg standby-timeout-ac 0 -> ' + IntToStr(ResultCode));
  Exec('powercfg.exe', '/change hibernate-timeout-ac 0', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Log('powercfg hibernate-timeout-ac 0 -> ' + IntToStr(ResultCode));
  Exec('powercfg.exe', '/change monitor-timeout-ac 0', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Log('powercfg monitor-timeout-ac 0 -> ' + IntToStr(ResultCode));
end;

// tv-launcher.ps1 -StartOnLogin puts "<name> TV.lnk" in the user's own Startup folder; with the all-users one from
// this installer the TV would open twice at sign-in. ({userstartup} is the account the installer runs as: the
// signed-in user when they confirmed the administrator prompt themselves.)
procedure RemoveOwnStartupTv;
var
  Lnk: String;
begin
  Lnk := ExpandConstant('{userstartup}\{#AppName} TV.lnk');
  if FileExists(Lnk) then
  begin
    if DeleteFile(Lnk) then Log('Removed ' + Lnk + ' (the installer''s sign-in shortcut replaces it).')
    else Log('Could not remove ' + Lnk);
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep <> ssPostInstall then Exit;
  if WizardIsTaskSelected('keepawake') then
    KeepAwake;
  if WantStartupTv then
    RemoveOwnStartupTv;
end;

// --- Wizard pages -----------------------------------------------------------------------------------------------

function OfferSetupPage: Boolean;
begin
  Result := IsHub and HubAnswered and not SetupDone;
end;

function UpdateReadyMemo(Space, NewLine, MemoUserInfoInfo, MemoDirInfo, MemoTypeInfo, MemoComponentsInfo,
  MemoGroupInfo, MemoTasksInfo: String): String;
begin
  Result := '';
  if IsHub and HubInstalledHere then
    Result := 'Install updates when nobody is driving: the hub restarts.' + NewLine + NewLine;
  if IsTvOnly and HubInstalledHere then
    Result := 'This PC will stop being the hub. The hub on this PC is stopped and no longer starts with Windows; ' +
      'rigs, phones and other TVs must use the new hub PC. The cafe''s data is kept in ' + HomeDir + '.' +
      NewLine + NewLine;
  if MemoTypeInfo <> '' then Result := Result + MemoTypeInfo + NewLine + NewLine;
  if IsTvOnly then
    Result := Result + 'The TV shows the hub at:' + NewLine + Space + TvUrl + NewLine + NewLine;
  if MemoDirInfo <> '' then Result := Result + MemoDirInfo + NewLine + NewLine;
  if MemoTasksInfo <> '' then Result := Result + MemoTasksInfo + NewLine;
end;

function NewLabel: TNewStaticText;
begin
  Result := TNewStaticText.Create(WizardForm);
  Result.Parent := WizardForm.FinishedPage;
  Result.AutoSize := False;
  Result.WordWrap := True;
  Result.Left := WizardForm.FinishedLabel.Left;
  Result.Width := WizardForm.FinishedLabel.Width;
end;

procedure CurPageChanged(CurPageID: Integer);
var
  Shown: String;
begin
  if (CurPageID = wpSelectTasks) and IsTvOnly and not StartupTvDefaulted then
  begin
    WizardSelectTasks('startuptv');      // a TV-only PC is there to show the TV: open it at sign-in by default
    StartupTvDefaulted := True;
  end;
  if CurPageID <> wpFinished then Exit;
  if CodeLabel = nil then
  begin
    CodeLabel := NewLabel;
    CodeLabel.Font.Size := 16;
    CodeLabel.Font.Style := [fsBold];
    HelpLabel := NewLabel;
    WarnLabel := NewLabel;
    WarnLabel.Font.Color := clRed;
  end;
  CodeLabel.Top := WizardForm.FinishedLabel.Top + WizardForm.FinishedLabel.Height + ScaleY(12);
  CodeLabel.Height := ScaleY(40);
  HelpLabel.Height := ScaleY(60);
  if IsTvOnly then
  begin
    CodeLabel.Caption := 'This PC shows the TV';
    HelpLabel.Caption := 'It shows the hub at ' + TvUrl + '. Open "{#AppName} TV" on the desktop to start it. ' +
      'Until the hub answers, the TV says "Starting up".';
  end
  else if not HubAnswered then
  begin
    CodeLabel.Font.Color := clRed;
    CodeLabel.Caption := 'The hub has not started';
    Shown := '';
    if StartErrorLine <> '' then Shown := 'It said: ' + StartErrorLine + #13#10;
    Shown := Shown + 'It may still be starting. Wait a minute, then open "{#AppName} Setup" in the Start menu. ' +
      'If it doesn''t open, restart this PC.';
    if SetupDone then
      Shown := Shown + ' Your cafe''s data and settings were kept.'
    else if SetupCodeText <> '' then
      Shown := Shown + #13#10 + 'Your setup code: ' + SetupCodeText + ' (write it down; "{#AppName} Show setup code" in the Start menu shows it again).';
    HelpLabel.Caption := Shown;
    HelpLabel.Height := ScaleY(110);
  end
  else if SetupDone then
  begin
    CodeLabel.Caption := 'Already set up: use your owner PIN.';
    HelpLabel.Caption := 'Your cafe''s data and settings were kept.';
  end
  else if SetupCodeText <> '' then
  begin
    CodeLabel.Height := ScaleY(70);
    CodeLabel.Caption := 'Your setup code: ' + SetupCodeText;
    HelpLabel.Caption := 'Enter it on the setup page that opens next. It works once.' + #13#10 +
      'Can''t find it later? Open "{#AppName} Show setup code" in the Start menu.';
  end
  else
  begin
    CodeLabel.Caption := 'Setup code not available';
    HelpLabel.Caption := 'Open "{#AppName} Show setup code" in the Start menu to get it.';
  end;
  HelpLabel.Top := CodeLabel.Top + CodeLabel.Height + ScaleY(4);
  WarnLabel.Top := HelpLabel.Top + HelpLabel.Height + ScaleY(4);
  if IsHub and IcaclsFailed then
  begin
    WarnLabel.Caption := 'Warning: the cafe''s data folder could not be fully locked to administrators (the install ' +
      'log has the details). Run this installer again; if this stays, ask for help.';
    WarnLabel.Height := ScaleY(30);
  end
  else
  begin
    WarnLabel.Caption := '';
    WarnLabel.Height := 0;
  end;
  WizardForm.RunList.Top := WarnLabel.Top + WarnLabel.Height + ScaleY(8);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
    StopHub;
  if (CurUninstallStep = usDone) and not UninstallSilent and DirExists(HomeDir) then
    MsgBox('{#AppName} was removed. Your cafe''s data (laps, settings, backups) was kept in ' +
      HomeDir + ' and is used again if you reinstall.', mbInformation, MB_OK);
end;
