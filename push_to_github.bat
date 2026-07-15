@echo off
chcp 65001 >nul
title Push to GitHub
cd /d "%~dp0"

echo ============================================
echo   VideoTranscriber - Commit und Push
echo ============================================
echo.

set /p "MSG=Kurze Beschreibung der Aenderungen (Enter fuer Standardtext): "
if "%MSG%"=="" set "MSG=Update project files"

echo Schritt 1/2: Aenderungen committen...
git add -A
git commit -m "%MSG%"
echo.

echo Schritt 2/2: Alles zu GitHub hochladen...
git push -u origin main
if errorlevel 1 (
    echo.
    echo ============================================
    echo   FEHLER beim Push - siehe Meldung oben.
    echo   Haeufigste Ursache: fehlende GitHub-
    echo   Anmeldung. Dann einmal anmelden und
    echo   diese Datei erneut ausfuehren.
    echo ============================================
    pause
    exit /b 1
)

echo.
echo ============================================
echo   Fertig! Aenderungen sind auf GitHub.
echo ============================================
pause
