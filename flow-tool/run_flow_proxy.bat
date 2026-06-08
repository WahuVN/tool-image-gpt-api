@echo off
chcp 65001 >nul
echo === Flow Multi-Account Proxy ===
echo Quan ly acc: http://localhost:8790/accounts
echo Base URL cho tool ve: http://localhost:8790
echo.
cd /d "%~dp0"
python flow_proxy_multi.py
pause
