@echo off
setlocal
set "PROJECT_DIR=%~dp0"
set "PYTHON_EXE=%PROJECT_DIR%\.venv\Scripts\python.exe"
set "APP_FILE=%PROJECT_DIR%\app.py"

if not exist "%PYTHON_EXE%" (
    echo Python venv not found: %PYTHON_EXE%
    exit /b 1
)

if not exist "%APP_FILE%" (
    echo App file not found: %APP_FILE%
    exit /b 1
)

"%PYTHON_EXE%" "%APP_FILE%"
