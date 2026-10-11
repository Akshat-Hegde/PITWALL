@echo off
rem Opens the TV dashboard full screen. Pass options through, e.g.:
rem   "Start TV.cmd" -Url http://192.168.1.64:8000/ -StartOnLogin
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tv-launcher.ps1" %*
