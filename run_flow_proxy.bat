@echo off
chcp 65001 >nul
echo === Flow Multi-Account Proxy ===
echo Quan ly acc: http://localhost:8790/accounts
echo Base URL cho tool ve: http://localhost:8790
echo.
cd /d "D:\TOOL\TOOL API Flow\flow-tool"
python flow_proxy_multi.py
pause
