@echo off
chcp 65001 >nul
cd /d "%~dp0"
start "ZeroFake Server" cmd /k python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

