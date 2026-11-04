@echo off
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

rem ============================================
rem KiCad SVG -> _PROJECT folder / PNG + NC + LaserGRBL TXT
rem Put SVG files next to start.cmd
rem ============================================
set "DPI=508"
set "INVERT=0"
set "MIRROR_X=0"
set "THRESHOLD=128"
rem Raster NC: binary (default) or grayscale; density 10 or 20 in BOTH axes
set "GCODE_MODE=binary"
set "GCODE_LINES_PER_MM=10"
set "GCODE_FEED=1000"
set "GCODE_POWER=1000"
rem ============================================

pushd "%~dp0"
if errorlevel 1 (
    echo ERROR: Cannot open script directory.
    pause
    exit /b 1
)
if not exist "project_output.py" (
    echo ERROR: Missing project_output.py. Download the complete repository archive.
    goto :start_failed
)
if not exist "svg_to_png_batch.py" (
    echo ERROR: Missing svg_to_png_batch.py
    goto :start_failed
)

rem A venv may contain python.exe but point to a removed Python installation.
rem Validate execution and imports, not only the existence of the file.
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -c "import pymupdf; from PIL import Image" >nul 2>nul
    if not errorlevel 1 goto :run
)
if not exist "install.cmd" (
    echo ERROR: Missing install.cmd. Download the complete repository archive.
    goto :start_failed
)
echo Python environment is missing or broken. Repairing automatically...
call "%~dp0install.cmd" /quiet
if errorlevel 1 goto :start_failed

:run
echo ============================================
echo KiCad SVG - PNG + LaserGRBL NC + TXT - v4
echo ============================================
echo Folder: %CD%
echo DPI: %DPI%  INVERT: %INVERT%  MIRROR_X: %MIRROR_X%
echo NC: %GCODE_MODE%  %GCODE_LINES_PER_MM% samples/mm on X and Y  F%GCODE_FEED%  S%GCODE_POWER%
echo.

rem No --folder argument: avoids Windows escaped trailing-slash issue.
".venv\Scripts\python.exe" "svg_to_png_batch.py" --dpi %DPI% --threshold %THRESHOLD% --invert %INVERT% --mirror-x %MIRROR_X% --gcode-mode %GCODE_MODE% --gcode-lines-per-mm %GCODE_LINES_PER_MM% --gcode-feed %GCODE_FEED% --gcode-power %GCODE_POWER%
set "EXIT_CODE=%errorlevel%"
echo.
if exist "LASERGRBL_SETTINGS.txt" (
    echo Opening LASERGRBL_SETTINGS.txt ...
    start "" notepad.exe "%CD%\LASERGRBL_SETTINGS.txt"
)
if "%EXIT_CODE%"=="0" (
    echo DONE. KiCad project folders contain SVG, PNG, NC and TXT files.
) else (
    echo Some SVG conversions failed. See LASERGRBL_SETTINGS.txt.
)
popd
pause
exit /b %EXIT_CODE%

:start_failed
echo Converter could not start. See the error above.
popd
pause
exit /b 1
