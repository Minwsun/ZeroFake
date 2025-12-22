@echo off
chcp 65001 >nul
REM Change to project root directory (parent of scripts_bat)
cd /d "%~dp0.."
start "ZeroFake Server" cmd /k python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000 --log-level warning --no-access-log

