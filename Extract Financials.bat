@echo off
REM Double-click this file to open the Annual Report Financials Extractor.
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo Python is not installed.
    echo Install it from https://www.python.org/downloads/ and tick "Add Python to PATH",
    echo then double-click this file again.
    pause
    exit /b
)

python -c "import pypdf, pypdfium2" >nul 2>nul
if errorlevel 1 (
    echo First run: installing the required components. This takes a minute...
    python -m pip install --quiet -r requirements.txt
    if errorlevel 1 (
        echo Installation failed. Check your internet connection and try again.
        pause
        exit /b
    )
)

start "" pythonw "%~dp0ar_gui.pyw"
