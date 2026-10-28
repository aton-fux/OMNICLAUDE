<div align="center">
  <img src="./assets/logo.png" width="124" height="124" alt="OMNICLAUDE Official Logo" />
</div>

# 📘 Guida Ufficiale: OMNICLAUDE (Free) & OMNICLAUDE INFINITY
**Creato da ATON-FUX** · Repository Ufficiale: [https://github.com/aton-fux/OMNICLAUDE](https://github.com/aton-fux/OMNICLAUDE)

Benvenuto in **OMNICLAUDE**, il centro di controllo AI ideato da **ATON-FUX** per utilizzare **Claude Code** e **OpenCode** collegati a **motori AI Cloud gratuiti, Open Source, modelli Locali Ollama e al tuo account web Claude.ai**, con **Paracadute Modulare** anti-interruzione e scelta del tema **Dark Cyber / Light Pro**.

---

## 🗂️ I File nella Cartella

| File | Tipo | A cosa serve |
|---|---|---|
| **`START.bat`** | 🟢 Command Center | **Avvia i servizi e apre il browser (`http://localhost:3000`).** Dal browser scegli il motore e avvii Claude Code o OpenCode! |
| **`START_CLAUDE.bat`** | 🚀 Claude Code Diretto | Apre direttamente la finestra del terminale di Claude Code. |
| **`START_OPENCODE.bat`** | ⚡ OpenCode Diretto | Apre direttamente la TUI a schermo intero di OpenCode. |
| **`FERMA.bat`** | 🔴 Chiusura Totale | **Arresta e killa TUTTO:** Claude Code, OpenCode, finestre console, gateway OmniRoute, server web e libera al 100% la memoria RAM e VRAM della GPU. |
| **`LOGIN_CLAUDE.bat`** | 🌐 Accesso Web Claude | Collega il tuo account Claude.ai tramite OAuth del browser senza spendere in API a consumo. |
| **`INSTALLA.bat`** | ⚙️ Setup & Diagnostica | Si usa al primo setup o su un nuovo PC per installare Node, Claude Code, OpenCode e OmniRoute in 1 clic. |

---

## 🎯 Come Funziona la Nuova Pagina Iniziale

1. Fai doppio click su **`START.bat`**.
2. Si aprirà **OMNICLAUDE** nel browser (`http://localhost:3000`).
3. In alto a destra puoi scegliere in qualsiasi momento lo stile **`🖤 DARK CYBER`** oppure **`🤍 LIGHT PRO`**.
4. Nella **Pagina Iniziale**, subito sotto al box **Pronto per Programmare**, trovi tutte le card interattive di:
   - **☁️ Motori Cloud Gratuiti** (Paracadute Multi-Motore, Google Gemini Flash, Meta Llama 3.3 70B, DeepSeek V3, DeepSeek R1, Claude 3.5 Sonnet OAuth).
   - **🖥️ Motori Locali su questo PC (Ollama)** (tutti i modelli scaricati sulla tua macchina, 100% offline).
5. Clicca sul motore che vuoi attivare e poi premi **`🚀 APRI CLAUDE CODE`** oppure **`⚡ APRI OPENCODE`**.

---

## 🛡️ Il Paracadute di Riserva Configurabile & Modulare

Nella sezione **`🛡️ Paracadute Riserva`** del pannello sinistro puoi costruire su misura la tua catena di sicurezza:
- **Ordine Personalizzato:** sposta i motori in su (**⬆️**) o in giù (**⬇️**) per decidere chi parte per primo e chi subentra in caso di fine crediti.
- **Aggiunta Modulare dall'App:** aggiungi nella catena sia motori Cloud sia i tuoi modelli Locali **Ollama** (così se cade anche internet o finiscono tutti i crediti cloud, il codice continua sul tuo PC locale!).
- **Strategia Gateway:** scegli tra `Priority` (cascata sequenziale), `Round-Robin` (rotazione equa) o `Least-Used` (minor carico).

---

## ⚡ Gemini Multi-Key Hub & Quota Tracker (Zero Rate-Limit · OMNICLAUDE INFINITY)

Google Gemini offre ben **1.000.000 di token gratuiti al giorno** per ciascun account Google AI Studio, rendendolo il motore d'elezione per Claude Code e OpenCode. Tuttavia, in sessioni di refactoring o programmazione intensiva, si rischia di raggiungere il rate limit (15 richieste al minuto o quota giornaliera).

**OMNICLAUDE include una soluzione chirurgica:**
1. **Pannello Dedicato `⚡ Gemini Multi-Key & Quota`:** accessibile dal menu a sinistra o dal banner neon in Home.
2. **Multi-Account Pool:** puoi registrare account Google AI Studio illimitati con licenza **OMNICLAUDE INFINITY (14,99€ Una Tantum)**, ciascuno con il proprio nome personalizzato (es. *Personale*, *Lavoro*, *Dev*). *(La versione Community gratuita consente 1 chiave)*.
3. **Monitoraggio Quota Live:** una barra dinamica colorata mostra in tempo reale i token utilizzati nella giornata rispetto alla soglia di 1 milione.
4. **Auto-Failover Istantaneo (Zero Interruzioni):** quando la chiave attiva riceve un errore di limite (HTTP 429 / Quota Esaurita), il monitor background di OMNICLAUDE commuta all'istante sulla chiave standby successiva aggiornando il gateway. Claude Code o OpenCode continuano a scrivere codice senza crashare o perdere la sessione!
5. **Cooldown e Ripristino Intelligente:** la chiave esaurita entra in stato temporaneo di raffreddamento e ritorna automaticamente disponibile appena la quota o il rate limit si sblocca.
6. **Attivazione Istantanea:** inserisci il codice licenza ricevuto dopo l'acquisto su Gumroad o fornito da **ATON-FUX** cliccando su *"🔑 Attiva Licenza INFINITY"* per sbloccare la rotazione a vita.
7. **Privacy Assoluta:** tutte le chiavi sono custodite in locale nel file `gemini_keys.json` (escluso da Git via `.gitignore`) e mostrate nell'interfaccia con mascheratura di sicurezza.

---

## ℹ️ Come Funziona il Terminale (Pannello Sinistro)

Nel pannello sinistro trovi il pulsante dedicato **`ℹ️ Come funziona il terminale`** che ti ricorda in ogni momento:
- 🟢 **Si apre una finestra nera** — il terminale interattivo dove scrivere i tuoi prompt o comandi e premere Invio.
- 🛡️ **Se il motore finisce i crediti** — con il Paracadute attivo, OmniRoute cambia motore automaticamente senza interrompere il lavoro.
- 🔄 **Per cambiare motore** — vai nella Pagina Iniziale sotto a "Pronto per Programmare" (`Motori Cloud Gratuiti` o `Motori Locali`), clicca il motore preferito e riavvia.
- 🛑 **Per chiudere tutto** — usa il pulsante rosso **"Chiudi Tutto"** in alto a destra, oppure digita `exit` nel terminale.

---

## ⚖️ Crediti e Licenza

- **Autore:** **ATON-FUX** ([https://github.com/aton-fux/OMNICLAUDE](https://github.com/aton-fux/OMNICLAUDE))
- **Licenza:** GNU GPL v3.0 con obbligo di attribuzione all'autore originale e tutela legale completa verso software di terze parti (vedi `LICENSE` e `NOTICE.md`).
