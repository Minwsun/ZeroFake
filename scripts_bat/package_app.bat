@echo off
echo ========================================
echo   ZeroFake - Create Offline Package
echo ========================================

:: Switch to project root directory
cd /d "%~dp0.."

echo 1. Creating 'dist' folder...
if not exist "dist" mkdir dist

echo.
echo 2. Building Docker images...
cd docker
docker-compose build
if %errorlevel% neq 0 (
    echo [ERROR] Build failed!
    pause
    exit /b
)
cd ..

echo.
echo 3. Exporting images to file (this may take a while)...
docker save -o dist/zerofake_images.tar zerofake-backend:latest zerofake-frontend:latest
if %errorlevel% neq 0 (
    echo [ERROR] Export failed!
    pause
    exit /b
)

echo.
echo 4. Copying configuration files...
copy docker\docker-compose.prod.yml dist\docker-compose.yml
copy .env dist\.env.example

echo.
echo 5. Creating run scripts in dist...
(
echo @echo off
echo echo ========================================
echo echo   ZeroFake - Offline Installer
echo echo ========================================
echo.
echo echo 1. Checking .env file...
echo if not exist .env ^(
echo     if exist .env.example ^(
echo         copy .env.example .env
echo         echo [INFO] Created .env from example. PLEASE UPDATE API KEYS!
echo         notepad .env
echo     ^) else ^(
echo         echo [ERROR] Missing .env file!
echo         pause
echo         exit /b
echo     ^)
echo ^)
echo.
echo echo 2. Loading Docker images...
echo docker load -i zerofake_images.tar
echo.
echo echo 3. Starting services...
echo docker-compose up -d
echo.
echo echo [SUCCESS] ZeroFake is running!
echo echo Frontend: http://localhost:3000
echo echo Backend: http://localhost:8000/docs
echo pause
) > dist\install_and_run.bat

echo.
echo ========================================
echo [SUCCESS] Package created in 'dist' folder!
echo.
echo To distribute:
echo 1. Zip the 'dist' folder
echo 2. Send to target machine
echo 3. Run 'install_and_run.bat' on target machine
echo ========================================
pause
