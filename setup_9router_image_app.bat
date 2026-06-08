@echo off
setlocal

cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo Khong tim thay Python. Hay cai Python 3.10+ truoc.
  goto :eof
)

if not exist ".venv\Scripts\python.exe" (
  echo Tao virtualenv .venv ...
  python -m venv .venv
)

echo Cai thu vien ...
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt

if not exist ".env.9router" (
  copy ".env.9router.example" ".env.9router" >nul
  echo Da tao .env.9router tu file mau.
)

if not exist ".streamlit" (
  mkdir ".streamlit"
)

(
  echo [browser]
  echo gatherUsageStats = false
  echo.
  echo [server]
  echo headless = true
  echo address = "127.0.0.1"
  echo port = 8501
  echo.
  echo [theme]
  echo base = "dark"
  echo primaryColor = "#0ea5e9"
  echo backgroundColor = "#0b1220"
  echo secondaryBackgroundColor = "#111827"
  echo textColor = "#e2e8f0"
) > ".streamlit\config.toml"

(
  echo [general]
  echo email = ""
) > ".streamlit\credentials.toml"

echo.
echo Hoan tat setup.
echo 1) Mo file .env.9router va dien NINEROUTER_URL / NINEROUTER_KEY
echo 2) Chay WEB: run_9router_image_app.bat
echo 3) Chay DESKTOP APP: run_wahu_desktop_app.bat (1 click tu Desktop sau khi tao shortcut)

endlocal
