@echo off
chcp 65001 >nul
echo Starting ZeroFake Server in a new window...
cd /d "%~dp0"
start "ZeroFake Server" cmd /k python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

echo.
echo Test trich xuat dia danh (API weather) - tuy chon
set /p CLAIM=Nhap cau can trich dia danh (bo trong de bo qua): 
if "%CLAIM%"=="" goto :end

echo Dang goi /extract_location ...
rem doi server khoi dong
timeout /t 4 /nobreak >nul
powershell -NoProfile -Command "$body = @{ text = '%CLAIM%' } | ConvertTo-Json; $resp = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/extract_location' -Method Post -Body $body -ContentType 'application/json'; Write-Host 'Canonical:' $resp.canonical; $resp | ConvertTo-Json -Depth 6"

:end
echo.
pause

