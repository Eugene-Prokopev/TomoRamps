@echo off
rem Быстрый прогон тестов
cd /d %~dp0
.venv\Scripts\python.exe -m pytest -q
pause
