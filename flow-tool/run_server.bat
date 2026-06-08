@echo off
cd /d "%~dp0"
echo === Flow Image Server ===
python server.py %*
pause
