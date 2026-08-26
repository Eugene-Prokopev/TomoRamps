@echo off
rem Пульт управления столом (GUI)
cd /d %~dp0
.venv\Scripts\python.exe app\main.py
if errorlevel 1 pause
