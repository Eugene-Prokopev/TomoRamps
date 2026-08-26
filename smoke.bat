@echo off
rem Проверка платы: smoke.bat COM5
cd /d %~dp0
.venv\Scripts\python.exe scripts\smoke_serial.py --port %1
pause
