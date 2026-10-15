<#
.SYNOPSIS
  Opens the TV dashboard full screen (kiosk mode) in Edge or Chrome, with sound allowed.

.DESCRIPTION
  Run it on the PC that drives the TV. It opens the dashboard in kiosk mode with
  --autoplay-policy=no-user-gesture-required, so moment sounds play without anyone clicking the page. When the hub
  is not answering yet (right after the PCs start), it opens the local waiting.html next to this script instead:
  that page waits for the hub and switches to the dashboard by itself, so the TV never shows a browser error. The browser uses its own profile folder, so it doesn't touch anyone's
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
  [switch]$StartOnLogin,
  [switch]$RemoveStartOnLogin,
  [switch]$DryRun                   # print what would run, start nothing (used by the tests)
)

$ErrorActionPreference = "Stop"
# The product name lives in brand.py only. It is needed just for the start-at-login shortcut, so it is looked up
# lazily and never by running anything: a source checkout reads brand.py, an installed copy uses the name of the
# single program next to the tools folder (it equals brand.EXE_NAME). Returns $null when it can't be worked out.
function Get-ProductName {
  try {
    $brandPy = Join-Path (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)) "hub"; $brandPy = Join-Path (Join-Path $brandPy "simtelemetry") "brand.py"
    if (Test-Path -LiteralPath $brandPy) {
      $m = [regex]::Match((Get-Content -LiteralPath $brandPy -Raw), '(?m)^PRODUCT_NAME\s*=\s*"([^"]+)"')
      if ($m.Success) { return $m.Groups[1].Value }
    }
    $appDir = Split-Path -Parent $PSScriptRoot
    $exes = @(Get-ChildItem -LiteralPath $appDir -Filter *.exe -File -ErrorAction Stop |
              Where-Object { $_.Name -notlike "unins*" })
    if ($exes.Count -eq 1) { return [IO.Path]::GetFileNameWithoutExtension($exes[0].Name) }
  } catch { }
  return $null
}
function Get-ShortcutPath {
  $name = Get-ProductName
  if (-not $name) { Write-Warning "Could not work out the product name, so the start-at-login shortcut was not changed."; return $null }
  return Join-Path ([Environment]::GetFolderPath("Startup")) "$name TV.lnk"
}
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
# A shortcut from before the rename would open a second TV window at login.
$oldShortcut = Join-Path $startup $OldShortcutName
if (Test-Path $oldShortcut) { Remove-Item $oldShortcut -Force }

if ($RemoveStartOnLogin) {
  $shortcutPath = Get-ShortcutPath
  if (-not $shortcutPath) { exit 1 }
  if (Test-Path $shortcutPath) { Remove-Item $shortcutPath -Force; Write-Host "Removed: the TV no longer opens at login." }
  else { Write-Host "There was no start-at-login shortcut." }
  exit 0
}

if ($StartOnLogin) {
  $shortcutPath = Get-ShortcutPath
  if (-not $shortcutPath) { exit 1 }
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
  "--disable-features=Translate,LocalNetworkAccessChecks",   # the waiting page (a local file) may ask the hub
  "--disable-session-crashed-bubble",
  "--noerrdialogs",
  "--user-data-dir=`"$profileDir`""
)
if ($isEdge) { $browserArgs += "--edge-kiosk-type=fullscreen" }

# The hub answering now? Then open the TV page straight away; otherwise the local waiting page, which opens it
# as soon as the hub answers (never a browser error page on the TV).
$waitingFile = Join-Path $PSScriptRoot "waiting.html"
$waitingUrl = $null
if (Test-Path -LiteralPath $waitingFile) {
  $waitingUrl = ([Uri]$waitingFile).AbsoluteUri + "?to=" + [Uri]::EscapeDataString($Url)
}

if ($DryRun) {
  Write-Output "BROWSER $exe"
  Write-Output ("ARGS " + ($browserArgs -join " "))
  if ($waitingUrl) { Write-Output "WAITING $waitingUrl" }
  exit 0
}

$health = ([Uri]$Url).GetLeftPart([UriPartial]::Authority) + "/api/health"
$answers = $false
try { Invoke-WebRequest -UseBasicParsing -Uri $health -TimeoutSec 3 | Out-Null; $answers = $true } catch { }
if (-not $answers -and $waitingUrl) {
  $browserArgs[1] = $waitingUrl
}

Start-Process -FilePath $exe -ArgumentList $browserArgs
