@echo off
setlocal
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8

if not exist ".venv\Scripts\python.exe" (
  echo Missing .venv\Scripts\python.exe. Run setup_9router_image_app.bat first.
  pause
  exit /b 1
)

".venv\Scripts\python.exe" "tools\generate_tutien4_pink_alpha_art.py" --workers 4 --contact-sheet %*
set EXITCODE=%ERRORLEVEL%

echo.
if "%EXITCODE%"=="0" (
  echo Done. TuTien4 pink-screen raw + transparent art generated and validated.
  echo Raw pink:    TuTien4\Resources\^<group^>\_raw_background\^<code^>_pink_raw.png
  echo Final alpha: TuTien4\Resources\^<group^>\^<code^>.png
) else (
  echo Failed with exit code %EXITCODE%. Check outputs\tutien4_pink_alpha_generation.
)
pause
exit /b %EXITCODE%
