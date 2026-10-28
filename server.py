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
import urllib.error
import urllib.request
import uuid
import datetime
import sqlite3
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


# ═══════════════════════════════════════════════════════════════════════════
# GEMINI MULTI-KEY HUB & FAILOVER ROTATOR ENGINE (Created by ATON-FUX)
# ═══════════════════════════════════════════════════════════════════════════
GEMINI_KEYS_FILE = DIR / "gemini_keys.json"
OMNIROUTE_DIR = Path(os.environ.get("USERPROFILE", "")) / ".omniroute"
OMNIROUTE_DB = OMNIROUTE_DIR / "storage.sqlite"
_POOL_LOCK = threading.Lock()
_LAST_PROCESSED_CALL_ID = ""


def mask_key(k: str) -> str:
    k = (k or "").strip()
    if not k:
        return ""
    if len(k) <= 10:
        return "********"
    return k[:6] + "****" + k[-4:]


def load_gemini_pool() -> dict:
    with _POOL_LOCK:
        if GEMINI_KEYS_FILE.exists():
            try:
                data = json.loads(GEMINI_KEYS_FILE.read_text(encoding="utf-8"))
                if isinstance(data, dict) and "keys" in data:
                    return data
            except Exception:
                pass

        # Inizializza automaticamente dal config.env se presente
        cfg = get_config()
        initial_key = cfg.get("GEMINI_API_KEY", "").strip()
        keys_list = []
        if initial_key:
            keys_list.append({
                "id": "gemini_default",
                "name": "Account Google #1 (Predefinito)",
                "key": initial_key,
                "status": "active",
                "calls_count": 0,
                "tokens_used": 0,
                "last_status": 200,
                "rate_limited_until": 0,
                "error_message": "",
                "last_checked": int(time.time()),
            })
        data = {
            "auto_failover": True,
            "active_id": "gemini_default" if keys_list else "",
            "keys": keys_list,
            "events": [
                {
                    "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "type": "init",
                    "message": "Pool Gemini inizializzato con failover automatico attivo (Zero Rate-Limit by ATON-FUX)."
                }
            ]
        }
        try:
            GEMINI_KEYS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception:
            pass
        return data


def save_gemini_pool(data: dict) -> None:
    with _POOL_LOCK:
        try:
            GEMINI_KEYS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception:
            pass


def test_gemini_api_key(key: str) -> dict:
    """Live verification of a Google Gemini API key via official models endpoint."""
    key = (key or "").strip()
    if not key:
        return {"valid": False, "status": 400, "message": "Chiave API mancante"}
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models?key={quote(key)}"
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 OMNICLAUDE/2.0 (by ATON-FUX)",
                "Accept": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
            models = [
                m.get("name", "").replace("models/", "")
                for m in data.get("models", [])
                if "gemini" in m.get("name", "").lower()
            ]
            return {
                "valid": True,
                "status": 200,
                "models_count": len(models),
                "sample_models": models[:6],
                "message": f"Chiave valida! {len(models)} modelli Gemini attivi e pronti.",
            }
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")
            err_json = json.loads(body)
            msg = err_json.get("error", {}).get("message") or body
        except Exception:
            msg = body or str(e)

        if e.code == 429:
            return {
                "valid": True,
                "status": 429,
                "rate_limited": True,
                "message": "Quota Esaurita o Rate Limit Raggiunto (HTTP 429 Too Many Requests / ResourceExhausted)",
                "detail": msg,
            }
        elif e.code in (400, 403):
            return {
                "valid": False,
                "status": e.code,
                "invalid": True,
                "message": "Chiave non valida o revocata (API_KEY_INVALID)",
                "detail": msg,
            }
        else:
            return {
                "valid": False,
                "status": e.code,
                "message": f"Errore Google Gemini HTTP {e.code}",
                "detail": msg,
            }
    except Exception as e:
        return {
            "valid": False,
            "status": 0,
            "message": f"Errore di connessione: {str(e)[:120]}",
        }


def get_gemini_db_stats() -> dict:
    """Query live token counts and recent call status directly from OmniRoute SQLite database."""
    out = {
        "total_calls": 0,
        "total_tokens": 0,
        "today_calls": 0,
        "today_tokens": 0,
        "latest_status": 200,
        "latest_model": "",
        "latest_time": "",
    }
    if not OMNIROUTE_DB.exists():
        return out
    try:
        today_start = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT00:00:00")
        conn = sqlite3.connect(f"file:{OMNIROUTE_DB}?mode=ro", uri=True, timeout=1.5)
        cur = conn.cursor()
        row = cur.execute('''
            SELECT 
                COUNT(*),
                COALESCE(SUM(tokens_in + tokens_out), 0),
                COALESCE(SUM(CASE WHEN timestamp >= ? THEN tokens_in + tokens_out ELSE 0 END), 0),
                COALESCE(SUM(CASE WHEN timestamp >= ? THEN 1 ELSE 0 END), 0)
            FROM call_logs 
            WHERE provider = 'gemini'
        ''', (today_start, today_start)).fetchone()
        if row:
            out["total_calls"] = int(row[0] or 0)
            out["total_tokens"] = int(row[1] or 0)
            out["today_tokens"] = int(row[2] or 0)
            out["today_calls"] = int(row[3] or 0)

        latest = cur.execute('''
            SELECT status, model, timestamp 
            FROM call_logs 
            WHERE provider = 'gemini' 
            ORDER BY id DESC LIMIT 1
        ''').fetchone()
        if latest:
            out["latest_status"] = latest[0]
            out["latest_model"] = latest[1] or ""
            out["latest_time"] = latest[2] or ""
        conn.close()
    except Exception:
        pass
    return out


def switch_active_gemini_key(target_id: str, reason: str = "") -> dict:
    """Switch active Gemini API key in pool, OmniRoute and config.env."""
    pool = load_gemini_pool()
    target_key = None
    for k in pool.get("keys", []):
        if k.get("id") == target_id:
            target_key = k
            break
    if not target_key:
        return {"ok": False, "error": f"Chiave ID {target_id} non trovata"}

    actual_key = target_key.get("key", "").strip()
    if actual_key:
        ensure_omniroute()
        _run(["omniroute.cmd", "keys", "add", "gemini", actual_key])
        save_config({"GEMINI_API_KEY": actual_key})

    for k in pool.get("keys", []):
        if k.get("id") == target_id:
            k["status"] = "active"
        elif k.get("status") == "active":
            k["status"] = "standby"

    pool["active_id"] = target_id
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    msg = f"Attivata chiave: {target_key.get('name')}" + (f" ({reason})" if reason else "")
    events = pool.setdefault("events", [])
    events.insert(0, {"time": now_str, "type": "switch", "message": msg})
    pool["events"] = events[:30]
    save_gemini_pool(pool)
    _CACHE["keys"] = (0.0, {})
    return {"ok": True, "active_id": target_id, "name": target_key.get("name")}


def rotate_to_next_gemini_key(reason: str = "Rate Limit 429 rilevato") -> dict:
    """Seamless failover to the next available healthy Gemini key in the pool."""
    pool = load_gemini_pool()
    keys = pool.get("keys", [])
    if not keys:
        return {"ok": False, "error": "Nessuna chiave configurata nel pool"}

    active_id = pool.get("active_id", "")
    now_ts = int(time.time())

    curr_idx = -1
    for i, k in enumerate(keys):
        if k.get("id") == active_id:
            curr_idx = i
            break

    # Segna la chiave attuale come rate_limited con cooldown di 5 minuti
    if curr_idx >= 0:
        keys[curr_idx]["status"] = "rate_limited"
        keys[curr_idx]["rate_limited_until"] = now_ts + 300
        keys[curr_idx]["error_message"] = reason

    # Ricerca circolare della prossima chiave pronta
    candidate = None
    n = len(keys)
    for offset in range(1, n + 1):
        idx = (curr_idx + offset) % n
        k = keys[idx]
        if k.get("id") == active_id and n > 1:
            continue
        if k.get("status") == "invalid":
            continue
        rl_until = k.get("rate_limited_until", 0)
        if rl_until > now_ts:
            continue
        candidate = k
        break

    if not candidate:
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        events = pool.setdefault("events", [])
        events.insert(0, {
            "time": now_str,
            "type": "error",
            "message": f"Tutte le chiavi Gemini ({n}) sono esaurite o in cooldown! In attesa di ripristino quota."
        })
        pool["events"] = events[:30]
        save_gemini_pool(pool)
        return {"ok": False, "error": "Tutte le chiavi nel pool hanno esaurito la quota"}

    res = switch_active_gemini_key(candidate["id"], reason=reason)
    return res


def _gemini_monitor_daemon():
    """Background thread: monitors SQLite call_logs for 429 quota exhaustion and recovers cooled-down keys."""
    global _LAST_PROCESSED_CALL_ID
    # Inizializza con l'ultimo ID esistente per non scattare su vecchie chiamate storiche
    if OMNIROUTE_DB.exists():
        try:
            conn = sqlite3.connect(f"file:{OMNIROUTE_DB}?mode=ro", uri=True, timeout=1.0)
            row = conn.cursor().execute("SELECT id FROM call_logs WHERE provider = 'gemini' ORDER BY id DESC LIMIT 1").fetchone()
            conn.close()
            if row:
                _LAST_PROCESSED_CALL_ID = row[0]
        except Exception:
            pass

    while True:
        try:
            time.sleep(3.0)
            pool = load_gemini_pool()
            now_ts = int(time.time())
            dirty = False

            # 1. Ripristina le chiavi il cui cooldown è terminato
            for k in pool.get("keys", []):
                if k.get("status") == "rate_limited":
                    until = k.get("rate_limited_until", 0)
                    if until and now_ts >= until:
                        k["status"] = "standby"
                        k["rate_limited_until"] = 0
                        dirty = True

            if dirty:
                save_gemini_pool(pool)

            # 2. Se auto_failover è attivo, controlla errori 429 recenti da OmniRoute
            if pool.get("auto_failover", True) and OMNIROUTE_DB.exists():
                try:
                    conn = sqlite3.connect(f"file:{OMNIROUTE_DB}?mode=ro", uri=True, timeout=1.0)
                    cur = conn.cursor()
                    row = cur.execute('''
                        SELECT id, status, timestamp, error_summary, model
                        FROM call_logs 
                        WHERE provider = 'gemini' 
                        ORDER BY id DESC LIMIT 1
                    ''').fetchone()
                    conn.close()

                    if row:
                        call_id, status, call_time, err_sum, model = row
                        if call_id != _LAST_PROCESSED_CALL_ID:
                            _LAST_PROCESSED_CALL_ID = call_id
                            err_str = (err_sum or "").lower()
                            if status in (429, 503) or "quota" in err_str or "exhausted" in err_str or "rate" in err_str:
                                reason = f"Errore {status} su {model}: {err_sum or 'Quota esaurita'}"
                                rotate_to_next_gemini_key(reason=reason)
                except Exception:
                    pass
        except Exception:
            pass


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

            # Gemini Multi-Key Hub snapshot
            g_pool = load_gemini_pool()
            g_db = get_gemini_db_stats()
            active_g_name = ""
            for k in g_pool.get("keys", []):
                if k.get("id") == g_pool.get("active_id"):
                    active_g_name = k.get("name", "")
                    break

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
                "gemini_hub": {
                    "keys_count": len(g_pool.get("keys", [])),
                    "active_name": active_g_name or "Nessuna chiave attiva",
                    "auto_failover": g_pool.get("auto_failover", True),
                    "today_tokens": g_db.get("today_tokens", 0),
                    "today_calls": g_db.get("today_calls", 0),
                    "total_tokens": g_db.get("total_tokens", 0),
                }
            })
            return

        if parsed.path == "/api/gemini-pool":
            pool = load_gemini_pool()
            db_stats = get_gemini_db_stats()
            keys_safe = []
            for k in pool.get("keys", []):
                keys_safe.append({
                    "id": k.get("id"),
                    "name": k.get("name"),
                    "masked_key": mask_key(k.get("key")),
                    "status": k.get("status"),
                    "calls_count": k.get("calls_count", 0),
                    "tokens_used": k.get("tokens_used", 0),
                    "last_status": k.get("last_status", 200),
                    "rate_limited_until": k.get("rate_limited_until", 0),
                    "error_message": k.get("error_message", ""),
                    "last_checked": k.get("last_checked", 0),
                })
            self.send_json({
                "ok": True,
                "auto_failover": pool.get("auto_failover", True),
                "active_id": pool.get("active_id", ""),
                "keys": keys_safe,
                "events": pool.get("events", [])[:20],
                "db_stats": db_stats,
                "daily_free_limit": 1000000,
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

        if parsed.path == "/api/gemini-pool/add":
            name = body.get("name", "").strip() or f"Account Google #{len(load_gemini_pool().get('keys', [])) + 1}"
            key = body.get("key", "").strip()
            do_validate = body.get("validate", True)
            if not key:
                self.send_json({"error": "Inserisci una chiave API Google Gemini valida (AIza...)"}, status=400)
                return

            val_res = test_gemini_api_key(key) if do_validate else {"valid": True, "status": 200, "message": "Non testata"}
            if do_validate and not val_res.get("valid") and not val_res.get("rate_limited"):
                self.send_json({
                    "error": f"Chiave non valida secondo Google AI Studio: {val_res.get('message')}",
                    "details": val_res
                }, status=400)
                return

            pool = load_gemini_pool()
            for existing in pool.get("keys", []):
                if existing.get("key") == key:
                    self.send_json({"error": "Questa chiave API è già presente nel pool!"}, status=400)
                    return

            new_id = f"gemini_{int(time.time())}_{uuid.uuid4().hex[:4]}"
            is_first = len(pool.get("keys", [])) == 0
            status = "active" if is_first else ("rate_limited" if val_res.get("rate_limited") else "standby")
            new_entry = {
                "id": new_id,
                "name": name,
                "key": key,
                "status": status,
                "calls_count": 0,
                "tokens_used": 0,
                "last_status": val_res.get("status", 200),
                "rate_limited_until": int(time.time()) + 300 if val_res.get("rate_limited") else 0,
                "error_message": val_res.get("message", ""),
                "last_checked": int(time.time()),
            }
            pool.setdefault("keys", []).append(new_entry)
            now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            events = pool.setdefault("events", [])
            events.insert(0, {
                "time": now_str,
                "type": "add",
                "message": f"Aggiunta nuova chiave: {name} ({mask_key(key)})"
            })
            pool["events"] = events[:30]

            if is_first:
                pool["active_id"] = new_id
                save_config({"GEMINI_API_KEY": key})
                ensure_omniroute()
                _run(["omniroute.cmd", "keys", "add", "gemini", key])

            save_gemini_pool(pool)
            self.send_json({"ok": True, "key_id": new_id, "name": name, "status": status, "validation": val_res})
            return

        if parsed.path == "/api/gemini-pool/delete":
            target_id = body.get("id", "").strip()
            pool = load_gemini_pool()
            keys = pool.get("keys", [])
            new_keys = [k for k in keys if k.get("id") != target_id]
            if len(new_keys) == len(keys):
                self.send_json({"error": "Chiave non trovata"}, status=404)
                return
            pool["keys"] = new_keys
            if pool.get("active_id") == target_id:
                if new_keys:
                    new_active = new_keys[0]
                    pool["active_id"] = new_active["id"]
                    new_active["status"] = "active"
                    save_config({"GEMINI_API_KEY": new_active["key"]})
                    _run(["omniroute.cmd", "keys", "add", "gemini", new_active["key"]])
                else:
                    pool["active_id"] = ""
                    save_config({"GEMINI_API_KEY": ""})
            now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            events = pool.setdefault("events", [])
            events.insert(0, {
                "time": now_str,
                "type": "delete",
                "message": f"Rimossa chiave dal pool (ID: {target_id})"
            })
            pool["events"] = events[:30]
            save_gemini_pool(pool)
            self.send_json({"ok": True, "deleted": target_id, "active_id": pool.get("active_id", "")})
            return

        if parsed.path == "/api/gemini-pool/set-active":
            target_id = body.get("id", "").strip()
            res = switch_active_gemini_key(target_id, reason="Attivazione manuale dall'interfaccia utente")
            self.send_json(res)
            return

        if parsed.path == "/api/gemini-pool/test-key":
            target_id = body.get("id", "").strip()
            raw_key = body.get("key", "").strip()
            key_to_test = raw_key
            pool = load_gemini_pool()
            target_obj = None
            if target_id:
                for k in pool.get("keys", []):
                    if k.get("id") == target_id:
                        target_obj = k
                        key_to_test = k.get("key")
                        break
            res = test_gemini_api_key(key_to_test)
            if target_obj:
                target_obj["last_status"] = res.get("status", 0)
                target_obj["last_checked"] = int(time.time())
                if res.get("valid"):
                    target_obj["error_message"] = ""
                    if target_obj.get("status") in ("invalid", "rate_limited"):
                        target_obj["status"] = "standby"
                        target_obj["rate_limited_until"] = 0
                elif res.get("rate_limited"):
                    target_obj["status"] = "rate_limited"
                    target_obj["rate_limited_until"] = int(time.time()) + 300
                    target_obj["error_message"] = res.get("message", "")
                else:
                    target_obj["status"] = "invalid"
                    target_obj["error_message"] = res.get("message", "")
                save_gemini_pool(pool)
            self.send_json({"ok": True, "result": res})
            return

        if parsed.path == "/api/gemini-pool/test-all":
            pool = load_gemini_pool()
            keys = pool.get("keys", [])
            threads = []
            results = {}

            def _worker(item):
                res = test_gemini_api_key(item.get("key"))
                results[item.get("id")] = res

            for k in keys:
                t = threading.Thread(target=_worker, args=(k,))
                threads.append(t)
                t.start()
            for t in threads:
                t.join(timeout=8)

            now_ts = int(time.time())
            for k in keys:
                r = results.get(k.get("id"))
                if r:
                    k["last_status"] = r.get("status", 0)
                    k["last_checked"] = now_ts
                    if r.get("valid"):
                        k["error_message"] = ""
                        if k.get("status") in ("invalid", "rate_limited"):
                            k["status"] = "standby"
                            k["rate_limited_until"] = 0
                    elif r.get("rate_limited"):
                        k["status"] = "rate_limited"
                        k["rate_limited_until"] = now_ts + 300
                        k["error_message"] = r.get("message", "")
                    else:
                        k["status"] = "invalid"
                        k["error_message"] = r.get("message", "")

            save_gemini_pool(pool)
            self.send_json({"ok": True, "results": results})
            return

        if parsed.path == "/api/gemini-pool/toggle-failover":
            enabled = bool(body.get("enabled", True))
            pool = load_gemini_pool()
            pool["auto_failover"] = enabled
            now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            events = pool.setdefault("events", [])
            events.insert(0, {
                "time": now_str,
                "type": "config",
                "message": f"Auto-failover Gemini impostato su: {'ATTIVO' if enabled else 'DISATTIVO'}"
            })
            pool["events"] = events[:30]
            save_gemini_pool(pool)
            self.send_json({"ok": True, "auto_failover": enabled})
            return

        if parsed.path == "/api/set-key":
            prov = body.get("provider", "").strip().lower()
            key = body.get("key", "").strip()
            if prov and key:
                ensure_omniroute()
                _run(["omniroute.cmd", "keys", "add", prov, key])
                if prov == "gemini":
                    save_config({"GEMINI_API_KEY": key})
                    # Sincronizza anche con il pool Gemini
                    pool = load_gemini_pool()
                    found = False
                    for k in pool.get("keys", []):
                        if k.get("key") == key:
                            switch_active_gemini_key(k.get("id"), reason="Aggiornata da pannello chiavi")
                            found = True
                            break
                    if not found:
                        new_id = f"gemini_{int(time.time())}_{uuid.uuid4().hex[:4]}"
                        pool.setdefault("keys", []).append({
                            "id": new_id,
                            "name": f"Account Google #{len(pool.get('keys', [])) + 1}",
                            "key": key,
                            "status": "active",
                            "calls_count": 0,
                            "tokens_used": 0,
                            "last_status": 200,
                            "rate_limited_until": 0,
                            "error_message": "",
                            "last_checked": int(time.time()),
                        })
                        switch_active_gemini_key(new_id, reason="Aggiunta da pannello chiavi")
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

    # Avvia daemon di monitoraggio quota e failover automatico Gemini (Zero Rate-Limit by ATON-FUX)
    mon_thread = threading.Thread(target=_gemini_monitor_daemon, daemon=True)
    mon_thread.start()

    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
