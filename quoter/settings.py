"""Local settings storage (carrier API credentials + default ship-from address).

Settings live in ``data/settings.json`` next to the app (override with the
``QUOTER_SETTINGS_FILE`` environment variable). That file is git-ignored
because it contains API secrets.
"""

from __future__ import annotations

import copy
import json
import os
import threading
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_PATH = BASE_DIR / "data" / "settings.json"

# Fields that must never be sent back to the browser.
SECRET_FIELDS = {"client_secret"}
MASK = "********"

DEFAULTS: dict = {
    "origin": {
        "company": "CMI",
        "address_line": "",
        "city": "",
        "state": "",
        "postal_code": "",
        "country_code": "US",
    },
    "carriers": {
        "ups": {
            "enabled": False,
            "environment": "sandbox",  # "sandbox" or "production"
            "client_id": "",
            "client_secret": "",
            "account_number": "",
            "negotiated_rates": True,
        },
        "fedex": {
            "enabled": False,
            "environment": "sandbox",
            "client_id": "",
            "client_secret": "",
            "account_number": "",
            "pickup_type": "DROPOFF_AT_FEDEX_LOCATION",
        },
    },
}

_lock = threading.Lock()


def _path() -> Path:
    return Path(os.environ.get("QUOTER_SETTINGS_FILE", DEFAULT_PATH))


def _merge(defaults: dict, stored: dict) -> dict:
    """Recursively overlay stored values onto defaults (keeps new default keys)."""
    out = copy.deepcopy(defaults)
    for key, value in (stored or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def load() -> dict:
    path = _path()
    with _lock:
        if not path.exists():
            return copy.deepcopy(DEFAULTS)
        with path.open("r", encoding="utf-8") as fh:
            stored = json.load(fh)
    return _merge(DEFAULTS, stored)


def save(settings: dict) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with _lock:
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(settings, fh, indent=2)
        os.replace(tmp, path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass  # Windows ignores most chmod bits; fine.


def public_view(settings: dict) -> dict:
    """Copy of settings safe to send to the browser (secrets masked)."""
    view = copy.deepcopy(settings)
    for carrier in view.get("carriers", {}).values():
        for key in SECRET_FIELDS:
            if carrier.get(key):
                carrier[key] = MASK
    return view


def apply_update(current: dict, incoming: dict) -> dict:
    """Merge an update from the settings form into the current settings.

    A secret left as the mask (or blank) keeps the stored value, so the form can
    be re-saved without re-typing secrets. Unknown keys are ignored.
    """
    updated = copy.deepcopy(current)

    for key in DEFAULTS["origin"]:
        if key in (incoming.get("origin") or {}):
            updated["origin"][key] = str(incoming["origin"][key]).strip()

    for name, defaults in DEFAULTS["carriers"].items():
        new = (incoming.get("carriers") or {}).get(name)
        if not isinstance(new, dict):
            continue
        target = updated["carriers"][name]
        for key, default in defaults.items():
            if key not in new:
                continue
            value = new[key]
            if key in SECRET_FIELDS:
                value = str(value or "").strip()
                if value in ("", MASK):
                    continue
            elif isinstance(default, bool):
                value = bool(value)
            else:
                value = str(value).strip()
            if key == "environment" and value not in ("sandbox", "production"):
                value = "sandbox"
            target[key] = value
    return updated
