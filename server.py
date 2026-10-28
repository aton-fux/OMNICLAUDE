"""OMNICLAUDE — Local Web Server & AI Control Hub.
Created by ATON-FUX (https://github.com/aton-fux/OMNICLAUDE)
License: GNU General Public License v3.0 (GPL-3.0)

Zero external dependencies (uses Python standard library http.server, json, subprocess, shutil).
Provides REST endpoints to control AI models, API keys, modular Parachute fallback chain,
dynamic Ollama local model detection/installation, and process lifecycle.
"""

from __future__ import annotations

import html
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

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


def _http_get_text(url: str, timeout: int = 6) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) OMNICLAUDE/2.0",
            "Accept": "application/json, text/html, */*",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def search_ollama_library(query: str) -> list[dict]:
    """Live search on official Ollama Library (https://ollama.com/search)."""
    results: list[dict] = []
    try:
        url = f"https://ollama.com/search?q={quote(query.strip())}"
        raw_html = _http_get_text(url, timeout=6)
        # Split by result item blocks in ollama.com/search
        blocks = re.split(r'<li[^>]*x-test-model[^>]*>', raw_html)
        for blk in blocks[1:15]:
            m_name = re.search(r'x-test-search-response-title[^>]*>([^<]+)<', blk)
            if not m_name:
                m_href = re.search(r'href="/library/([^"/]+)"', blk)
                name = m_href.group(1).strip() if m_href else ""
            else:
                name = html.unescape(m_name.group(1).strip())
            if not name:
                continue

            m_desc = re.search(r'<p[^>]*class="[^"]*max-w-lg[^"]*"[^>]*>(.*?)</p>', blk, re.S)
            if not m_desc:
                m_desc = re.search(r'<p[^>]*>(.*?)</p>', blk, re.S)
            desc = ""
            if m_desc:
                desc = re.sub(r"<[^>]+>", "", m_desc.group(1)).strip()
                desc = html.unescape(re.sub(r"\s+", " ", desc))

            sizes = re.findall(r'x-test-size[^>]*>([^<]+)<', blk)
            sizes = [s.strip() for s in sizes if s.strip()]
            pulls_m = re.search(r'x-test-pull-count[^>]*>([^<]+)<', blk)
            pulls = pulls_m.group(1).strip() if pulls_m else ""

            # Build pullable variants (default or specific parameter sizes)
            default_tag = sizes[0] if sizes else "latest"
            pull_id = f"{name}:{default_tag}" if ":" not in name and sizes else name

            results.append({
                "source": "ollama",
                "source_label": "📚 Ollama Library",
                "name": name,
                "pull_id": pull_id,
                "variants": [f"{name}:{s}" for s in sizes[:6]] if sizes else [name],
                "desc": desc or f"Modello ufficiale dalla libreria Ollama ({name}).",
                "stats": f"⬇ {pulls} pulls" if pulls else "Libreria Ufficiale",
                "url": f"https://ollama.com/library/{name}",
                "installable": True,
            })
    except Exception:
        pass
    return results


def search_huggingface_gguf(query: str) -> list[dict]:
    """Live search on HuggingFace Hub for GGUF models directly pullable by Ollama (ollama pull hf.co/...)."""
    results: list[dict] = []
    try:
        q = query.strip() or "coder"
        url = f"https://huggingface.co/api/models?search={quote(q)}&filter=gguf&sort=downloads&direction=-1&limit=12"
        raw = _http_get_text(url, timeout=6)
        data = json.loads(raw)
        if isinstance(data, list):
            for item in data[:12]:
                repo_id = item.get("id") or item.get("modelId") or ""
                if not repo_id:
                    continue
                downloads = item.get("downloads", 0)
                likes = item.get("likes", 0)
                tags = [t for t in (item.get("tags") or []) if t not in ("gguf", "region:us")][:4]
                pull_id = f"hf.co/{repo_id}"
                results.append({
                    "source": "huggingface",
                    "source_label": "🤗 HuggingFace GGUF",
                    "name": repo_id,
                    "pull_id": pull_id,
                    "variants": [pull_id],
                    "desc": f"Repository GGUF su HuggingFace installabile direttamente in Ollama ({', '.join(tags) if tags else 'GGUF Quantized'}).",
                    "stats": f"⬇ {downloads:,} · ♥ {likes}",
                    "url": f"https://huggingface.co/{repo_id}",
                    "installable": True,
                })
    except Exception:
        pass
    return results


def search_github_models(query: str) -> list[dict]:
    """Live search on GitHub for Ollama / GGUF / Local AI model repositories & tools."""
    results: list[dict] = []
    try:
        q = query.strip() or "ollama model"
        gh_q = f"{q} ollama OR gguf"
        url = f"https://api.github.com/search/repositories?q={quote(gh_q)}&sort=stars&order=desc&per_page=9"
        raw = _http_get_text(url, timeout=6)
        data = json.loads(raw)
        for item in (data.get("items") or [])[:9]:
            full_name = item.get("full_name", "")
            html_url = item.get("html_url", "")
            desc = item.get("description") or "Repository GitHub per modelli AI / Ollama / GGUF."
            stars = item.get("stargazers_count", 0)
            results.append({
                "source": "github",
                "source_label": "🐙 GitHub Repo",
                "name": full_name,
                "pull_id": "",
                "variants": [],
                "desc": desc,
                "stats": f"★ {stars:,} stars",
                "url": html_url,
                "installable": False,
            })
    except Exception:
        pass
    return results


def search_models_multi(query: str, source: str = "all") -> list[dict]:
    """Search models dynamically across Ollama Library, HuggingFace GGUF, and GitHub."""
    source = (source or "all").lower().strip()
    out: list[dict] = []
    threads: list[threading.Thread] = []
    buckets: dict[str, list[dict]] = {"ollama": [], "huggingface": [], "github": []}

    if source in ("all", "ollama"):
        t1 = threading.Thread(target=lambda: buckets["ollama"].extend(search_ollama_library(query)))
        threads.append(t1)
        t1.start()
    if source in ("all", "huggingface"):
        t2 = threading.Thread(target=lambda: buckets["huggingface"].extend(search_huggingface_gguf(query)))
        threads.append(t2)
        t2.start()
    if source in ("all", "github"):
        t3 = threading.Thread(target=lambda: buckets["github"].extend(search_github_models(query)))
        threads.append(t3)
        t3.start()

    for t in threads:
        t.join(timeout=7)

    if source == "ollama":
        return buckets["ollama"]
    if source == "huggingface":
        return buckets["huggingface"]
    if source == "github":
        return buckets["github"]

    # Interleave or combine cleanly when source == "all"
    out.extend(buckets["ollama"][:8])
    out.extend(buckets["huggingface"][:6])
    out.extend(buckets["github"][:4])
    return out


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

        if parsed.path == "/api/search-models":
            q = qs.get("q", [""])[0].strip()
            source = qs.get("source", ["all"])[0].strip()
            items = search_models_multi(q, source)
            self.send_json({"ok": True, "query": q, "source": source, "results": items})
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
                self.send_json({"error": "Specifica il nome o link del modello da scaricare"}, status=400)
                return
            # Convert full HuggingFace URL or ollama pull prefix if user pasted it
            for prefix in ("ollama pull ", "ollama run "):
                if model_name.lower().startswith(prefix):
                    model_name = model_name[len(prefix):].strip()
            model_name = re.sub(r"^https?://(www\.)?huggingface\.co/", "hf.co/", model_name, flags=re.I)
            model_name = re.sub(r"^https?://(www\.)?ollama\.com/library/", "", model_name, flags=re.I)
            # Sanitize basic shell chars
            safe_model = "".join(c for c in model_name if c.isalnum() or c in ("-", "_", ":", ".", "/"))
            cmd_str = (
                f"title OMNICLAUDE - Download Modello Locale {safe_model} && color 0A && "
                "echo ============================================================ && "
                f"echo   SCARICAMENTO MODELLO LOCALE OLLAMA: {safe_model} && "
                "echo ============================================================ && "
                "echo. && "
                f"ollama pull {safe_model} && "
                "echo. && echo [COMPLETATO] Modello installato con successo! Torna su OMNICLAUDE e clicca 'Rileva Modelli PC'. && pause"
            )
            subprocess.Popen(["cmd.exe", "/c", cmd_str], creationflags=CREATE_NEW_CONSOLE, cwd=str(DIR))
            _CACHE["ollama"] = (0.0, {})
            self.send_json({"ok": True, "model": safe_model})
            return

        if parsed.path == "/api/delete-ollama-model":
            model_name = body.get("model", "").strip()
            if not model_name:
                self.send_json({"error": "Specifica il modello da rimuovere"}, status=400)
                return
            safe_model = "".join(c for c in model_name if c.isalnum() or c in ("-", "_", ":", ".", "/"))
            _run(["ollama", "rm", safe_model], timeout=8)
            _CACHE["ollama"] = (0.0, {})
            self.send_json({"ok": True, "deleted": safe_model})
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
