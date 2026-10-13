# Build dist\<exe>\<exe>.exe: dashboard first, then PyInstaller, then a smoke test on spare ports.
# Every product name comes from hub\simtelemetry\brand.py.
# Needs a python.org Python 3.11 venv at .venv-build (see README, "Building the installer").
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$py = "$root\.venv-build\Scripts\python.exe"
Push-Location "$root\dashboard"
try {
  npm ci
  if ($LASTEXITCODE -ne 0) { throw "npm ci failed (exit $LASTEXITCODE)" }
  npm run build
  if ($LASTEXITCODE -ne 0) { throw "npm run build failed (exit $LASTEXITCODE)" }
} finally { Pop-Location }
if (-not (Test-Path "$root\dashboard\dist\index.html")) { throw "dashboard\dist\index.html missing after the dashboard build" }
& $py -m pip install -q -e "$root[build]"
if ($LASTEXITCODE -ne 0) { throw "pip install failed (exit $LASTEXITCODE)" }
$brand = & $py -c "import json; from simtelemetry import brand; print(json.dumps(brand.as_dict()))" | ConvertFrom-Json
& $py -m PyInstaller --noconfirm --clean --distpath "$root\dist" --workpath "$root\build" "$root\packaging\pitwall.spec"
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }
$exe = "$root\dist\$($brand.EXE_NAME)\$($brand.EXE_NAME).exe"
& $exe --version
if ($LASTEXITCODE -ne 0) { throw "$exe --version failed (exit $LASTEXITCODE)" }
Set-Item "env:$($brand.HOME_ENV)" (Join-Path $env:TEMP "$($brand.SLUG)-smoke")
$p = Start-Process $exe -ArgumentList "run --demo --duration 25 --http-port 8199" -PassThru -WindowStyle Hidden
try {
  Start-Sleep -Seconds 12
  $h = Invoke-RestMethod http://127.0.0.1:8199/api/health
  $page = Invoke-WebRequest http://127.0.0.1:8199/ -UseBasicParsing
  if ($page.Content -notmatch "<div id=`"root`"") { throw "dashboard not served" }
  Write-Host "Smoke test OK: $($h | ConvertTo-Json -Compress)"
} finally { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue }
