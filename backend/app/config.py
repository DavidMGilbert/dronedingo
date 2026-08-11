"""Configuration loading.

Static deployment config lives in ``config/skywarden.yaml``.
Runtime-mutable state the UI can change (e.g. Home Base location) is written
to ``data/state.json`` and layered on top, so we never rewrite the YAML and
lose its comments.
"""
from __future__ import annotations
import json
import threading
from pathlib import Path
from typing import Any

import yaml

BASE = Path(__file__).resolve().parents[2]          # project root
CONFIG_PATH = BASE / "config" / "skywarden.yaml"
DATA_DIR = BASE / "data"
STATE_PATH = DATA_DIR / "state.json"

_lock = threading.Lock()


def _load_yaml() -> dict[str, Any]:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _load_state() -> dict[str, Any]:
    if STATE_PATH.exists():
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def load() -> dict[str, Any]:
    """Return the merged configuration (static YAML + mutable state)."""
    cfg = _load_yaml()
    state = _load_state()
    if "home" in state:
        cfg["site"]["home"].update(state["home"])
    # runtime source enable/disable overrides (set by installer autodetect or UI)
    for name, enabled in state.get("sources_enabled", {}).items():
        cfg["sources"].setdefault(name, {})["enabled"] = bool(enabled)
    cfg["_state"] = state
    return cfg


def get_home() -> dict[str, Any]:
    return load()["site"]["home"]


def get_node_id() -> str:
    return load()["site"]["node_id"]


def set_home(lat: float, lon: float, label: str | None = None) -> dict[str, Any]:
    """Persist a new Home Base location chosen from the UI."""
    DATA_DIR.mkdir(exist_ok=True)
    with _lock:
        state = _load_state()
        home = state.get("home", {})
        home.update({"lat": float(lat), "lon": float(lon), "set": True})
        if label:
            home["label"] = label
        state["home"] = home
        with open(STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
    return home


def set_source_enabled(name: str, enabled: bool) -> None:
    """Enable/disable a capture source at runtime (persists to state.json)."""
    DATA_DIR.mkdir(exist_ok=True)
    with _lock:
        state = _load_state()
        se = state.setdefault("sources_enabled", {})
        se[name] = bool(enabled)
        with open(STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
