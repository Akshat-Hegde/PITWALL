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
Name: "{commonstartup}\{#AppName} TV"; Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "{code:TvLauncherParams}"; WorkingDir: "{app}\tools"; IconFilename: "{app}\{#ExeName}.ico"; Flags: runminimized; Tasks: startuptv
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
  FreshInstall, SetupDone, HubAnswered, StartupTvDefaulted: Boolean;
  SetupCodeText, StartErrorLine: String;
  TaskDisabled, TaskRecreated: Boolean;
  CodeLabel, HelpLabel: TNewStaticText;
  HubAddrPage: TInputQueryWizardPage;

function HomeDir: String;
begin
  Result := ExpandConstant('{commonappdata}\{#AppName}');
end;

function DataDir: String;
begin
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

function InitializeSetup: Boolean;
begin
  // Decided before any file is written: settings.json only exists once a previous install was set up.
  FreshInstall := not FileExists(DataDir + '\settings.json');
  SetupDone := ReadSetupDone;
  Log('Fresh install: ' + IntToStr(Ord(FreshInstall)) + ', setup done: ' + IntToStr(Ord(SetupDone)));
  Result := True;
end;

// --- TV-only PCs: the hub PC's address ------------------------------------------------------------------------

// "192.168.1.20", "hubpc", "http://192.168.1.20:8000/staff" -> "192.168.1.20:8000" (empty when nothing usable).
function HubHostPort(Typed: String): String;
var
  P: Integer;
begin
  Result := Trim(Typed);
  if Pos('http://', Lowercase(Result)) = 1 then Delete(Result, 1, 7)
  else if Pos('https://', Lowercase(Result)) = 1 then Delete(Result, 1, 8);
  P := Pos('/', Result);
  if P > 0 then Result := Copy(Result, 1, P - 1);
  if (Result = '') or (Pos(' ', Result) > 0) or (Result[1] = ':') then
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
  if CurPageID <> HubAddrPage.ID then Exit;
  HostPort := HubHostPort(HubAddrPage.Values[0]);
  if HostPort = '' then
  begin
    MsgBox('Type the hub PC''s address, for example 192.168.1.20, or its name.', mbError, MB_OK);
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

function HubRunning: Boolean;
var
  ResultCode: Integer;
begin
  // find exits 0 when the exe is in the tasklist
  Result := Exec(ExpandConstant('{sys}\cmd.exe'), '/c tasklist /FI "IMAGENAME eq {#ExeName}.exe" | find /I "{#ExeName}.exe" >nul',
    '', SW_HIDE, ewWaitUntilTerminated, ResultCode) and (ResultCode = 0);
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
    Sleep(1000);
  end;
  if HubRunning then
  begin
    Log('Hub still running after the task was ended: taskkill');
    Exec('taskkill.exe', '/F /IM {#ExeName}.exe', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
    Sleep(1000);
  end;
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
  if IsHub then StopHub;          // a TV-only PC has no hub to stop
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
  // the virus scanner looking at every new file, takes a while.
  HubAnswered := False;
  Started := GetTickCount;
  while (GetTickCount - Started) < HUB_WAIT_MS do
  begin
    if UrlAnswers('http://localhost:{#HttpPort}/api/health', 1000) then
    begin
      HubAnswered := True;
      Log('The hub answers after ' + IntToStr((GetTickCount - Started) div 1000) + ' s.');
      Exit;
    end;
    Sleep(500);
  end;
  Log('The hub did not answer on port {#HttpPort} within 90 s.');
end;

// The first line of <data>\last-start-error.txt (the hub writes the plain-English reason there), or ''.
function ReadStartError: String;
var
  Raw: AnsiString;
  P: Integer;
begin
  Result := '';
  if not LoadStringFromFile(DataDir + '\last-start-error.txt', Raw) then Exit;
  Result := Trim(String(Raw));
  P := Pos(#10, Result);
  if P > 0 then Result := Trim(Copy(Result, 1, P - 1));
  if Length(Result) > 220 then Result := Copy(Result, 1, 217) + '...';
end;

procedure Netsh(Params: String);
var
  ResultCode: Integer;
begin
  Exec('netsh.exe', Params, '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Log('netsh ' + Params + ' -> ' + IntToStr(ResultCode));
end;

procedure Icacls(Params: String);
var
  ResultCode: Integer;
begin
  Exec(ExpandConstant('{sys}\icacls.exe'), Params, '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Log('icacls ' + Params + ' -> ' + IntToStr(ResultCode));
end;

// The cafe's folder: SYSTEM (the hub) and Administrators full control, ordinary users read only, except the logs
// folder, which they may also change. Well-known SIDs, so it works in every Windows language. Inheritance from
// ProgramData is cut (it lets every user create files), and anything below is reset to inherit from here.
procedure SetDataPermissions;
begin
  ForceDirectories(DataDir + '\logs');
  Icacls('"' + HomeDir + '" /inheritance:r /grant:r *S-1-5-18:(OI)(CI)F *S-1-5-32-544:(OI)(CI)F *S-1-5-32-545:(OI)(CI)RX /Q');
  Icacls('"' + HomeDir + '\*" /reset /T /C /Q');
  Icacls('"' + DataDir + '\logs" /grant *S-1-5-32-545:(OI)(CI)M /Q');
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
      Log('Setup code: ' + SetupCodeText);
    end
    else
      Log('Could not read setup-code.txt');
  end
  else
    Log('Upgrade over an existing setup: no new setup code.');

  // Firewall: old rules out, then the program rule plus port rules (in case the network profile is Public).
  Netsh('advfirewall firewall delete rule name="{#AppName} hub"');
  Netsh('advfirewall firewall delete rule name="{#AppName} telemetry"');
  Netsh('advfirewall firewall delete rule name="{#AppName} pages"');
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
  WizardForm.StatusLabel.Caption := 'Starting the hub (this can take up to a minute)...';
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

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep = ssPostInstall) and WizardIsTaskSelected('keepawake') then
    KeepAwake;
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
  if IsHub and (not FreshInstall or FileExists(ExpandConstant('{app}\{#ExeName}.exe'))) then
    Result := 'Install updates when nobody is driving: the hub restarts.' + NewLine + NewLine;
  if MemoTypeInfo <> '' then Result := Result + MemoTypeInfo + NewLine + NewLine;
  if IsTvOnly then
    Result := Result + 'The TV shows the hub at:' + NewLine + Space + TvUrl + NewLine + NewLine;
  if MemoDirInfo <> '' then Result := Result + MemoDirInfo + NewLine + NewLine;
  if MemoTasksInfo <> '' then Result := Result + MemoTasksInfo + NewLine;
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
    CodeLabel := TNewStaticText.Create(WizardForm);
    CodeLabel.Parent := WizardForm.FinishedPage;
    CodeLabel.AutoSize := False;
    CodeLabel.WordWrap := True;
    CodeLabel.Left := WizardForm.FinishedLabel.Left;
    CodeLabel.Width := WizardForm.FinishedLabel.Width;
    CodeLabel.Font.Size := 16;
    CodeLabel.Font.Style := [fsBold];
    HelpLabel := TNewStaticText.Create(WizardForm);
    HelpLabel.Parent := WizardForm.FinishedPage;
    HelpLabel.AutoSize := False;
    HelpLabel.WordWrap := True;
    HelpLabel.Left := WizardForm.FinishedLabel.Left;
    HelpLabel.Width := WizardForm.FinishedLabel.Width;
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
  WizardForm.RunList.Top := HelpLabel.Top + HelpLabel.Height + ScaleY(8);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
    StopHub;
  if (CurUninstallStep = usDone) and not UninstallSilent and DirExists(HomeDir) then
    MsgBox('{#AppName} was removed. Your cafe''s data (laps, settings, backups) was kept in ' +
      HomeDir + ' and is used again if you reinstall.', mbInformation, MB_OK);
end;
