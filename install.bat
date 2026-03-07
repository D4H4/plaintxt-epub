@echo off
echo ============================================
echo  PlainTXT-EPUB Converter - Installer
echo ============================================
echo.

REM Try to find Python (Anaconda first, then system Python)
set PYTHON=
if exist "%USERPROFILE%\anaconda3\python.exe" set PYTHON=%USERPROFILE%\anaconda3\python.exe
if exist "%USERPROFILE%\miniconda3\python.exe" set PYTHON=%USERPROFILE%\miniconda3\python.exe
if "%PYTHON%"=="" for /f "tokens=*" %%i in ('where python 2^>nul') do set PYTHON=%%i

if "%PYTHON%"=="" (
    echo ERROR: Python not found.
    echo Please install Python from https://www.python.org/downloads/
    echo or Anaconda from https://www.anaconda.com/
    pause
    exit /b 1
)

echo Found Python: %PYTHON%
echo.
echo Installing required packages...
echo.

"%PYTHON%" -m pip install ebooklib Pillow tkinterdnd2
if %ERRORLEVEL% neq 0 (
    echo.
    echo WARNING: Some packages may not have installed correctly.
    echo You can still use the app - only ebooklib is strictly required.
)

echo.
echo ============================================
echo  Installation complete!
echo  Run the app with: run.bat
echo ============================================
echo.
pause
