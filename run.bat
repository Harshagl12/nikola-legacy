@echo off
cd /d "%~dp0"
echo [NIKOLA] Starting system...

REM Kill any stale lock on port 47821
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr ":47821" ^| findstr "LISTEN"') do (
    taskkill /PID %%a /F >nul 2>&1
)

if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" nikola_launcher/launcher.py %*
) else if exist ".venv\Scripts\python.exe" (
    start "" ".venv\Scripts\python.exe" nikola_launcher/launcher.py %*
) else (
    start "" python nikola_launcher/launcher.py %*
)
