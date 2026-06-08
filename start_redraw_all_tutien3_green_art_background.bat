@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Missing .venv\Scripts\python.exe. Run setup_9router_image_app.bat first.
  pause
  exit /b 1
)

if not exist "outputs\tutien3_green_generation" mkdir "outputs\tutien3_green_generation"
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set STAMP=%%i
set LOG=outputs\tutien3_green_generation\redraw_all_%STAMP%.log
set ERR=outputs\tutien3_green_generation\redraw_all_%STAMP%.err.log
set PIDFILE=outputs\tutien3_green_generation\redraw_all_%STAMP%.pid

powershell -NoProfile -ExecutionPolicy Bypass -Command "$p=Start-Process -FilePath '.\.venv\Scripts\python.exe' -ArgumentList @('tools\generate_tutien3_green_art.py','--overwrite','--workers','4','--contact-sheet') -WorkingDirectory '%CD%' -RedirectStandardOutput '%LOG%' -RedirectStandardError '%ERR%' -WindowStyle Hidden -PassThru; $p.Id | Set-Content '%PIDFILE%'; Write-Host ('Started TuTien3 green redraw. PID=' + $p.Id)"

echo Log: %CD%\%LOG%
echo Error log: %CD%\%ERR%
echo PID file: %CD%\%PIDFILE%
echo.
echo To watch progress:
echo powershell -NoProfile -Command "Get-Content '%CD%\%LOG%' -Wait -Tail 80"
pause
