@echo off
chcp 65001 >nul
title Login Account Claude Web (OAuth) - OmniRoute
color 0B

echo ================================================================
echo    LOGIN ACCOUNT CLAUDE WEB / PRO (OAuth Senza Chiavi a Consumo)
echo ================================================================
echo.
echo Questa procedura collega il tuo account Claude.ai (Free o Pro).
echo.
echo 1. Si aprira automaticamente il browser per autorizzare OmniRoute.
echo 2. Fai il login con la tua email di Claude.ai e clicca Approva.
echo 3. Copia l'indirizzo URL o il Codice che ti viene mostrato.
echo 4. Incollalo qui sotto e premi INVIO.
echo.
echo Premi un tasto per iniziare...
pause >nul
echo.

cmd /c "omniroute oauth start --provider claude-code"

echo.
echo ================================================================
echo Procedura terminata. Premi un tasto per uscire...
echo ================================================================
pause >nul
exit /b 0
