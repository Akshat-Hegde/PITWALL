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

[Setup]
AppId={{B7C1E0A4-5D2F-4C57-9A53-2E6F4D8A9C11}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppName}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename={#ExeName}-Setup-{#AppVersion}
SetupIconFile=pitwall.ico
UninstallDisplayIcon={app}\{#ExeName}.exe
WizardStyle=modern
CloseApplications=yes
SetupLogging=yes
Compression=lzma2
SolidCompression=yes

[Tasks]
Name: "startuptv"; Description: "Open the TV page when this PC signs in"; Flags: unchecked

[Files]
Source: "..\dist\{#ExeName}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "..\tools\windows\*"; DestDir: "{app}\tools"; Flags: recursesubdirs createallsubdirs ignoreversion

[Dirs]
Name: "{commonappdata}\{#AppName}"; Permissions: users-modify

[Icons]
Name: "{autoprograms}\{#AppName} TV"; Filename: "{app}\tools\Start TV.cmd"; WorkingDir: "{app}\tools"; IconFilename: "{app}\{#ExeName}.exe"
Name: "{autoprograms}\{#AppName} Staff"; Filename: "http://localhost:8000/staff"
Name: "{autoprograms}\{#AppName} Owner"; Filename: "http://localhost:8000/owner"
Name: "{autoprograms}\{#AppName} Setup"; Filename: "http://localhost:8000/setup"
Name: "{autoprograms}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName} TV"; Filename: "{app}\tools\Start TV.cmd"; WorkingDir: "{app}\tools"; IconFilename: "{app}\{#ExeName}.exe"
Name: "{commonstartup}\{#AppName} TV"; Filename: "{app}\tools\Start TV.cmd"; WorkingDir: "{app}\tools"; IconFilename: "{app}\{#ExeName}.exe"; Tasks: startuptv

[Run]
Filename: "schtasks.exe"; Parameters: "/End /TN ""{#TaskName}"""; Flags: runhidden; StatusMsg: "Stopping the old hub..."
Filename: "netsh.exe"; Parameters: "advfirewall firewall delete rule name=""{#AppName} hub"""; Flags: runhidden
Filename: "netsh.exe"; Parameters: "advfirewall firewall delete rule name=""{#AppName} telemetry"""; Flags: runhidden
Filename: "netsh.exe"; Parameters: "advfirewall firewall delete rule name=""{#AppName} pages"""; Flags: runhidden
Filename: "netsh.exe"; Parameters: "advfirewall firewall add rule name=""{#AppName} hub"" dir=in action=allow program=""{app}\{#ExeName}.exe"" enable=yes profile=private,domain"; Flags: runhidden; StatusMsg: "Opening the firewall for rigs and phones..."
Filename: "netsh.exe"; Parameters: "advfirewall firewall add rule name=""{#AppName} telemetry"" dir=in action=allow protocol=UDP localport=20777 enable=yes profile=any"; Flags: runhidden
Filename: "netsh.exe"; Parameters: "advfirewall firewall add rule name=""{#AppName} pages"" dir=in action=allow protocol=TCP localport=8000 enable=yes profile=any"; Flags: runhidden
Filename: "schtasks.exe"; Parameters: "/Create /F /TN ""{#TaskName}"" /XML ""{tmp}\pitwall-task.xml"""; Flags: runhidden; StatusMsg: "Setting the hub to start with this PC..."
Filename: "schtasks.exe"; Parameters: "/Run /TN ""{#TaskName}"""; Flags: runhidden; StatusMsg: "Starting the hub..."
Filename: "http://localhost:8000/setup"; Description: "Open the setup page"; Flags: shellexec postinstall skipifsilent; Check: IsFreshInstall

[UninstallRun]
Filename: "schtasks.exe"; Parameters: "/End /TN ""{#TaskName}"""; Flags: runhidden; RunOnceId: "EndTask"
Filename: "schtasks.exe"; Parameters: "/Delete /F /TN ""{#TaskName}"""; Flags: runhidden; RunOnceId: "DeleteTask"
Filename: "netsh.exe"; Parameters: "advfirewall firewall delete rule name=""{#AppName} hub"""; Flags: runhidden; RunOnceId: "FwHub"
Filename: "netsh.exe"; Parameters: "advfirewall firewall delete rule name=""{#AppName} telemetry"""; Flags: runhidden; RunOnceId: "FwTelemetry"
Filename: "netsh.exe"; Parameters: "advfirewall firewall delete rule name=""{#AppName} pages"""; Flags: runhidden; RunOnceId: "FwPages"

[Code]
var
  FreshInstall: Boolean;
  SetupCodeText: String;
  CodeLabel, HelpLabel: TNewStaticText;

function DataDir: String;
begin
  Result := ExpandConstant('{commonappdata}\{#AppName}\data');
end;

function IsFreshInstall: Boolean;
begin
  Result := FreshInstall;
end;

function InitializeSetup: Boolean;
begin
  // Decided before any file is written: settings.json only exists once a previous install was set up.
  FreshInstall := not FileExists(DataDir + '\settings.json');
  Result := True;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
begin
  Result := '';
  // Stop the running hub so its files can be replaced on an upgrade.
  Exec('schtasks.exe', '/End /TN "{#TaskName}"', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Sleep(1500);
end;

procedure WriteTaskXml;
var
  Task: AnsiString;
  Text: String;
begin
  // Task definition with the installed paths filled in.
  if LoadStringFromFile(ExpandConstant('{tmp}\pitwall-task.xml'), Task) then
  begin
    Text := String(Task);
    StringChangeEx(Text, '__EXE__', ExpandConstant('{app}\{#ExeName}.exe'), True);
    StringChangeEx(Text, '__DATA__', ExpandConstant('{commonappdata}\{#AppName}'), True);
    SaveStringToFile(ExpandConstant('{tmp}\pitwall-task.xml'), AnsiString(Text), False);
  end
  else
    Log('Could not read the hub start-up task definition.');
end;

function HubAnswers: Boolean;
var
  Req: Variant;
begin
  Result := False;
  try
    Req := CreateOleObject('WinHttp.WinHttpRequest.5.1');
    Req.Open('GET', 'http://localhost:8000/api/health', False);
    Req.SetTimeouts(1000, 1000, 1000, 1000);
    Req.Send('');
    Result := (Req.Status = 200);
  except
    Result := False;
  end;
end;

procedure AfterAllFiles;
var
  ResultCode: Integer;
  Code: AnsiString;
begin
  WriteTaskXml;
  if FreshInstall then
  begin
    if not Exec(ExpandConstant('{app}\{#ExeName}.exe'), 'setup-code --new', '', SW_HIDE, ewWaitUntilTerminated, ResultCode)
       or (ResultCode <> 0) then
      Log('setup-code --new failed, exit code ' + IntToStr(ResultCode));
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
end;

procedure WaitForHub;
var
  I: Integer;
begin
  // The hub is started by the last non-postinstall [Run] line; give it up to 20 s before the setup page opens.
  for I := 1 to 20 do
  begin
    if HubAnswers then Break;
    Sleep(1000);
  end;
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if CurPageID <> wpFinished then Exit;
  WaitForHub;
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
  if FreshInstall and (SetupCodeText <> '') then
  begin
    CodeLabel.Height := ScaleY(70);
    CodeLabel.Caption := 'Your setup code: ' + SetupCodeText;
    HelpLabel.Caption := 'Enter it on the setup page that opens next. It works once.' + #13#10 +
      'Can''t find it later? Run "{#ExeName} setup-code" in "' + ExpandConstant('{app}') + '", or look in ' +
      ExpandConstant('{commonappdata}\{#AppName}') + '\data\logs\hub.log.';
  end
  else if FreshInstall then
  begin
    CodeLabel.Height := ScaleY(40);
    CodeLabel.Caption := 'Setup code not available';
    HelpLabel.Caption := 'Run "{#ExeName} setup-code" in "' + ExpandConstant('{app}') + '" to get it.';
  end
  else
  begin
    CodeLabel.Height := ScaleY(40);
    CodeLabel.Caption := 'Already set up: use your owner PIN.';
    HelpLabel.Caption := 'Your cafe''s data and settings were kept.';
  end;
  HelpLabel.Top := CodeLabel.Top + CodeLabel.Height + ScaleY(4);
  HelpLabel.Height := ScaleY(60);
  WizardForm.RunList.Top := HelpLabel.Top + HelpLabel.Height + ScaleY(8);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if (CurUninstallStep = usDone) and not UninstallSilent then
    MsgBox('{#AppName} was removed. Your cafe''s data (laps, settings, backups) was kept in ' +
      ExpandConstant('{commonappdata}\{#AppName}') + ' and is used again if you reinstall.', mbInformation, MB_OK);
end;
