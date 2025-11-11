@echo off
chcp 65001 >nul
echo Starting ZeroFake Server...
cd /d "%~dp0"
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
pause

