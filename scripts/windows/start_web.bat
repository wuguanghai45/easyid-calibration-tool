@echo off
setlocal EnableExtensions

rem Repo root: scripts\windows -> ../..
cd /d "%~dp0..\.."
if errorlevel 1 (
  echo Failed to change directory to repo root.
  exit /b 1
)

set "HOST=0.0.0.0"
set "PORT=8080"
if defined EASYID_WEB_HOST set "HOST=%EASYID_WEB_HOST%"
if defined EASYID_WEB_PORT set "PORT=%EASYID_WEB_PORT%"

set "PYTHON_EXE="
if exist "%CD%\.venv\Scripts\python.exe" (
  set "PYTHON_EXE=%CD%\.venv\Scripts\python.exe"
) else (
  where python >nul 2>&1
  if errorlevel 1 (
    echo Python not found. Create .venv or add python to PATH.
    exit /b 1
  )
  set "PYTHON_EXE=python"
)

if not exist "%CD%\logs" mkdir "%CD%\logs"

for /f %%I in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd"') do set "LOGDATE=%%I"
set "LOGFILE=%CD%\logs\web-%LOGDATE%.log"

echo [%DATE% %TIME%] Starting EasyID calibration web on %HOST%:%PORT%>> "%LOGFILE%"
"%PYTHON_EXE%" run_web.py --host "%HOST%" --port %PORT% >> "%LOGFILE%" 2>&1
set "EXITCODE=%ERRORLEVEL%"
echo [%DATE% %TIME%] Process exited with code %EXITCODE%>> "%LOGFILE%"
exit /b %EXITCODE%
