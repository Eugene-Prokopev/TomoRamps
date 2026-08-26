@echo off
rem Run test suite
cd /d %~dp0
.venv\Scripts\python.exe -m pytest -q
pause
