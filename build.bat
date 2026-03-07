@echo off
REM Both intermediate files and final output go to TEMP (outside Google Drive)
REM to avoid file-lock errors during the build.
REM
REM After building, find the output here:
REM   %TEMP%\pyinstaller-epub-output\PlainTXT-EPUB Converter\
REM Copy or move that folder wherever you want to distribute it from.

set WORKPATH=%TEMP%\pyinstaller-epub-converter
set DISTPATH=%TEMP%\pyinstaller-epub-output

C:\Users\00dav\anaconda3\python.exe -m PyInstaller converter.spec -y ^
    --workpath "%WORKPATH%" ^
    --distpath "%DISTPATH%"

echo.
echo ============================================================
echo Build complete.
echo Output folder:  %DISTPATH%\PlainTXT-EPUB Converter\
echo ============================================================
pause
