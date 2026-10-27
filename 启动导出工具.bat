@echo off
setlocal
cd /d "%~dp0"

rem ---------- Locate Python ----------
set "PY="
where python >nul 2>nul && set "PY=python"
if not defined PY ( where py >nul 2>nul && set "PY=py -3" )
if not defined PY (
    echo [ERROR] Python 3 not found.
    echo         Please install Python 3.8+ from https://www.python.org/downloads/
    echo         IMPORTANT: tick "Add python.exe to PATH" during install, then retry.
    pause
    exit /b 1
)

rem ---------- Install dependencies on first run ----------
%PY% -c "import requests, openpyxl" >nul 2>nul
if errorlevel 1 (
    echo [INFO] First run: installing dependencies, please wait...
    %PY% -m pip install -r "%~dp0requirements.txt"
    if errorlevel 1 (
        echo [ERROR] Failed to install dependencies. Check your network and retry.
        pause
        exit /b 1
    )
)

rem ---------- Launch ----------
cd /d "%~dp0程序"
start "" http://127.0.0.1:8765/
%PY% app.py

pause
endlocal
