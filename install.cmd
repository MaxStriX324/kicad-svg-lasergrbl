@echo off
setlocal EnableExtensions
cd /d "%~dp0"
chcp 65001 >nul
set "PYTHONIOENCODING=utf-8"
set "INSTALLER=%TEMP%\python-3.14.8-amd64.exe"

echo ============================================
echo      Python + PNG libraries installer
 echo ============================================
echo.
if exist "%~dp0.venv\Scripts\python.exe" (
    echo Local Python environment already exists. Updating libraries...
    goto :packages
)

call :try_create_venv
if not errorlevel 1 goto :packages

echo Python 3 is not installed or not detected.
where winget >nul 2>nul
if errorlevel 1 goto :direct_install

echo Installing Python 3.14 with winget...
winget install --id Python.Python.3.14 --exact --source winget --scope user --accept-source-agreements --accept-package-agreements --silent
call :try_create_venv
if not errorlevel 1 goto :packages

:direct_install
echo.
echo Trying official Python.org 64-bit installer...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest 'https://www.python.org/ftp/python/3.14.8/python-3.14.8-amd64.exe' -OutFile '%INSTALLER%'; $s = Get-AuthenticodeSignature '%INSTALLER%'; if ($s.Status -ne 'Valid') { throw 'Installer signature is not valid' }"
if errorlevel 1 goto :failed
start /wait "" "%INSTALLER%" /quiet InstallAllUsers=0 PrependPath=1 Include_pip=1 Include_launcher=1 Include_test=0
if errorlevel 1 goto :failed
call :try_create_venv
if errorlevel 1 goto :failed

:packages
echo.
echo Installing PyMuPDF and Pillow into a local virtual environment...
"%~dp0.venv\Scripts\python.exe" -m pip install --disable-pip-version-check --upgrade pip
if errorlevel 1 goto :failed
"%~dp0.venv\Scripts\python.exe" -m pip install --disable-pip-version-check --upgrade pymupdf Pillow
if errorlevel 1 goto :failed
"%~dp0.venv\Scripts\python.exe" -c "import pymupdf; from PIL import Image; print('SUCCESS: PyMuPDF and Pillow imported')"
if errorlevel 1 goto :failed

echo.
echo ============================================
echo INSTALLATION COMPLETE. Use start.cmd.
echo ============================================
pause
exit /b 0

:try_create_venv
if exist "%LocalAppData%\Programs\Python\Python314\python.exe" (
    "%LocalAppData%\Programs\Python\Python314\python.exe" -m venv "%~dp0.venv" >nul 2>nul
    if not errorlevel 1 exit /b 0
)
py -3 -m venv "%~dp0.venv" >nul 2>nul
if not errorlevel 1 exit /b 0
python -m venv "%~dp0.venv" >nul 2>nul
if not errorlevel 1 exit /b 0
exit /b 1

:failed
echo.
echo INSTALLATION FAILED. Check internet connection / Python installation.
echo Try installing Python 3.14 from https://www.python.org/downloads/windows/
echo Then run install.cmd again.
pause
exit /b 1