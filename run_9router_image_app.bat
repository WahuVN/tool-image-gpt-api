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

set PORT=8501
set HOST=127.0.0.1
set STREAMLIT_BROWSER_GATHER_USAGE_STATS=false
set STREAMLIT_GLOBAL_EMAIL=

echo Dang mo Web UI tai: http://%HOST%:%PORT%
start "" "http://%HOST%:%PORT%"
".venv\Scripts\python.exe" -m streamlit run nine_router_image_app.py --server.headless true --server.port %PORT% --server.address %HOST%

endlocal
