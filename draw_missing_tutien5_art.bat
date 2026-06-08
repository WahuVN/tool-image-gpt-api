@echo off
setlocal
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8

if not exist ".venv\Scripts\python.exe" (
  echo Missing .venv\Scripts\python.exe. Run setup_9router_image_app.bat first.
  pause
  exit /b 1
)

".venv\Scripts\python.exe" "tools\generate_tutien5_art.py" --workers 4 --contact-sheet %*
set EXITCODE=%ERRORLEVEL%

echo.
if "%EXITCODE%"=="0" (
  echo Done. Missing TuTien5 art generated and validated under D:\TOOL\TOOL Anh\TuTien5.
) else (
  echo Failed with exit code %EXITCODE%. Check outputs\tutien5_generation logs/contact sheets.
)
pause
exit /b %EXITCODE%
