@echo off
setlocal EnableExtensions EnableDelayedExpansion

rem Repo root: scripts\windows -> ../..
cd /d "%~dp0..\.."
if errorlevel 1 (
  echo Failed to change directory to repo root.
  exit /b 1
)

set "REPO_ROOT=%CD%"
set "HOST=0.0.0.0"
set "PORT=8080"
if defined EASYID_WEB_HOST set "HOST=%EASYID_WEB_HOST%"
if defined EASYID_WEB_PORT set "PORT=%EASYID_WEB_PORT%"

if not exist "%REPO_ROOT%\logs" mkdir "%REPO_ROOT%\logs"

for /f %%I in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd"') do set "LOGDATE=%%I"
if not defined LOGDATE set "LOGDATE=unknown"
set "LOGFILE=%REPO_ROOT%\logs\web-%LOGDATE%.log"

call :resolve_python
if errorlevel 1 (
  echo [%DATE% %TIME%] ERROR: Python not found. Create .venv or install Python and add to PATH.>> "%LOGFILE%"
  echo Python not found. Create .venv or install Python and add to PATH.
  exit /b 1
)

echo [%DATE% %TIME%] Repo=%REPO_ROOT%>> "%LOGFILE%"
echo [%DATE% %TIME%] Python=%PYTHON_EXE%>> "%LOGFILE%"
echo [%DATE% %TIME%] Starting EasyID calibration web on %HOST%:%PORT%>> "%LOGFILE%"

"%PYTHON_EXE%" "%REPO_ROOT%\run_web.py" --host "%HOST%" --port %PORT% >> "%LOGFILE%" 2>&1
set "EXITCODE=%ERRORLEVEL%"
echo [%DATE% %TIME%] Process exited with code %EXITCODE%>> "%LOGFILE%"
exit /b %EXITCODE%

:resolve_python
set "PYTHON_EXE="
if exist "%REPO_ROOT%\.venv\Scripts\python.exe" (
  set "PYTHON_EXE=%REPO_ROOT%\.venv\Scripts\python.exe"
  exit /b 0
)
where py >nul 2>&1
if not errorlevel 1 (
  for /f "delims=" %%P in ('py -3 -c "import sys; print(sys.executable)" 2^>nul') do set "PYTHON_EXE=%%P"
  if defined PYTHON_EXE exit /b 0
)
where python >nul 2>&1
if not errorlevel 1 (
  for /f "delims=" %%P in ('where python') do (
    set "PYTHON_EXE=%%P"
    goto :python_ok
  )
)
exit /b 1

:python_ok
exit /b 0
