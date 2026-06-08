@echo off
cd /d "%~dp0"
".venv\Scripts\python.exe" gemini_openai_proxy.py
pause
