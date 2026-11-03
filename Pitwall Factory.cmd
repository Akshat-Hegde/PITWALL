@echo off
rem The seller's factory window: cafe profiles, licences and packages. Seller's PC only; never shipped.
rem Needs the developer setup from README.md (the .venv folder).
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo The factory needs the Python setup first: see "Factory (seller only)" in README.md.
  pause
  exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" -m factory
