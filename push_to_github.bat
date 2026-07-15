@echo off
chcp 65001 >nul
title Push to GitHub
cd /d "%~dp0"

echo ============================================
echo   VideoTranscriber - Commit und Push
echo ============================================
echo.

echo Schritt 1/3: Aenderungen committen...
git add -A
git commit -m "Add EP /streaming/?event= URL support; improve transcribe.bat (error handling, default output to 002_Transkripte)"
echo.

echo Schritt 2/3: Branch in 'main' umbenennen...
git branch -m main
echo.

echo Schritt 3/3: Alles zu GitHub hochladen...
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
echo   Fertig! Branch 'main' ist auf GitHub.
echo.
echo   NOCH EIN MANUELLER SCHRITT auf github.com:
echo   Repo VideoTranscriber - Settings -
echo   General - Default branch - auf 'main'
echo   umstellen. Danach koennen die alten
echo   claude/...-Branches geloescht werden.
echo ============================================
pause
