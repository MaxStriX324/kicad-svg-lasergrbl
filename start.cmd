@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONIOENCODING=utf-8"

rem ============================================
rem KiCad SVG -> PNG + lasergrbl TXT instructions
rem SVG files must be next to this start.cmd
rem ============================================
set "DPI=508"
set "INVERT=0"
set "MIRROR_X=0"
set "THRESHOLD=128"
rem ============================================

pushd "%~dp0"
if errorlevel 1 (
    echo ERROR: Cannot open script directory.
    pause
    exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
    echo ERROR: Python libraries are not installed. Run install.cmd first.
    popd
    pause
    exit /b 1
)
if not exist "svg_to_png_batch.py" (
    echo ERROR: Missing svg_to_png_batch.py
    popd
    pause
    exit /b 1
)

echo ============================================
echo KiCad SVG - PNG + LaserGRBL TXT - v3
echo ============================================
echo Folder: %CD%
echo DPI: %DPI%  INVERT: %INVERT%  MIRROR_X: %MIRROR_X%
echo.

rem No --folder argument: avoids Windows escaped trailing-slash issue.
".venv\Scripts\python.exe" "svg_to_png_batch.py" --dpi %DPI% --threshold %THRESHOLD% --invert %INVERT% --mirror-x %MIRROR_X%
set "EXIT_CODE=%errorlevel%"
echo.
if exist "LASERGRBL_SETTINGS.txt" (
    echo Opening LASERGRBL_SETTINGS.txt ...
    start "" notepad.exe "%CD%\LASERGRBL_SETTINGS.txt"
)
if "%EXIT_CODE%"=="0" (
    echo DONE. PNG and TXT files are in this folder.
) else (
    echo Some SVG conversions failed. See TXT report.
)
popd
pause
exit /b %EXIT_CODE%