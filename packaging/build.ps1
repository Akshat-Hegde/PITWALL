# Build dist\<exe>\<exe>.exe: dashboard first, then PyInstaller, a smoke test on spare ports, then the Inno Setup installer.
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
$smokeHome = Join-Path $env:TEMP "$($brand.SLUG)-smoke"
if (Test-Path $smokeHome) { Remove-Item $smokeHome -Recurse -Force }   # a fresh home, so setup is not done yet
Set-Item "env:$($brand.HOME_ENV)" $smokeHome
$p = Start-Process $exe -ArgumentList "run --demo --duration 25 --http-port 8199" -PassThru -WindowStyle Hidden
try {
  Start-Sleep -Seconds 12
  $h = Invoke-RestMethod http://127.0.0.1:8199/api/health
  $page = Invoke-WebRequest http://127.0.0.1:8199/ -UseBasicParsing
  if ($page.Content -notmatch "<div id=`"root`"") { throw "dashboard not served" }
  Write-Host "Smoke test OK: $($h | ConvertTo-Json -Compress)"
  # (--demo keeps its data in data-demo, so the code is made there.) The logo upload needs python-multipart, which PyInstaller only bundles via hiddenimports: prove it is in the exe.
  $code = (& $exe setup-code --data-dir "$smokeHome\data-demo" | Select-Object -Last 1).Trim()
  $png = Join-Path $env:TEMP "$($brand.SLUG)-smoke-logo.png"
  [IO.File]::WriteAllBytes($png, [Convert]::FromBase64String("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP4z8DwHwAFAAH/q842iQAAAABJRU5ErkJggg=="))
  $up = curl.exe -s -S -X POST -H "X-Setup-Code: $code" -F "file=@$png;type=image/png" http://127.0.0.1:8199/api/setup/logo
  if ($LASTEXITCODE -ne 0 -or $up -notmatch '"logo"\s*:\s*"logo-') { throw "Logo upload failed in the frozen exe: $up" }
  Write-Host "Logo upload OK: $up"
} finally { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue }

# The installer. Inno Setup 6 is installed machine-wide or per user (winget); take whichever exists.
$version = (& $exe --version).Split(" ")[-1]
$iscc = @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
          "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw "Inno Setup 6 not found. Install it: winget install -e --id JRSoftware.InnoSetup" }
& $iscc "/DAppName=$($brand.PRODUCT_NAME)" "/DExeName=$($brand.EXE_NAME)" "/DTaskName=$($brand.TASK_NAME)" `
        "/DAppVersion=$version" "$root\packaging\pitwall.iss"
if ($LASTEXITCODE -ne 0) { throw "ISCC failed (exit $LASTEXITCODE)" }
$installer = "$root\dist\$($brand.EXE_NAME)-Setup-$version.exe"
if (-not (Test-Path $installer)) { throw "$installer was not produced" }
Write-Host "Installer: $installer"
