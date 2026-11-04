@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"
if errorlevel 1 goto :failed_folder
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "VENV=%~dp0.venv"
set "VENV_PY=%VENV%\Scripts\python.exe"
set "INSTALLER=%TEMP%\python-3.14.10-amd64.exe"
set "NO_PAUSE=0"
if /i "%~1"=="/quiet" set "NO_PAUSE=1"

echo ============================================
echo     KiCad SVG to PNG - Python installer
echo ============================================
echo.

call :check_venv
if not errorlevel 1 (
    echo Existing Python environment is healthy.
    goto :packages
)

if exist "%VENV%" (
    echo Old Python environment is broken. Recreating it...
    rmdir /s /q "%VENV%"
    if exist "%VENV%" goto :failed_venv
)

call :create_venv
if not errorlevel 1 goto :packages

echo No usable Python found. Trying an automatic installation...
where winget >nul 2>nul
if errorlevel 1 goto :direct_install

echo Installing Python 3.14 using winget...
winget install --id Python.Python.3.14 --exact --source winget --scope user --accept-source-agreements --accept-package-agreements --silent
call :create_venv
if not errorlevel 1 goto :packages

:direct_install
echo.
echo Trying official Python.org 64-bit installer...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest 'https://www.python.org/ftp/python/3.14.10/python-3.14.10-amd64.exe' -OutFile '%INSTALLER%'; $s = Get-AuthenticodeSignature '%INSTALLER%'; if ($s.Status -ne 'Valid') { throw 'Installer signature is not valid' }"
if errorlevel 1 goto :failed_python
start /wait "" "%INSTALLER%" /quiet InstallAllUsers=0 PrependPath=1 Include_pip=1 Include_launcher=1 Include_test=0
if errorlevel 1 goto :failed_python
call :create_venv
if errorlevel 1 goto :failed_python

:packages
if not exist "%~dp0requirements.txt" goto :failed_requirements
echo.
echo Checking required Python libraries...
"%VENV_PY%" -m pip --version >nul 2>nul
if errorlevel 1 (
    "%VENV_PY%" -m ensurepip --upgrade
    if errorlevel 1 goto :failed_packages
)
"%VENV_PY%" -m pip install --disable-pip-version-check -r "%~dp0requirements.txt"
if errorlevel 1 goto :failed_packages
"%VENV_PY%" -c "import pymupdf; from PIL import Image; print('SUCCESS: PyMuPDF and Pillow are available')"
if errorlevel 1 goto :failed_packages

echo.
echo ============================================
echo INSTALLATION COMPLETE. Run start.cmd.
echo ============================================
goto :success

:check_venv
if not exist "%VENV_PY%" exit /b 1
"%VENV_PY%" -c "import sys; assert sys.prefix != sys.base_prefix and sys.version_info >= (3, 10)" >nul 2>nul
exit /b %errorlevel%

:create_venv
call :try_python py -3.14
if not errorlevel 1 exit /b 0
call :try_python py -3.13
if not errorlevel 1 exit /b 0
call :try_python py -3.12
if not errorlevel 1 exit /b 0
call :try_python py -3
if not errorlevel 1 exit /b 0
call :try_python python
if not errorlevel 1 exit /b 0
if exist "%LocalAppData%\Programs\Python\Python314\python.exe" (
    call :try_python "%LocalAppData%\Programs\Python\Python314\python.exe"
    if not errorlevel 1 exit /b 0
)
if exist "%LocalAppData%\Programs\Python\Python313\python.exe" (
    call :try_python "%LocalAppData%\Programs\Python\Python313\python.exe"
    if not errorlevel 1 exit /b 0
)
if exist "%LocalAppData%\Programs\Python\Python312\python.exe" (
    call :try_python "%LocalAppData%\Programs\Python\Python312\python.exe"
    if not errorlevel 1 exit /b 0
)
exit /b 1

:try_python
if exist "%VENV%" (
    rmdir /s /q "%VENV%" >nul 2>nul
    if exist "%VENV%" exit /b 1
)
%* -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
if errorlevel 1 exit /b 1
%* -m venv "%VENV%" >nul 2>nul
if errorlevel 1 exit /b 1
call :check_venv
exit /b %errorlevel%

:failed_folder
echo ERROR: Cannot open the installer folder.
goto :failed

:failed_venv
echo ERROR: Cannot remove the broken .venv folder.
echo Close all converter windows and retry.
goto :failed

:failed_requirements
echo ERROR: requirements.txt is missing. Download the complete repository archive.
goto :failed

:failed_packages
echo ERROR: Python runs, but the required libraries could not be installed.
echo Check the network, proxy and the pip error above.
goto :failed

:failed_python
echo ERROR: Python could not be installed or detected.
echo Install a supported Python 3 version from https://www.python.org/downloads/windows/
goto :failed

:failed
echo.
echo INSTALLATION FAILED.
if "%NO_PAUSE%"=="0" pause
exit /b 1

:success
if "%NO_PAUSE%"=="0" pause
exit /b 0
