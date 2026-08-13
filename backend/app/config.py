"""Configuration loading.

Static deployment config lives in ``config/dronedingo.yaml``.
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
CONFIG_PATH = BASE / "config" / "dronedingo.yaml"
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


def _deep_merge(base: dict, over: dict) -> None:
    """Recursively merge ``over`` into ``base`` in place."""
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v


# Config sections the UI is allowed to override via state.json.
_EDITABLE_SECTIONS = ("alerts", "map", "site", "updates")


def load() -> dict[str, Any]:
    """Return the merged configuration (static YAML + mutable state)."""
    cfg = _load_yaml()
    state = _load_state()
    # UI-edited settings overrides (alerts, map, etc.), layered over the YAML.
    for section, values in (state.get("settings") or {}).items():
        if section in _EDITABLE_SECTIONS and isinstance(values, dict):
            _deep_merge(cfg.setdefault(section, {}), values)
    if "home" in state:
        cfg["site"]["home"].update(state["home"])
    # runtime source enable/disable overrides (set by installer autodetect or UI)
    for name, enabled in state.get("sources_enabled", {}).items():
        cfg["sources"].setdefault(name, {})["enabled"] = bool(enabled)
    cfg["_state"] = state
    return cfg


def save_settings(section: str, values: dict) -> None:
    """Persist a UI settings override for one config section."""
    if section not in _EDITABLE_SECTIONS:
        raise ValueError(f"section '{section}' is not editable")
    DATA_DIR.mkdir(exist_ok=True)
    with _lock:
        state = _load_state()
        settings = state.setdefault("settings", {})
        current = settings.setdefault(section, {})
        _deep_merge(current, values)
        with open(STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)


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


def get_state() -> dict:
    return _load_state()


def update_state(**values) -> dict:
    """Merge top-level keys into the persisted runtime state."""
    DATA_DIR.mkdir(exist_ok=True)
    with _lock:
        state = _load_state()
        state.update(values)
        with open(STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
        return state


def set_source_enabled(name: str, enabled: bool) -> None:
    """Enable/disable a capture source at runtime (persists to state.json)."""
    DATA_DIR.mkdir(exist_ok=True)
    with _lock:
        state = _load_state()
        se = state.setdefault("sources_enabled", {})
        se[name] = bool(enabled)
        with open(STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)


# --------------------------------------------------------------------------
# raw YAML editing (Settings → Config)
# --------------------------------------------------------------------------
def read_yaml_text() -> str:
    """The exact contents of config/dronedingo.yaml, for the Config editor."""
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return f.read()


def write_yaml_text(text: str) -> None:
    """Validate that ``text`` is parseable YAML with a top-level mapping, back up
    the current file to .bak, then write it. Raises ValueError on bad YAML so the
    editor can show the parser error and nothing is overwritten with junk."""
    try:
        parsed = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ValueError(f"YAML error: {exc}")
    if not isinstance(parsed, dict):
        raise ValueError("Top level must be a mapping (key: value pairs).")
    with _lock:
        if CONFIG_PATH.exists():
            backup = CONFIG_PATH.with_suffix(".yaml.bak")
            backup.write_text(CONFIG_PATH.read_text(encoding="utf-8"),
                              encoding="utf-8")
        # Normalise line endings; keep the author's text otherwise verbatim.
        CONFIG_PATH.write_text(text.replace("\r\n", "\n"), encoding="utf-8")
