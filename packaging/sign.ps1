# Signs one file with signtool. Called by build.ps1 for the exe and by Inno Setup (SignTool) for the installer and its
# uninstaller. The certificate settings come from environment variables that build.ps1 sets for this build only, so
# the password never appears on Inno's command line (its /S parameter) and needs no Inno quoting:
#   SIGN_TOOL_EXE   signtool.exe
#   SIGN_CERT_FILE  the .pfx file
#   SIGN_CERT_PASS  its password (may be empty: a .pfx without a password)
#   SIGN_TS_URL     timestamp server URL (empty: no timestamp)
param([Parameter(Mandatory = $true)][string]$File)
$ErrorActionPreference = "Stop"

# One argument quoted the way signtool (the Microsoft C runtime) reads it back: Windows PowerShell 5.1 does not
# escape quotes inside arguments, so the command line is built here and started directly.
function Format-Arg([string]$s) {
  if ($s -ne "" -and $s -notmatch '[\s"]') { return $s }
  $s = [regex]::Replace($s, '(\\*)"', { param($m) $m.Groups[1].Value * 2 + '\"' })
  $s = [regex]::Replace($s, '(\\+)$', { param($m) $m.Groups[1].Value * 2 })
  return '"' + $s + '"'
}

$signArgs = @("sign", "/f", $env:SIGN_CERT_FILE)
if ($env:SIGN_CERT_PASS) { $signArgs += @("/p", $env:SIGN_CERT_PASS) }
$signArgs += @("/fd", "SHA256")
if ($env:SIGN_TS_URL) { $signArgs += @("/tr", $env:SIGN_TS_URL, "/td", "SHA256") }
$signArgs += $File

$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = $env:SIGN_TOOL_EXE
$psi.Arguments = ($signArgs | ForEach-Object { Format-Arg $_ }) -join " "
$psi.UseShellExecute = $false
$proc = [System.Diagnostics.Process]::Start($psi)
$proc.WaitForExit()
exit $proc.ExitCode
