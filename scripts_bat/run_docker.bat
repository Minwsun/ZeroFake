@echo off
echo ========================================
echo   ZeroFake - Docker Startup Script
echo ========================================

:: Switch to project root directory
cd /d "%~dp0.."

echo Checking Docker...
docker --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Docker is not installed or not running!
    echo Please install Docker Desktop first: https://www.docker.com/products/docker-desktop
    pause
    exit /b
)

echo.
echo Starting ZeroFake services...
echo Building backend and frontend (this may take a few minutes)...
echo.

cd docker
docker-compose up --build

pause
