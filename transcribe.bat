@echo off
chcp 65001 >nul
title EP Video Transcriber

echo ============================================
echo   EP Video Transcriber
echo ============================================
echo.

:: URL input
set /p "URL=Paste the EP video URL: "
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

:: Output file
echo.
set /p "OUTFILE=Output filename (e.g. transcript.%FMT%) [press Enter for screen output]: "
set "OUT_FLAG="
if not "%OUTFILE%"=="" set "OUT_FLAG=-o "%OUTFILE%""

:: Build and run command
echo.
echo ============================================
echo Starting transcription...
echo ============================================
echo.

python -m video_transcriber "%URL%" --format %FMT% --model %MODEL% --clean %OUT_FLAG%

echo.
echo ============================================
echo Done!
echo ============================================
pause
