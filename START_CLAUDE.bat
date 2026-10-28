@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
title OMNICLAUDE — Claude Code Terminal (by ATON-FUX)
color 0A

echo.
echo ============================================================
echo   OMNICLAUDE — AVVIO CLAUDE CODE (Creato da ATON-FUX)
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

:: 1. Avvia OmniRoute se non attivo
netstat -ano | findstr /R ":%OMNIROUTE_PORT%.*LISTENING" >nul
if errorlevel 1 (
    echo [1/2] Avvio gateway OmniRoute...
    start "OmniRoute" /MIN cmd /c "omniroute serve --no-open"
    ping -n 4 127.0.0.1 >nul
)

:: 2. Avvia server interfaccia web locale se non attivo
netstat -ano | findstr /R ":3000.*LISTENING" >nul
if errorlevel 1 (
    start "" pythonw "%SCRIPT_DIR%server.py"
    ping -n 2 127.0.0.1 >nul
)

:: Imposta variabili per Claude Code
set ANTHROPIC_BASE_URL=http://localhost:%OMNIROUTE_PORT%
set ANTHROPIC_AUTH_TOKEN=%OMNIROUTE_TOKEN%
set ANTHROPIC_API_KEY=%OMNIROUTE_TOKEN%
set CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1

echo Modello attivo: %DEFAULT_MODEL%
echo Gateway:        %ANTHROPIC_BASE_URL%
echo.
echo ============================================================
echo   SESSIONE CLAUDE CODE PRONTA - Scrivi il tuo prompt qui sotto
echo ============================================================
echo.

call claude --model %DEFAULT_MODEL% %*

echo.
echo   Sessione Claude Code terminata. Premi un tasto per chiudere.
pause >nul
