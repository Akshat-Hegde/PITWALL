<#
.SYNOPSIS
  Opens the hub's backups or logs folder in Explorer (the "Open backups folder" / "Open logs folder" Start-menu
  shortcuts). Runs hidden and only reads. "Open logs folder" runs as the signed-in user; "Open backups folder" runs
  elevated (Windows asks for administrator permission), because the default backups folder is closed to ordinary
  users: the zips hold guests' phone numbers and the Wi-Fi password. Explorer itself opens as the signed-in user, so
  Windows may say "You don't currently have permission to access this folder": an administrator clicks Continue.

.DESCRIPTION
  The backup folder is chosen on the owner page, so the hub program is asked where it is ("<exe> folder backups":
  it only reads the settings). When the folder isn't there (a USB stick that is unplugged), a message says so in
  plain words instead of Explorer showing an error.

.EXAMPLE
  .\open-folder.ps1 -Which backups -Exe "C:\Program Files\<product>\<product>.exe"
#>
[CmdletBinding()]
param(
  [ValidateSet("backups", "logs")]
  [string]$Which = "backups",
  [string]$Exe,                    # the hub program; default: the single program next to the tools folder
  [switch]$DryRun                  # print the folder, open nothing (used by the tests)
)

$ErrorActionPreference = "Stop"

function Find-HubExe {
  $appDir = Split-Path -Parent $PSScriptRoot
  $exes = @(Get-ChildItem -LiteralPath $appDir -Filter *.exe -File -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -notlike "unins*" })
  if ($exes.Count -eq 1) { return $exes[0].FullName }
  return $null
}

if (-not $Exe) { $Exe = Find-HubExe }
$folder = $null
if ($Exe -and (Test-Path -LiteralPath $Exe)) {
  # Windows PowerShell 5.1 turns a native program's stderr line (a hub.toml warning) into an error record, which
  # stops the script under "Stop" even with 2>$null: relax it for this one call. The path is the last stdout line.
  $savedPreference = $ErrorActionPreference
  $ErrorActionPreference = "Continue"
  try {
    $out = @(& $Exe folder $Which 2>$null)
    $exitCode = $LASTEXITCODE
    $lines = @($out | Where-Object { $_ -isnot [System.Management.Automation.ErrorRecord] } |
               ForEach-Object { ([string]$_).Trim() } | Where-Object { $_ })
    if ($exitCode -eq 0 -and $lines.Count -gt 0) { $folder = $lines[-1] }
  } catch { $folder = $null }
  finally { $ErrorActionPreference = $savedPreference }
}

if ($DryRun) { Write-Output "FOLDER $folder"; exit 0 }

function Show-Message([string]$text) {
  try {
    $shell = New-Object -ComObject WScript.Shell
    [void]$shell.Popup($text, 0, "Folder not found", 48)
  } catch { Write-Host $text }
}

if (-not $folder) {
  Show-Message "The folder could not be found. Restart this PC and try again."
  exit 1
}
if (-not (Test-Path -LiteralPath $folder -PathType Container)) {
  if ($Which -eq "backups") {
    Show-Message "The backup folder isn't there:`n$folder`n`nIf it is on a USB stick, plug the stick in. No backup has been made there yet if this is a new install."
  } else {
    Show-Message "The logs folder isn't there yet:`n$folder`n`nIt appears once the hub has started."
  }
  exit 1
}
Start-Process -FilePath "explorer.exe" -ArgumentList "`"$folder`""
