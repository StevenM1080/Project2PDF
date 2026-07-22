@echo off
setlocal

cd /d "%~dp0"

set "PYTHONW=%~dp0.venv\Scripts\pythonw.exe"
set "APP=%~dp0run_project2pdf.py"

if not exist "%APP%" (
    echo Project2PDF could not be started because run_project2pdf.py is missing.
    echo.
    pause
    exit /b 1
)

if not exist "%PYTHONW%" (
    echo Project2PDF could not find its Python environment.
    echo Expected: %PYTHONW%
    echo.
    echo Create the environment and install the project first:
    echo   python -m venv .venv
    echo   .venv\Scripts\python.exe -m pip install -e ".[dev]"
    echo.
    pause
    exit /b 1
)

start "Project2PDF" "%PYTHONW%" "%APP%"
exit /b 0
