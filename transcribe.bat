@echo off
chcp 65001 >nul
title EP Video Transcriber

echo ============================================
echo   EP Video Transcriber
echo ============================================
echo.

:: URL input
set /p "URL=Paste the video URL (EP, YouTube, Vimeo, ...): "
if "%URL%"=="" (
    echo No URL provided. Exiting.
    pause
    exit /b 1
)

:: Output format
echo.
echo Output format:
echo   1 = txt  (plain text)
echo   2 = srt  (subtitles)
echo   3 = vtt  (web subtitles)
echo   4 = md   (Markdown)
echo   5 = docx (Word document)
set /p "FMT_CHOICE=Choose format [1]: "
if "%FMT_CHOICE%"=="" set "FMT_CHOICE=1"
if "%FMT_CHOICE%"=="1" set "FMT=txt"
if "%FMT_CHOICE%"=="2" set "FMT=srt"
if "%FMT_CHOICE%"=="3" set "FMT=vtt"
if "%FMT_CHOICE%"=="4" set "FMT=md"
if "%FMT_CHOICE%"=="5" set "FMT=docx"

:: Model size
echo.
echo Whisper model (bigger = slower but more accurate):
echo   1 = tiny    (fastest)
echo   2 = base    (default)
echo   3 = small
echo   4 = medium
echo   5 = large-v3 (best quality)
set /p "MODEL_CHOICE=Choose model [2]: "
if "%MODEL_CHOICE%"=="" set "MODEL_CHOICE=2"
if "%MODEL_CHOICE%"=="1" set "MODEL=tiny"
if "%MODEL_CHOICE%"=="2" set "MODEL=base"
if "%MODEL_CHOICE%"=="3" set "MODEL=small"
if "%MODEL_CHOICE%"=="4" set "MODEL=medium"
if "%MODEL_CHOICE%"=="5" set "MODEL=large-v3"

:: Audio track (only relevant for EP videos)
echo.
echo Audio track (nur fuer EP-Videos relevant):
echo   1 = Originalton / Floor (empfohlen)
echo   2 = Dolmetscher Deutsch
echo   3 = Dolmetscher Englisch
echo   4 = Standard (Sprache der URL)
set /p "TRACK_CHOICE=Choose audio track [1]: "
if "%TRACK_CHOICE%"=="" set "TRACK_CHOICE=1"
set "TRACK_FLAG=--audio-track or"
if "%TRACK_CHOICE%"=="2" set "TRACK_FLAG=--audio-track de"
if "%TRACK_CHOICE%"=="3" set "TRACK_FLAG=--audio-track en"
if "%TRACK_CHOICE%"=="4" set "TRACK_FLAG="

:: Output file -- saved to the central OneDrive transcript folder.
:: Falls back to the "Transkripte" subfolder next to this script if
:: the OneDrive folder is not available on this machine.
set "ONEDRIVE_DIR=%USERPROFILE%\OneDrive - Dr. Andreas Tinhofer"
if exist "%ONEDRIVE_DIR%" (
    set "OUTDIR=%ONEDRIVE_DIR%\002_Transkripte"
) else (
    set "OUTDIR=%~dp0Transkripte"
)
if not exist "%OUTDIR%" mkdir "%OUTDIR%"

:: Timestamp for automatic filenames (locale-independent via PowerShell)
for /f "delims=" %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd_HHmmss"') do set "STAMP=%%i"

echo.
set /p "OUTNAME=Output filename (press Enter for an automatic name): "

if "%OUTNAME%"=="" (
    set "OUTFILE=%OUTDIR%\transkript_%STAMP%.%FMT%"
) else (
    rem Endung .%FMT% anhaengen, falls der Name nicht schon darauf endet
    rem (robust auch bei Punkten im Namen, z.B. "Webinar_9.7.2026")
    for /f "delims=" %%i in ('powershell -NoProfile -Command "$n='%OUTNAME%'; if($n.ToLower().EndsWith('.%FMT%')){$n}else{$n+'.%FMT%'}"') do set "OUTFILE=%OUTDIR%\%%i"
)

set "OUT_FLAG=-o "%OUTFILE%""

echo.
echo Saving transcript to:
echo   %OUTFILE%

:: Build and run command
echo.
echo ============================================
echo Starting transcription...
echo ============================================
echo.

python -m video_transcriber "%URL%" --format %FMT% --model %MODEL% --clean %TRACK_FLAG% %OUT_FLAG%
set "RC=%ERRORLEVEL%"

echo.
if not "%RC%"=="0" (
    echo ============================================
    echo   ERROR: Transcription failed ^(exit code %RC%^).
    echo   See the error message above for details.
    echo   No transcript was written.
    echo ============================================
    pause
    exit /b %RC%
)

echo ============================================
echo Done! Transcript saved to:
echo   %OUTFILE%
echo ^(If the file already existed, a numbered
echo  variant like _2 was used instead.^)
echo ============================================
pause
