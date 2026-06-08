@echo off
setlocal
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8

if not exist ".venv\Scripts\python.exe" (
  echo Missing .venv\Scripts\python.exe. Run setup_9router_image_app.bat first.
  pause
  exit /b 1
)

".venv\Scripts\python.exe" "tools\generate_relic_contract_art.py" --validate-only --contact-sheet %*
set EXITCODE=%ERRORLEVEL%

echo.
if "%EXITCODE%"=="0" (
  echo OK. Relic contract art is complete.
) else (
  echo Validation failed with exit code %EXITCODE%.
)
pause
exit /b %EXITCODE%
