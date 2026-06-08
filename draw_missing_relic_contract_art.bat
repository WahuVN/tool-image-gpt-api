@echo off
setlocal
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8

if not exist ".venv\Scripts\python.exe" (
  echo Missing .venv\Scripts\python.exe. Run setup_9router_image_app.bat first.
  pause
  exit /b 1
)

".venv\Scripts\python.exe" "tools\generate_relic_contract_art.py" --workers 4 --contact-sheet %*
set EXITCODE=%ERRORLEVEL%

echo.
if "%EXITCODE%"=="0" (
  echo Done. Missing relic contract art is generated and validated.
) else (
  echo Failed with exit code %EXITCODE%. Check outputs\relic_contract_generation logs/contact sheets.
)
pause
exit /b %EXITCODE%
