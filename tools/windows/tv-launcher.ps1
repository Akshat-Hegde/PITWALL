<#
.SYNOPSIS
  Opens the TV dashboard full screen (kiosk mode) in Edge or Chrome, with sound allowed.

.DESCRIPTION
  Run it on the PC that drives the TV. It waits until the hub answers (handy right after the PC starts), then
  opens the dashboard in kiosk mode with --autoplay-policy=no-user-gesture-required, so moment sounds play
  without anyone clicking the page. The browser uses its own profile folder, so it doesn't touch anyone's
  normal browsing. Press Alt+F4 to close it.

  -StartOnLogin adds a shortcut to this Windows user's Startup folder, so the TV opens by itself after a
  restart; -RemoveStartOnLogin takes it away again.

.EXAMPLE
  .\tv-launcher.ps1                                     # this PC runs the hub too
  .\tv-launcher.ps1 -Url http://192.168.1.64:8000/      # the hub is another PC
  .\tv-launcher.ps1 -Url http://192.168.1.64:8000/portrait -StartOnLogin
#>
[CmdletBinding()]
param(
  [string]$Url = "http://localhost:8000/",
  [ValidateSet("auto", "edge", "chrome")]
  [string]$Browser = "auto",
  [int]$WaitSeconds = 120,          # how long to wait for the hub before opening anyway
  [switch]$StartOnLogin,
  [switch]$RemoveStartOnLogin,
  [switch]$DryRun                   # print what would run, start nothing (used by the tests)
)

$ErrorActionPreference = "Stop"
# The product name lives in brand.py only. Installed: the exe sits in the parent folder of tools\ and prints
# "Name x.y.z" for --version. From a source checkout: ask the repo's own Python.
function Get-ProductName {
  $appDir = Split-Path -Parent $PSScriptRoot
  $exes = @(Get-ChildItem -LiteralPath $appDir -Filter *.exe -File -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -notlike "unins*" })
  if ($exes.Count -eq 1) {
    $line = (& $exes[0].FullName --version 2>$null | Select-Object -First 1)
    $parts = @("$line".Trim() -split "\s+")
    if ($parts.Count -ge 2) { return ($parts[0..($parts.Count - 2)] -join " ") }
  }
  $repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
  $python = Join-Path $repo ".venv\Scripts\python.exe"
  if (Test-Path $python) {
    $name = (& $python -c "from simtelemetry import brand; print(brand.PRODUCT_NAME)" 2>$null | Select-Object -First 1)
    if ($name) { return "$name".Trim() }
  }
  throw "Could not work out the product name: no single program next to the tools folder and no .venv in the source checkout."
}
$ShortcutName = "$(Get-ProductName) TV.lnk"
$OldShortcutName = "Sim Telemetry TV.lnk"  # before the product was renamed

function Find-Browser([string]$which) {
  $edge = @(
    "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
    "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe"
  )
  $chrome = @(
    "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
    "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"
  )
  $candidates = switch ($which) {
    "edge"   { $edge }
    "chrome" { $chrome }
    default  { $chrome + $edge }   # Chrome first when both exist; Edge is on every Windows 10/11 PC
  }
  foreach ($path in $candidates) {
    if ($path -and (Test-Path $path)) { return $path }
  }
  return $null
}

$startup = [Environment]::GetFolderPath("Startup")
$shortcutPath = Join-Path $startup $ShortcutName
# A shortcut from before the rename would open a second TV window at login.
$oldShortcut = Join-Path $startup $OldShortcutName
if (Test-Path $oldShortcut) { Remove-Item $oldShortcut -Force }

if ($RemoveStartOnLogin) {
  if (Test-Path $shortcutPath) { Remove-Item $shortcutPath -Force; Write-Host "Removed: the TV no longer opens at login." }
  else { Write-Host "There was no start-at-login shortcut." }
  exit 0
}

if ($StartOnLogin) {
  $arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$PSCommandPath`" -Url `"$Url`" -Browser $Browser"
  if ($DryRun) { Write-Output "SHORTCUT $shortcutPath powershell.exe $arguments"; exit 0 }
  $shell = New-Object -ComObject WScript.Shell
  $link = $shell.CreateShortcut($shortcutPath)
  $link.TargetPath = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
  $link.Arguments = $arguments
  $link.WorkingDirectory = $PSScriptRoot
  $link.Description = "Opens the sim racing TV dashboard full screen"
  $link.Save()
  Write-Host "Added: the TV opens at login ($shortcutPath). Remove it with -RemoveStartOnLogin."
}

$exe = Find-Browser $Browser
if (-not $exe) {
  Write-Error "No $(if ($Browser -eq 'auto') { 'Edge or Chrome' } else { $Browser }) found. Install one, or pass -Browser."
  exit 2
}
$isEdge = $exe -like "*msedge.exe"
$profileDir = Join-Path $env:LOCALAPPDATA ("SimTelemetryTV\" + $(if ($isEdge) { "edge" } else { "chrome" }))

$browserArgs = @(
  "--kiosk", $Url,
  "--autoplay-policy=no-user-gesture-required",
  "--no-first-run",
  "--disable-features=Translate",
  "--disable-session-crashed-bubble",
  "--noerrdialogs",
  "--user-data-dir=`"$profileDir`""
)
if ($isEdge) { $browserArgs += "--edge-kiosk-type=fullscreen" }

if ($DryRun) {
  Write-Output "BROWSER $exe"
  Write-Output ("ARGS " + ($browserArgs -join " "))
  exit 0
}

# Wait for the hub, so the first thing on the TV isn't "can't reach this page".
$health = ([Uri]$Url).GetLeftPart([UriPartial]::Authority) + "/api/health"
$deadline = (Get-Date).AddSeconds($WaitSeconds)
while ((Get-Date) -lt $deadline) {
  try { Invoke-WebRequest -UseBasicParsing -Uri $health -TimeoutSec 3 | Out-Null; break }
  catch { Start-Sleep -Seconds 2 }
}

Start-Process -FilePath $exe -ArgumentList $browserArgs
