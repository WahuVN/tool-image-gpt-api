@echo off
setlocal
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8

if not exist ".venv\Scripts\python.exe" (
  echo Missing .venv\Scripts\python.exe. Run setup_9router_image_app.bat first.
  pause
  exit /b 1
)

".venv\Scripts\python.exe" "tools\generate_tutien3_green_art.py" --overwrite --workers 4 --contact-sheet %*
set EXITCODE=%ERRORLEVEL%

echo.
if "%EXITCODE%"=="0" (
  echo Done. All TuTien3 green-screen art has been redrawn and validated.
) else (
  echo Failed with exit code %EXITCODE%. Check outputs\tutien3_green_generation.
)
pause
exit /b %EXITCODE%
