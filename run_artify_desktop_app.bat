@echo off
setlocal

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Chua setup app. Hay chay setup_9router_image_app.bat truoc.
  goto :eof
)

if not exist ".env.9router" (
  echo Chua co .env.9router
  echo Hay copy .env.9router.example thanh .env.9router va dien URL/KEY.
  goto :eof
)

echo Dang mo Artify AI Desktop App...
".venv\Scripts\python.exe" artify_desktop_app.py

endlocal
