@echo off
chcp 65001 >nul
echo Starting ZeroFake Server in a new window...
cd /d "%~dp0"
start "ZeroFake Server" cmd /k python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

echo.
echo Test trich xuat dia danh (API weather) - tuy chon
set /p CLAIM=Nhap cau can trich dia danh (bo trong de bo qua): 
if "%CLAIM%"=="" goto :end

setlocal EnableDelayedExpansion
set "CLAIM_ESC=%CLAIM%"

"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference='Stop';" ^
  "$bodyObj = @{ text = $env:CLAIM };" ^
  "$body = $bodyObj | ConvertTo-Json -Depth 5 -Compress;" ^
  "$headers = @{ 'Content-Type' = 'application/json; charset=utf-8' };" ^
  "$resp = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/extract_location' -Method Post -Headers $headers -Body $body;" ^
  "Write-Host 'Canonical:' ($resp.canonical);" ^
  "$resp | ConvertTo-Json -Depth 6"

:end
echo.
pause

