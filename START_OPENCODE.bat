@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
title OMNICLAUDE — OpenCode Terminal (by ATON-FUX)
color 0B

echo.
echo ============================================================
echo   OMNICLAUDE — AVVIO OPENCODE (Creato da ATON-FUX)
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

:: 1. Avvia OmniRoute (gateway AI)
netstat -ano | findstr /R ":%OMNIROUTE_PORT%.*LISTENING" >nul
if errorlevel 1 (
    echo [1/3] Avvio gateway OmniRoute...
    start "OmniRoute" /MIN cmd /c "omniroute serve --no-open"
    ping -n 5 127.0.0.1 >nul
    echo [1/3] Gateway avviato.
) else (
    echo [1/3] Gateway OmniRoute: gia attivo.
)

:: 2. Avvia server interfaccia web (porta 3000)
netstat -ano | findstr /R ":3000.*LISTENING" >nul
if errorlevel 1 (
    echo [2/3] Avvio interfaccia web OMNICLAUDE...
    start "" pythonw "%SCRIPT_DIR%server.py"
    ping -n 3 127.0.0.1 >nul
    echo [2/3] Interfaccia web avviata.
) else (
    echo [2/3] Interfaccia web: gia attiva.
)

:: 3. Apri il pannello nel browser
echo [3/3] Apertura pannello nel browser...
start http://localhost:3000

:: Imposta variabili per OpenCode (supporta endpoint Anthropic e OpenAI)
set ANTHROPIC_BASE_URL=http://localhost:%OMNIROUTE_PORT%
set ANTHROPIC_AUTH_TOKEN=%OMNIROUTE_TOKEN%
set ANTHROPIC_API_KEY=%OMNIROUTE_TOKEN%
set OPENAI_BASE_URL=http://localhost:%OMNIROUTE_PORT%/v1
set OPENAI_API_KEY=%OMNIROUTE_TOKEN%

echo.
echo ============================================================
echo   OPENCODE PRONTO!
echo.
echo   - Il pannello OMNICLAUDE e aperto (http://localhost:3000)
echo   - Motore configurato: omniroute/%DEFAULT_MODEL%
echo.
echo   Avvio sessione interattiva OpenCode...
echo ============================================================
echo.

call opencode --model omniroute/%DEFAULT_MODEL% %*

echo.
echo   OpenCode terminato. Premi un tasto per chiudere.
pause >nul
