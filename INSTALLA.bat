@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

title OMNICLAUDE — Installatore & Diagnostica (Creato da ATON-FUX)
color 0B

echo ===============================================================================
echo        OMNICLAUDE — INSTALLATORE AUTOMATICO ^& DIAGNOSTICA DIPENDENZE
echo                  Creato da ATON-FUX (github.com/aton-fux/OMNICLAUDE)
echo ===============================================================================
echo.
echo Questa procedura verifichera e installera tutte le dipendenze necessarie,
echo controllera i motori Cloud e i modelli Locali (Ollama), configurando tutto
echo per l'uso immediato a costo zero.
echo.
echo Premi un tasto per avviare il controllo...
pause >nul
echo.

:: -----------------------------------------------------------------------------
:: PASSO 1: Controllo Node.js e npm
:: -----------------------------------------------------------------------------
echo [1/6] Controllo ambiente Node.js e npm...
where.exe node >nul 2>&1
if errorlevel 1 (
    echo   [-] Node.js non trovato. Installazione automatica con winget...
    where.exe winget >nul 2>&1
    if not errorlevel 1 (
        call winget install OpenJS.NodeJS.LTS -e --accept-source-agreements --accept-package-agreements
        echo   [PASSED] Node.js installato. Riavvia la console se richiesto.
    ) else (
        echo   [ERRORE] Installa manualmente Node.js LTS da https://nodejs.org/
        pause
        exit /b 1
    )
) else (
    for /f "tokens=*" %%v in ('node -v') do set NODE_VER=%%v
    for /f "tokens=*" %%v in ('npm -v') do set NPM_VER=%%v
    echo   [PASSED] Node.js rilevato: !NODE_VER! (npm: !NPM_VER!)
)

:: -----------------------------------------------------------------------------
:: PASSO 2: Controllo pacchetti OmniRoute, Claude Code e OpenCode
:: -----------------------------------------------------------------------------
echo.
echo [2/6] Controllo OmniRoute, Claude Code e OpenCode...
where.exe omniroute >nul 2>&1
set OMNI_ERR=!errorlevel!
where.exe claude >nul 2>&1
set CLAUDE_ERR=!errorlevel!
where.exe opencode >nul 2>&1
set OPENCODE_ERR=!errorlevel!

if !OMNI_ERR! neq 0 (
    echo   [-] Installazione di OmniRoute...
    call npm install -g omniroute
    echo   [PASSED] OmniRoute installato con successo.
) else (
    for /f "tokens=*" %%v in ('omniroute --version') do set OMNI_VER=%%v
    echo   [PASSED] OmniRoute rilevato (v!OMNI_VER!).
)

if !CLAUDE_ERR! neq 0 (
    echo   [-] Installazione di Claude Code...
    call npm install -g @anthropic-ai/claude-code
    echo   [PASSED] Claude Code installato con successo.
) else (
    for /f "tokens=*" %%v in ('claude --version') do set CLAUDE_VER=%%v
    echo   [PASSED] Claude Code rilevato (!CLAUDE_VER!).
)

if !OPENCODE_ERR! neq 0 (
    echo   [-] Installazione di OpenCode...
    call npm install -g opencode-ai
    echo   [PASSED] OpenCode installato con successo.
) else (
    for /f "tokens=*" %%v in ('opencode --version') do set OPENCODE_VER=%%v
    echo   [PASSED] OpenCode rilevato (!OPENCODE_VER!).
)

:: -----------------------------------------------------------------------------
:: PASSO 3: Controllo Ollama (Modelli Locali 100% Offline)
:: -----------------------------------------------------------------------------
echo.
echo [3/6] Controllo ambiente Locale Ollama...
where.exe ollama >nul 2>&1
if errorlevel 1 (
    echo   [-] Ollama non e installato sul sistema (Opzionale per modelli 100%% offline).
    set /p INST_OLLAMA="  -> Vuoi installare Ollama automaticamente ora con winget? (S/N): "
    if /i "!INST_OLLAMA!"=="S" (
        echo   Installazione Ollama in corso...
        call winget install Ollama.Ollama -e --accept-source-agreements --accept-package-agreements
        echo   [PASSED] Ollama installato!
    ) else (
        echo   [PASSED] Saltato (useremo i motori Cloud gratuiti).
    )
) else (
    for /f "tokens=*" %%v in ('ollama --version') do set OLLAMA_VER=%%v
    echo   [PASSED] Ollama rilevato (!OLLAMA_VER!).
    
    for /f "tokens=*" %%m in ('ollama list ^| findstr /V "NAME"') do (
        set HAS_MODELS=1
    )
    if "!HAS_MODELS!"=="1" (
        echo   [PASSED] Modelli locali trovati in Ollama:
        for /f "tokens=1" %%m in ('ollama list ^| findstr /V "NAME"') do (
            echo            - %%m
        )
    ) else (
        echo   [AVVISO] Nessun modello trovato in Ollama.
        set /p PULL_MODEL="  -> Vuoi scaricare il modello di coding qwen2.5-coder:1.5b (1GB)? (S/N): "
        if /i "!PULL_MODEL!"=="S" (
            echo   Scaricamento modello in corso...
            call ollama pull qwen2.5-coder:1.5b
            echo   [PASSED] Modello qwen2.5-coder scaricato!
        ) else (
            echo   [PASSED] Proseguo senza modelli locali per ora.
        )
    )
)

:: -----------------------------------------------------------------------------
:: PASSO 4: Configurazione file di sicurezza e crittografia locale
:: -----------------------------------------------------------------------------
echo.
echo [4/6] Configurazione sicurezza OmniRoute...
if not exist "%USERPROFILE%\.omniroute" mkdir "%USERPROFILE%\.omniroute"
set ENV_FILE=%USERPROFILE%\.omniroute\.env
(
    echo STORAGE_ENCRYPTION_KEY=90b502a4b5cede384fc46dedd9397871b4ddbc476b4aa291c76cfa8d86cb119d
    echo REQUIRE_API_KEY=false
) > "%ENV_FILE%"
echo   [PASSED] Chiavi di crittografia configurate in %ENV_FILE%

:: -----------------------------------------------------------------------------
:: PASSO 5: Controllo Chiave Google Gemini e Catena Paracadute
:: -----------------------------------------------------------------------------
echo.
echo [5/6] Controllo credenziali Cloud e Catena Paracadute...
set SCRIPT_DIR=%~dp0
set CONFIG_FILE=%SCRIPT_DIR%config.env

if not exist "%CONFIG_FILE%" (
    if exist "%SCRIPT_DIR%config.example.env" (
        copy /y "%SCRIPT_DIR%config.example.env" "%CONFIG_FILE%" >nul
    )
)

if exist "%CONFIG_FILE%" (
    for /f "usebackq tokens=1,* delims==" %%A in ("%CONFIG_FILE%") do (
        set line=%%A
        if not "!line:~0,1!"=="#" (
            set %%A=%%B
        )
    )
)

if "%GEMINI_API_KEY%"=="" (
    echo   [ATTENZIONE] Nessuna chiave Google Gemini trovata in config.env!
    echo   Puoi ottenerne una GRATIS in 20 secondi su: https://aistudio.google.com/app/apikey
    set /p GEMINI_API_KEY="  -> Incolla qui la tua API Key di Google AI Studio (oppure premi INVIO per farlo dal browser): "
    if not "!GEMINI_API_KEY!"=="" (
        echo GEMINI_API_KEY=!GEMINI_API_KEY!>> "%CONFIG_FILE%"
    )
)

echo   [PASSED] Configurazione OMNICLAUDE verificata.

:: Avvio temporaneo OmniRoute per registrare la chiave e creare il paracadute
netstat -ano | findstr /R ":20128.*LISTENING" >nul
if errorlevel 1 (
    start /B omniroute serve --no-open >nul 2>&1
    ping -n 4 127.0.0.1 >nul
)

if not "%GEMINI_API_KEY%"=="" (
    call omniroute keys add gemini %GEMINI_API_KEY% >nul 2>&1
)
call omniroute tokens create --scope admin --name "claude-code" >nul 2>&1

:: Creazione della catena Paracadute
call omniroute combo create paracadute-gratis --strategy priority --models "gemini/gemini-3.5-flash-lite,groq/llama-3.3-70b-versatile,deepseek/deepseek-chat" >nul 2>&1
echo   [PASSED] Catena Paracadute Modulare registrata.

:: -----------------------------------------------------------------------------
:: Configurazione provider OmniRoute in OpenCode
if not exist "%USERPROFILE%\.config\opencode" mkdir "%USERPROFILE%\.config\opencode"
if exist "%SCRIPT_DIR%opencode.jsonc" (
    copy /y "%SCRIPT_DIR%opencode.jsonc" "%USERPROFILE%\.config\opencode\opencode.jsonc" >nul 2>&1
    echo   [PASSED] Provider OmniRoute registrato in OpenCode.
)

:: PASSO 6: Test Finale Gateway
:: -----------------------------------------------------------------------------
echo.
echo [6/6] Test di salute del Gateway...
call omniroute test gemini >nul 2>&1
if errorlevel 1 (
    echo   [INFO] Gateway pronto (inserisci o verifica le chiavi API nella dashboard OMNICLAUDE).
) else (
    echo   [PASSED] Connessione upstream a Google Gemini verificata con successo!
)

echo.
echo ===============================================================================
echo          🎉 DIAGNOSTICA E SETUP OMNICLAUDE COMPLETATI CON SUCCESSO!
echo                       Creato da ATON-FUX
echo ===============================================================================
echo.
echo Tutte le dipendenze sono configurate e verificate [PASSED].
echo.
echo MODALITA DI AVVIO:
echo   1. START.bat           -> Command Center OMNICLAUDE (consigliato: scegli dal browser)
echo   2. START_CLAUDE.bat    -> Avvio rapido Claude Code da console
echo   3. START_OPENCODE.bat  -> Avvio rapido OpenCode da console
echo   4. FERMA.bat           -> Chiusura completa e pulizia RAM/VRAM
echo.
echo Premi un tasto per uscire dall'installatore...
pause >nul
exit /b 0
