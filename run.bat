@echo off
REM Run TXT to EPUB Converter

set PYTHON=
if exist "%USERPROFILE%\anaconda3\python.exe" set PYTHON=%USERPROFILE%\anaconda3\python.exe
if exist "%USERPROFILE%\miniconda3\python.exe" set PYTHON=%USERPROFILE%\miniconda3\python.exe
if "%PYTHON%"=="" for /f "tokens=*" %%i in ('where python 2^>nul') do set PYTHON=%%i

if "%PYTHON%"=="" (
    echo Python not found. Please run install.bat first.
    pause
    exit /b 1
)

"%PYTHON%" "%~dp0converter.py"
