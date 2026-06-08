@echo off
REM Tao shortcut "Wahu Image Studio" tren Desktop.
REM Shortcut tro toi launch_wahu.vbs de mo app khong hien cua so cmd den.

setlocal
cd /d "%~dp0"

if not exist "launch_wahu.vbs" (
  echo Khong tim thay file VBS launcher launch_wahu.vbs. Huy tao shortcut.
  pause
  exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0create_desktop_shortcut.ps1"

pause
endlocal
