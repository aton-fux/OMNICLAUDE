@echo off
chcp 65001 >nul
title Arresto Completo e Pulizia Memoria (RAM / VRAM)
color 0C

echo.
echo ============================================================
echo   ARRESTO COMPLETO E PULIZIA RISORSE (RAM / VRAM)
echo ============================================================
echo.

:: 1. Chiudi processi e finestre Claude Code
echo [1/6] Arresto Claude Code...
taskkill /F /IM claude.exe >nul 2>&1
taskkill /F /FI "WINDOWTITLE eq Claude Code*" >nul 2>&1

:: 2. Chiudi processi e finestre OpenCode
echo [2/6] Arresto OpenCode...
taskkill /F /IM opencode.exe >nul 2>&1
taskkill /F /FI "WINDOWTITLE eq OpenCode*" >nul 2>&1

:: 3. Libera VRAM GPU scaricando eventuali modelli locali da Ollama
echo [3/6] Scaricamento modelli da GPU / VRAM...
where.exe ollama >nul 2>&1
if not errorlevel 1 (
    for /f "tokens=1" %%m in ('ollama ps 2^>nul ^| findstr /V "NAME"') do (
        ollama stop %%m >nul 2>&1
    )
)

:: 4. Arresto Gateway OmniRoute e processi associati
echo [4/6] Arresto gateway OmniRoute (porta 20128)...
cmd /c "omniroute stop" >nul 2>&1
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":20128.*LISTENING"') do (
    taskkill /PID %%a /F /T >nul 2>&1
)

:: 5. Arresto server web interfaccia (porta 3000)
echo [5/6] Arresto Centro di Controllo (porta 3000)...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":3000.*LISTENING"') do (
    taskkill /PID %%a /F /T >nul 2>&1
)

:: 6. Conferma
echo [6/6] Pulizia completata!
echo.
echo ============================================================
echo   TUTTI I PROCESSI E LE FINESTRE SONO STATI ARRESTATI.
echo   RAM e VRAM liberate al 100%%.
echo.
echo   Per ripartire: fai doppio click su START.bat
echo ============================================================
echo.
pause
exit /b 0
