@echo off
echo ======================================================================
echo ZeroFake Evaluation Runner
echo ======================================================================

REM Change to project root directory (parent of scripts_bat)
cd /d "%~dp0.."

REM Check if server is running
echo Checking if server is running...
curl -s http://127.0.0.1:8000/health >nul 2>&1
if %errorlevel% neq 0 (
    echo Server not running. Starting server...
    start "ZeroFake Server" cmd /c "python -m uvicorn app.main:app --host 127.0.0.1 --port 8000"
    echo Waiting 30 seconds for server to start...
    timeout /t 30 /nobreak
) else (
    echo Server is already running.
)

echo.
echo Starting evaluation...
echo ======================================================================
python evaluation/run_evaluation.py 100

echo.
echo ======================================================================
echo Evaluation completed!
echo Check evaluation/evaluation_report.md for results.
echo ======================================================================
pause
