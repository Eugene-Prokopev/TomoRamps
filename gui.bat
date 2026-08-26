@echo off
rem TomoRamps GUI launcher
cd /d %~dp0
.venv\Scripts\python.exe app\main.py
if errorlevel 1 pause
