"""OMNICLAUDE — Local Web Server & AI Control Hub.
Created by ATON-FUX (https://github.com/aton-fux/OMNICLAUDE)
License: GNU General Public License v3.0 (GPL-3.0)

Zero external dependencies (uses Python standard library http.server, json, subprocess, shutil).
Provides REST endpoints to control AI models, API keys, modular Parachute fallback chain,
dynamic Ollama local model detection/installation, and process lifecycle.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

# Protect against pythonw NoneType stdout/stderr crashes on Windows
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

DIR = Path(__file__).resolve().parent
WEB_DIR = DIR / "web"
CONFIG_FILE = DIR / "config.env"
PORT = 3000

DEFAULT_PARACHUTE_MODELS = "gemini/gemini-3.5-flash-lite,groq/llama-3.3-70b-versatile,deepseek/deepseek-chat"
DEFAULT_PARACHUTE_STRATEGY = "priority"

CREATE_NO_WINDOW = 0x08000000
CREATE_NEW_CONSOLE = 0x00000010

STARTUPINFO_HIDE = subprocess.STARTUPINFO()
STARTUPINFO_HIDE.dwFlags |= subprocess.STARTF_USESHOWWINDOW
STARTUPINFO_HIDE.wShowWindow = 0  # SW_HIDE

# subprocess helper: strictly hide any console window flash and handle encoding
_RUN_KWARGS = dict(
    capture_output=True,
    encoding="utf-8",
    errors="replace",
    creationflags=CREATE_NO_WINDOW,
    startupinfo=STARTUPINFO_HIDE,
)


def _run(cmd: list, timeout: int = 8) -> subprocess.CompletedProcess:
    """Run a command safely, completely hidden without any console window flash."""
    try:
        return subprocess.run(cmd, timeout=timeout, **_RUN_KWARGS)
    except Exception:
        return subprocess.CompletedProcess(cmd, 1, "", "")


def get_config() -> dict[str, str]:
    cfg = {
        "DEFAULT_MODEL": "gemini/gemini-3.5-flash-lite",
        "OMNIROUTE_PORT": "20128",
        "OMNIROUTE_TOKEN": "oma_live_omniclaude_local_token",
        "GEMINI_API_KEY": "",
        "PARACHUTE_MODELS": DEFAULT_PARACHUTE_MODELS,
        "PARACHUTE_STRATEGY": DEFAULT_PARACHUTE_STRATEGY,
    }
    if CONFIG_FILE.exists():
        for line in CONFIG_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                cfg[k.strip()] = v.strip()
    return cfg


def save_config(updates: dict[str, str]) -> None:
    current = get_config()
    current.update(updates)
    lines = [
        "# Configurazione Portatile OMNICLAUDE (Creato da ATON-FUX)",
        f"DEFAULT_MODEL={current.get('DEFAULT_MODEL', 'gemini/gemini-3.5-flash-lite')}",
        f"OMNIROUTE_PORT={current.get('OMNIROUTE_PORT', '20128')}",
        f"OMNIROUTE_TOKEN={current.get('OMNIROUTE_TOKEN', '')}",
        f"GEMINI_API_KEY={current.get('GEMINI_API_KEY', '')}",
        f"PARACHUTE_MODELS={current.get('PARACHUTE_MODELS', DEFAULT_PARACHUTE_MODELS)}",
        f"PARACHUTE_STRATEGY={current.get('PARACHUTE_STRATEGY', DEFAULT_PARACHUTE_STRATEGY)}",
    ]
    CONFIG_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def sync_opencode_model(model_id: str) -> None:
    """Ensure any selected model (including dynamic local Ollama models) is registered in OpenCode config."""
    try:
        local_cfg_path = DIR / "opencode.jsonc"
        user_cfg_dir = Path(os.environ.get("USERPROFILE", "")) / ".config" / "opencode"
        user_cfg_path = user_cfg_dir / "opencode.jsonc"

        if local_cfg_path.exists():
            data = json.loads(local_cfg_path.read_text(encoding="utf-8"))
            models_dict = data.setdefault("provider", {}).setdefault("omniroute", {}).setdefault("models", {})
            if model_id not in models_dict:
                models_dict[model_id] = {"name": f"{model_id} (OMNICLAUDE)"}
                local_cfg_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            if user_cfg_dir.exists() or True:
                user_cfg_dir.mkdir(parents=True, exist_ok=True)
                user_cfg_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception:
        pass


def is_port_listening(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def ensure_omniroute() -> bool:
    cfg = get_config()
    port = int(cfg.get("OMNIROUTE_PORT", "20128"))
    if not is_port_listening(port):
        subprocess.Popen(
            ["omniroute.cmd", "serve", "--no-open"],
            shell=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=CREATE_NO_WINDOW,
            startupinfo=STARTUPINFO_HIDE,
        )
        return True
    return False


def sync_parachute_combo(models_csv: str, strategy: str = "priority") -> None:
    """Register or update the modular parachute combo in OmniRoute."""
    ensure_omniroute()
    clean_models = ",".join([m.strip() for m in models_csv.split(",") if m.strip()])
    if not clean_models:
        clean_models = DEFAULT_PARACHUTE_MODELS
    if strategy not in ("priority", "round-robin", "least-used", "random"):
        strategy = "priority"
    _run([
        "omniroute.cmd", "combo", "create", "paracadute-gratis",
        "--strategy", strategy,
        "--models", clean_models,
    ])


_CACHE: dict[str, tuple[float, any]] = {
    "keys": (0.0, {}),
    "oauth": (0.0, {}),
    "ollama": (0.0, {}),
}


def get_keys_status(force: bool = False) -> dict[str, bool]:
    now = time.time()
    if not force and (now - _CACHE["keys"][0] < 15.0) and _CACHE["keys"][1]:
        return _CACHE["keys"][1]

    res = {
        "gemini": False,
        "groq": False,
        "deepseek": False,
        "openrouter": False,
        "anthropic": False,
        "openai": False,
    }
    try:
        proc = _run(["omniroute.cmd", "keys", "list"], timeout=5)
        out = proc.stdout.lower()
        for k in res.keys():
            if k in out:
                res[k] = True
    except Exception:
        pass
    if get_config().get("GEMINI_API_KEY"):
        res["gemini"] = True

    _CACHE["keys"] = (now, res)
    return res


def get_oauth_status(force: bool = False) -> dict[str, bool]:
    now = time.time()
    if not force and (now - _CACHE["oauth"][0] < 15.0) and _CACHE["oauth"][1]:
        return _CACHE["oauth"][1]

    res = {"claude": False}
    try:
        proc = _run(["omniroute.cmd", "oauth", "status"], timeout=5)
        out = proc.stdout.lower()
        if "claude" in out:
            res["claude"] = True
    except Exception:
        pass

    _CACHE["oauth"] = (now, res)
    return res


def get_ollama_status(force: bool = False) -> dict:
    now = time.time()
    if not force and (now - _CACHE["ollama"][0] < 12.0) and _CACHE["ollama"][1]:
        return _CACHE["ollama"][1]

    has_ollama = bool(shutil.which("ollama"))
    version = ""
    models: list[str] = []
    if has_ollama:
        try:
            v = _run(["ollama", "--version"], timeout=3)
            version = v.stdout.strip()
            m = _run(["ollama", "list"], timeout=4)
            for ln in m.stdout.splitlines():
                ln = ln.strip()
                if ln and not ln.upper().startswith("NAME"):
                    parts = ln.split()
                    if parts:
                        models.append(parts[0])
        except Exception:
            pass
    res = {"installed": has_ollama, "version": version, "models": models}
    _CACHE["ollama"] = (now, res)
    return res


class Handler(BaseHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(HTTPStatus.NO_CONTENT)
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)

        if parsed.path == "/api/status":
            force_refresh = qs.get("refresh", ["0"])[0] == "1"
            cfg = get_config()
            port = int(cfg.get("OMNIROUTE_PORT", "20128"))
            running = is_port_listening(port)
            model = cfg.get("DEFAULT_MODEL", "gemini/gemini-3.5-flash-lite")
            is_parachute = "paracadute" in model.lower()
            parachute_csv = cfg.get("PARACHUTE_MODELS", DEFAULT_PARACHUTE_MODELS)
            parachute_models = [m.strip() for m in parachute_csv.split(",") if m.strip()]
            parachute_strategy = cfg.get("PARACHUTE_STRATEGY", DEFAULT_PARACHUTE_STRATEGY)
            keys = get_keys_status(force=force_refresh)
            oauth_info = get_oauth_status(force=force_refresh)
            ollama_info = get_ollama_status(force=force_refresh)
            self.send_json({
                "running": running,
                "port": port,
                "model": model,
                "is_parachute": is_parachute,
                "parachute_models": parachute_models,
                "parachute_strategy": parachute_strategy,
                "keys": keys,
                "oauth": oauth_info,
                "ollama": ollama_info,
            })
            return

        # Serve static files from web/
        file_path = WEB_DIR / ("index.html" if parsed.path in ("/", "") else parsed.path.lstrip("/"))
        if file_path.exists() and file_path.is_file():
            mime = "text/html"
            suffix = file_path.suffix.lower()
            if suffix == ".css":
                mime = "text/css"
            elif suffix == ".js":
                mime = "application/javascript"
            elif suffix == ".json":
                mime = "application/json"
            elif suffix == ".png":
                mime = "image/png"
            elif suffix in (".jpg", ".jpeg"):
                mime = "image/jpeg"
            elif suffix == ".svg":
                mime = "image/svg+xml"
            elif suffix == ".ico":
                mime = "image/x-icon"
            self.send_response(HTTPStatus.OK)
            if mime.startswith("image/"):
                self.send_header("Content-Type", mime)
            else:
                self.send_header("Content-Type", f"{mime}; charset=utf-8")
            self.end_headers()
            self.wfile.write(file_path.read_bytes())
        else:
            self.send_response(HTTPStatus.NOT_FOUND)
            self.end_headers()
            self.wfile.write(b"File non trovato")

    def do_POST(self):
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}

        if parsed.path == "/api/set-model":
            model = body.get("model")
            if model:
                save_config({"DEFAULT_MODEL": model})
                sync_opencode_model(model)
                self.send_json({"ok": True, "model": model})
            else:
                self.send_json({"error": "Modello non specificato"}, status=400)
            return

        if parsed.path == "/api/toggle-parachute":
            cfg = get_config()
            current = cfg.get("DEFAULT_MODEL", "")
            parachute_csv = cfg.get("PARACHUTE_MODELS", DEFAULT_PARACHUTE_MODELS)
            strategy = cfg.get("PARACHUTE_STRATEGY", DEFAULT_PARACHUTE_STRATEGY)
            first_model = parachute_csv.split(",")[0].strip() if parachute_csv else "gemini/gemini-3.5-flash-lite"

            if "paracadute" in current.lower():
                new_model = first_model
                save_config({"DEFAULT_MODEL": new_model})
                self.send_json({"ok": True, "parachute": False, "model": new_model})
            else:
                sync_parachute_combo(parachute_csv, strategy)
                new_model = "combo/paracadute-gratis"
                save_config({"DEFAULT_MODEL": new_model})
                self.send_json({"ok": True, "parachute": True, "model": new_model})
            return

        if parsed.path == "/api/save-parachute":
            models_list = body.get("models", [])
            strategy = body.get("strategy", DEFAULT_PARACHUTE_STRATEGY)
            activate = body.get("activate", None)

            if isinstance(models_list, str):
                models_list = [m.strip() for m in models_list.split(",") if m.strip()]
            elif isinstance(models_list, list):
                models_list = [str(m).strip() for m in models_list if str(m).strip()]

            if not models_list:
                self.send_json({"error": "Inserisci almeno un motore nella catena Paracadute"}, status=400)
                return

            models_csv = ",".join(models_list)
            updates = {
                "PARACHUTE_MODELS": models_csv,
                "PARACHUTE_STRATEGY": strategy,
            }
            if activate is True:
                updates["DEFAULT_MODEL"] = "combo/paracadute-gratis"
            save_config(updates)
            sync_parachute_combo(models_csv, strategy)
            self.send_json({
                "ok": True,
                "parachute_models": models_list,
                "parachute_strategy": strategy,
                "model": get_config().get("DEFAULT_MODEL"),
            })
            return

        if parsed.path == "/api/install-ollama":
            # Opens an interactive console window that installs Ollama via winget or opens ollama.com
            cmd_str = (
                "title OMNICLAUDE - Installazione Automatica Ollama && color 0B && "
                "echo ============================================================ && "
                "echo   OMNICLAUDE - INSTALLAZIONE AUTOMATICA OLLAMA (100% OFFLINE) && "
                "echo ============================================================ && "
                "echo. && "
                "winget install Ollama.Ollama -e --accept-source-agreements --accept-package-agreements || start https://ollama.com/download && "
                "echo. && echo Installazione completata! Ora puoi scaricare i modelli dalla dashboard OMNICLAUDE. && pause"
            )
            subprocess.Popen(["cmd.exe", "/c", cmd_str], creationflags=CREATE_NEW_CONSOLE, cwd=str(DIR))
            _CACHE["ollama"] = (0.0, {})
            self.send_json({"ok": True, "message": "Installazione di Ollama avviata in una nuova finestra!"})
            return

        if parsed.path == "/api/pull-ollama-model":
            model_name = body.get("model", "").strip()
            if not model_name:
                self.send_json({"error": "Specifica il nome del modello Ollama da scaricare"}, status=400)
                return
            # Sanitize basic shell chars
            safe_model = "".join(c for c in model_name if c.isalnum() or c in ("-", "_", ":", ".", "/"))
            cmd_str = (
                f"title OMNICLAUDE - Download Modello Locale {safe_model} && color 0A && "
                "echo ============================================================ && "
                f"echo   SCARICAMENTO MODELLO LOCALE OLLAMA: {safe_model} && "
                "echo ============================================================ && "
                "echo. && "
                f"ollama pull {safe_model} && "
                "echo. && echo [COMPLETATO] Modello scaricato con successo! Torna su OMNICLAUDE per attivarlo. && pause"
            )
            subprocess.Popen(["cmd.exe", "/c", cmd_str], creationflags=CREATE_NEW_CONSOLE, cwd=str(DIR))
            _CACHE["ollama"] = (0.0, {})
            self.send_json({"ok": True, "model": safe_model})
            return

        if parsed.path == "/api/set-key":
            prov = body.get("provider", "").strip().lower()
            key = body.get("key", "").strip()
            if prov and key:
                ensure_omniroute()
                _run(["omniroute.cmd", "keys", "add", prov, key])
                if prov == "gemini":
                    save_config({"GEMINI_API_KEY": key})
                _CACHE["keys"] = (0.0, {})
                self.send_json({"ok": True, "provider": prov})
            else:
                self.send_json({"error": "Dati mancanti"}, status=400)
            return

        if parsed.path == "/api/launch-claude":
            ensure_omniroute()
            bat_path = DIR / "START_CLAUDE.bat"
            subprocess.Popen(
                ["cmd.exe", "/k", "call", str(bat_path)],
                creationflags=CREATE_NEW_CONSOLE,
                cwd=str(DIR),
            )
            self.send_json({"ok": True, "message": "Finestra terminale Claude Code aperta!"})
            return

        if parsed.path == "/api/launch-opencode":
            ensure_omniroute()
            bat_path = DIR / "START_OPENCODE.bat"
            subprocess.Popen(
                ["cmd.exe", "/k", "call", str(bat_path)],
                creationflags=CREATE_NEW_CONSOLE,
                cwd=str(DIR),
            )
            self.send_json({"ok": True, "message": "Finestra terminale OpenCode aperta!"})
            return

        if parsed.path == "/api/start-claude-oauth":
            ensure_omniroute()
            bat_path = DIR / "LOGIN_CLAUDE.bat"
            subprocess.Popen(
                ["cmd.exe", "/k", "call", str(bat_path)],
                creationflags=CREATE_NEW_CONSOLE,
                cwd=str(DIR),
            )
            self.send_json({"ok": True, "message": "Finestra di Login Claude Web aperta!"})
            return

        if parsed.path == "/api/stop-all":
            def _shutdown():
                time.sleep(0.5)
                _run(["taskkill", "/F", "/IM", "claude.exe"])
                _run(["taskkill", "/F", "/IM", "opencode.exe"])
                _run(["taskkill", "/F", "/FI", "WINDOWTITLE eq Claude Code*"])
                _run(["taskkill", "/F", "/FI", "WINDOWTITLE eq OpenCode*"])

                try:
                    ps = _run(["ollama", "ps"], timeout=4)
                    for ln in ps.stdout.splitlines():
                        ln = ln.strip()
                        if ln and not ln.upper().startswith("NAME"):
                            parts = ln.split()
                            if parts:
                                _run(["ollama", "stop", parts[0]], timeout=4)
                except Exception:
                    pass

                try:
                    _run(["omniroute.cmd", "stop"], timeout=6)
                except Exception:
                    pass

                try:
                    p = _run(["cmd.exe", "/c", "netstat -ano | findstr :20128.*LISTENING"], timeout=3)
                    for ln in p.stdout.splitlines():
                        parts = ln.strip().split()
                        if len(parts) >= 5 and parts[-1].isdigit():
                            _run(["taskkill", "/PID", parts[-1], "/F", "/T"])
                except Exception:
                    pass

                os._exit(0)

            threading.Thread(target=_shutdown, daemon=True).start()
            self.send_json({"ok": True, "message": "Tutti i servizi e processi (Claude, OpenCode, OmniRoute) sono stati arrestati. RAM e VRAM liberate."})
            return

        self.send_json({"error": "Endpoint sconosciuto"}, status=404)

    def send_json(self, data: dict, status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))

    def log_message(self, format, *args):
        pass  # Suppress request logs


def main():
    WEB_DIR.mkdir(parents=True, exist_ok=True)
    ensure_omniroute()
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
