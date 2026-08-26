@echo off
rem Usage: smoke.bat COM11
cd /d %~dp0
.venv\Scripts\python.exe scripts\smoke_serial.py --port %1
pause
