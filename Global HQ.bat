@echo off
rem Double-click to open Global HQ on Windows.
cd /d "%~dp0"
where py >nul 2>nul && (set PY=py) || (set PY=python)
%PY% --version >nul 2>nul || (echo Global HQ needs Python 3. Opening python.org... & start https://www.python.org/downloads/ & pause & exit /b 1)
if not exist config.json copy config.example.json config.json >nul
%PY% -c "import webview, certifi" 2>nul || %PY% -m pip install --user --quiet pywebview certifi
%PY% -m hq app
if errorlevel 1 pause
