@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
title OMNICLAUDE - AI Command Center (Creato da ATON-FUX)
color 0A

echo.
echo ============================================================
echo   OMNICLAUDE — AI TERMINAL COMMAND CENTER
echo   Creato da ATON-FUX (https://github.com/aton-fux/OMNICLAUDE)
echo ============================================================
echo.

set SCRIPT_DIR=%~dp0
set CONFIG_FILE=%SCRIPT_DIR%config.env

:: Carica config.env
if exist "%CONFIG_FILE%" (
    for /f "usebackq tokens=1,* delims==" %%A in ("%CONFIG_FILE%") do (
        set line=%%A
        if not "!line:~0,1!"=="#" ( set %%A=%%B )
    )
)

if "%DEFAULT_MODEL%"=="" set DEFAULT_MODEL=gemini/gemini-3.5-flash-lite
if "%OMNIROUTE_PORT%"=="" set OMNIROUTE_PORT=20128
if "%OMNIROUTE_TOKEN%"=="" set OMNIROUTE_TOKEN=oma_live_omniclaude_local_token

:: 1. Avvia OmniRoute in background se non attivo
netstat -ano | findstr /R ":%OMNIROUTE_PORT%.*LISTENING" >nul
if errorlevel 1 (
    echo [1/2] Avvio gateway OmniRoute...
    start "OmniRoute" /MIN cmd /c "omniroute serve --no-open"
    timeout /t 1 >nul
    echo [1/2] Gateway avviato.
) else (
    echo [1/2] Gateway OmniRoute gia attivo.
)

:: 2. Avvia server interfaccia web locale (porta 3000)
netstat -ano | findstr /R ":3000.*LISTENING" >nul
if errorlevel 1 (
    echo [2/2] Avvio interfaccia web OMNICLAUDE...
    start "" pythonw "%SCRIPT_DIR%server.py"
    timeout /t 1 >nul
    echo [2/2] Interfaccia web avviata.
) else (
    echo [2/2] Interfaccia web OMNICLAUDE gia attiva.
)

:: 3. Apri browser
echo.
echo Apertura OMNICLAUDE nel browser...
start http://localhost:3000

echo.
echo ============================================================
echo   OMNICLAUDE AVVIATO CON SUCCESSO!
echo.
echo   Il Command Center e aperto nel tuo browser:
echo   -^> http://localhost:3000
echo.
echo   Dal browser puoi scegliere il motore AI e avviare:
echo   - [APRI CLAUDE CODE]
echo   - [APRI OPENCODE]
echo.
echo   Questa finestra informativa si chiudera tra 2 secondi...
echo ============================================================
echo.
timeout /t 2 >nul
exit /b 0
