@echo off
setlocal EnableDelayedExpansion
title Basil BACnet Explorer - build Windows .exe
cd /d "%~dp0"
echo.
echo  ============================================================
echo    Basil BACnet Explorer  -  build BasilBACnetExplorer.exe
echo  ============================================================
echo.

rem ---------- find Python 3.8+ (py launcher first, then python on PATH)
set "PY="
where py >nul 2>nul && py -3 -c "import sys; sys.exit(0 if sys.version_info>=(3,8) else 1)" >nul 2>nul && set "PY=py -3"
if not defined PY (
  where python >nul 2>nul && python -c "import sys; sys.exit(0 if sys.version_info>=(3,8) else 1)" >nul 2>nul && set "PY=python"
)
if not defined PY goto :nopython

echo  Using:
%PY% --version
%PY% -c "import tkinter" >nul 2>nul || (
  echo.
  echo  ERROR: this Python has no Tkinter. Re-run the Python installer, choose "Modify"
  echo         and tick "tcl/tk and IDLE".
  goto :fail
)

rem ---------- isolated build environment
if not exist ".build-venv\Scripts\python.exe" (
  echo  Creating build environment...
  %PY% -m venv .build-venv || goto :fail
)
set "VPY=.build-venv\Scripts\python.exe"
echo  Installing PyInstaller (needs internet the first time)...
"%VPY%" -m pip install --disable-pip-version-check -q --upgrade pip
"%VPY%" -m pip install --disable-pip-version-check -q --upgrade pyinstaller psutil || goto :fail

rem ---------- build
echo  Building... (1-3 minutes)
"%VPY%" -m PyInstaller --noconfirm --clean --log-level WARN packaging\BACnetExplorer.spec || goto :fail

rem ---------- extras next to the exe
if not exist "dist\graphics" mkdir "dist\graphics"
copy /y "graphics\README.md" "dist\graphics\README.md" >nul
copy /y "README.md" "dist\README.md" >nul

echo.
echo  ============================================================
echo    DONE
echo      dist\BasilBACnetExplorer.exe    - the application
echo      dist\BasilBACnetSimulator.exe   - test device simulator
echo      dist\graphics\             - drop extra equipment .py files here
echo  ============================================================
echo.
explorer "dist"
goto :end

:nopython
echo  Python 3.8 or newer was not found.
where winget >nul 2>nul && (
  echo.
  choice /c YN /m " Install Python 3.12 now with winget"
  if !errorlevel! equ 1 (
    winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
    echo.
    echo  Python installed. Close this window and run build_exe.bat again.
    goto :end
  )
)
echo.
echo  Install Python from https://www.python.org/downloads/windows/
echo    - tick "Add python.exe to PATH" and keep "tcl/tk" selected
echo    - for a build that also runs on Windows 7 use Python 3.8 (32-bit = runs everywhere)
goto :fail

:fail
echo.
echo  BUILD FAILED - see the messages above.
:end
echo.
pause
