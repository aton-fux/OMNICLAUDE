"""OMNICLAUDE INFINITY — License Management System
Created by ATON-FUX (https://github.com/aton-fux/OMNICLAUDE)

Handles validation of OMNICLAUDE INFINITY licenses:
1. Offline Cryptographic HMAC-SHA256 licenses (unique per customer/serial)
2. Online Gumroad API license verification (with activation tracking)
3. Creator Master License for ATON-FUX
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

DIR = Path(__file__).resolve().parent
LICENSE_FILE = DIR / "license.json"

# Master signing secret for offline cryptographic keys (Owned exclusively by ATON-FUX)
_MASTER_SECRET = b"ATON-FUX_OMNICLAUDE_PRO_2026_MASTER_CRYPT_KEY_v2"
GUMROAD_PRODUCT_PERMALINK = "omniclaude-pro"
GUMROAD_PRODUCT_ID = "ph5_jemwJFTHsF9qYpJPqw=="
GUMROAD_DEFAULT_URL = "https://kronostone.gumroad.com/l/omniclaude-pro"
STORE_URL = "https://aton-fux.github.io/OMNICLAUDE/"

# Creator Master Keys (can be used by ATON-FUX anywhere)
CREATOR_MASTER_KEYS = {
    "OMNI-CREATOR-ATON-FUX-INFINITY-2026-MASTER-KEY",
    "OMNI-CREATOR-ATON-FUX-PRO-2026-MASTER-KEY",
}
CREATOR_MASTER_KEY = "OMNI-CREATOR-ATON-FUX-INFINITY-2026-MASTER-KEY"


def _compute_hmac(payload: str) -> str:
    """Compute 10-char uppercase HMAC-SHA256 signature."""
    h = hmac.new(_MASTER_SECRET, payload.strip().upper().encode("utf-8"), hashlib.sha256)
    return h.hexdigest()[:10].upper()


def generate_offline_license(serial: str, licensed_to: str = "Customer", prefix: str = "INF") -> str:
    """Generate a unique cryptographically signed offline INFINITY license key.
    Format: OMNI-INF-<SERIAL>-<HMAC_SIGNATURE> (or OMNI-PRO-...)
    """
    clean_serial = re.sub(r"[^A-Z0-9]", "", serial.strip().upper())
    if len(clean_serial) < 4:
        clean_serial = hashlib.sha256(f"{serial}-{datetime.now().isoformat()}".encode()).hexdigest()[:8].upper()
    sig = _compute_hmac(clean_serial)
    tag = "INF" if prefix.upper() in ("INF", "INFINITY") else "PRO"
    return f"OMNI-{tag}-{clean_serial}-{sig}"


def verify_offline_license(key: str) -> Tuple[bool, str]:
    """Verify an offline cryptographic license key."""
    clean = key.strip().upper()
    
    # Check Master Keys
    if clean in CREATOR_MASTER_KEYS:
        return True, "Licenza Ufficiale Creatore (ATON-FUX)"
        
    parts = clean.split("-")
    if len(parts) != 4 or parts[0] != "OMNI" or parts[1] not in ("PRO", "INF", "INFINITY"):
        return False, "Formato chiave non valido. Atteso: OMNI-INF-XXXX-XXXXXXXXXX"
        
    serial = parts[2]
    expected_sig = _compute_hmac(serial)
    if hmac.compare_digest(parts[3], expected_sig):
        return True, f"Licenza Crittografica Convalidata (Seriale {serial})"
        
    return False, "Firma licenza non valida o contraffatta"


def verify_gumroad_license(license_key: str, product_permalink: str = GUMROAD_PRODUCT_PERMALINK, product_id: str = GUMROAD_PRODUCT_ID) -> Tuple[bool, str, Dict[str, Any]]:
    """Verify a license key using Gumroad's official API."""
    url = "https://api.gumroad.com/v2/licenses/verify"
    payload = {
        "license_key": license_key.strip(),
        "increment_uses_count": "true"
    }
    if product_id:
        payload["product_id"] = product_id
    else:
        payload["product_permalink"] = product_permalink
    data = urllib.parse.urlencode(payload).encode("utf-8")
    
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "User-Agent": "OMNICLAUDE-Infinity-License-Verifier/2.0",
            "Content-Type": "application/x-www-form-urlencoded"
        },
        method="POST"
    )
    
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            if body.get("success") is True:
                purchase = body.get("purchase", {})
                email = purchase.get("email", "Acquirente Gumroad")
                uses = body.get("uses", 1)
                return True, f"Licenza Gumroad Convalidata ({email}, Attivazione #{uses})", purchase
            else:
                msg = body.get("message", "Chiave Gumroad non valida o scaduta.")
                return False, msg, {}
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode("utf-8"))
            msg = body.get("message", f"Errore server Gumroad ({e.code})")
        except Exception:
            msg = f"Errore verifica Gumroad: HTTP {e.code}"
        return False, msg, {}
    except Exception as e:
        return False, f"Impossibile contattare Gumroad: {e}", {}


def load_license() -> Dict[str, Any]:
    """Read local license.json file if present."""
    if not LICENSE_FILE.exists():
        return {
            "is_pro": False,
            "is_infinity": False,
            "tier": "free",
            "licensed_to": None,
            "license_type": None,
            "activated_at": None,
            "license_key_masked": None
        }
    try:
        with open(LICENSE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if data.get("master") is True or data.get("is_pro") is True or data.get("is_infinity") is True:
                data["is_pro"] = True
                data["is_infinity"] = True
                data["tier"] = "infinity"
                return data
    except Exception:
        pass
    return {"is_pro": False, "is_infinity": False, "tier": "free"}


def save_license(license_data: Dict[str, Any]) -> bool:
    """Save validated license locally."""
    try:
        license_data["is_pro"] = True
        license_data["is_infinity"] = True
        license_data["tier"] = "infinity"
        with open(LICENSE_FILE, "w", encoding="utf-8") as f:
            json.dump(license_data, f, indent=2, ensure_ascii=False)
        return True
    except Exception:
        return False


def is_pro_active() -> bool:
    """Check if INFINITY features are fully activated."""
    status = load_license()
    return bool(status.get("is_infinity") or status.get("is_pro"))


def activate_license(key: str, licensed_to_hint: str = "") -> Tuple[bool, str, Dict[str, Any]]:
    """Activate license by checking offline HMAC first, then Gumroad API."""
    clean_key = key.strip()
    if not clean_key:
        return False, "La chiave di licenza non può essere vuota.", {}

    # 1. Check Creator Master Key
    if clean_key in CREATOR_MASTER_KEYS:
        lic = {
            "is_pro": True,
            "is_infinity": True,
            "tier": "infinity",
            "master": True,
            "licensed_to": "ATON-FUX (Official Creator)",
            "license_type": "Creator Master Infinity Lifetime",
            "license_key_masked": "OMNI-CREATOR-***-MASTER",
            "activated_at": datetime.now().isoformat()
        }
        save_license(lic)
        return True, "Licenza Master Creatore ATON-FUX attivata con successo!", lic

    # 2. Check Offline Cryptographic Key (OMNI-INF-... or OMNI-PRO-...)
    if clean_key.upper().startswith("OMNI-INF-") or clean_key.upper().startswith("OMNI-PRO-"):
        valid, msg = verify_offline_license(clean_key)
        if valid:
            masked = clean_key[:9] + "..." + clean_key[-4:]
            lic = {
                "is_pro": True,
                "is_infinity": True,
                "tier": "infinity",
                "master": False,
                "licensed_to": licensed_to_hint or "Utente OMNICLAUDE INFINITY",
                "license_type": "Lifetime Infinity Key",
                "license_key_masked": masked,
                "activated_at": datetime.now().isoformat()
            }
            save_license(lic)
            return True, f"Licenza INFINITY attivata con successo! ({msg})", lic
        else:
            return False, f"Chiave non valida: {msg}", {}

    # 3. Check Gumroad Key
    valid, msg, purchase = verify_gumroad_license(clean_key)
    if valid:
        email = purchase.get("email") or licensed_to_hint or "Acquirente Gumroad"
        masked = clean_key[:4] + "-****-****-" + clean_key[-4:] if len(clean_key) >= 12 else clean_key[:3] + "***"
        lic = {
            "is_pro": True,
            "is_infinity": True,
            "tier": "infinity",
            "master": False,
            "licensed_to": email,
            "license_type": "Gumroad Lifetime Infinity (14.99€)",
            "license_key_masked": masked,
            "gumroad_purchase_id": purchase.get("id"),
            "activated_at": datetime.now().isoformat()
        }
        save_license(lic)
        return True, f"Licenza INFINITY attivata tramite Gumroad! Proprietario: {email}", lic

    return False, f"Verifica licenza fallita: {msg}", {}


def remove_license() -> bool:
    """Remove current license (reset to free)."""
    if LICENSE_FILE.exists():
        try:
            LICENSE_FILE.unlink()
            return True
        except Exception:
            return False
    return True
