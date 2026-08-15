"""Install and manage persistent offline basemap packs."""
from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

from . import config as cfg
from .tiles import TileStore

BASE = Path(__file__).resolve().parents[2]
PACK_DIR = BASE / "data" / "basemaps"
SUPPORTED = {".pmtiles", ".mbtiles"}
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def safe_name(value: str) -> str:
    name = _SAFE_NAME.sub("-", Path(value or "").name).strip(".-")
    if not name or Path(name).suffix.lower() not in SUPPORTED:
        raise ValueError("Choose a .pmtiles or .mbtiles map pack.")
    return name


def relative_path(path: Path) -> str:
    return path.resolve().relative_to(BASE.resolve()).as_posix()


def configured_path() -> Path | None:
    raw = (((cfg.load().get("map") or {}).get("basemap") or {}).get("path"))
    if not raw:
        return None
    path = Path(raw)
    return path if path.is_absolute() else BASE / path


def describe(path: Path, active: Path | None = None) -> dict:
    store = TileStore(path)
    metadata = store.metadata
    return {
        "name": path.name,
        "size": path.stat().st_size,
        "format": store.tile_format,
        "vector": store.is_vector,
        "minzoom": store.minzoom,
        "maxzoom": store.maxzoom,
        "title": metadata.get("name") or metadata.get("description") or path.stem,
        "active": bool(active and path.resolve() == active.resolve()),
    }


def list_packs() -> list[dict]:
    PACK_DIR.mkdir(parents=True, exist_ok=True)
    active = configured_path()
    packs = []
    for path in sorted(PACK_DIR.iterdir(), key=lambda p: p.name.lower()):
        if path.is_file() and path.suffix.lower() in SUPPORTED:
            try:
                packs.append(describe(path, active))
            except Exception as exc:
                packs.append({"name": path.name, "size": path.stat().st_size,
                              "active": False, "error": str(exc)})
    return packs


def activate(name: str, schema: str = "protomaps") -> Path:
    path = PACK_DIR / safe_name(name)
    if path.parent.resolve() != PACK_DIR.resolve() or not path.is_file():
        raise FileNotFoundError("Map pack not found.")
    TileStore(path)  # validate before changing live configuration
    schema = schema if schema in ("protomaps", "openmaptiles") else "protomaps"
    cfg.save_settings("map", {"basemap": {
        "path": relative_path(path), "schema": schema,
    }})
    return path


def use_online() -> None:
    cfg.save_settings("map", {"basemap": {"path": None}})


def remove(name: str) -> None:
    path = PACK_DIR / safe_name(name)
    active = configured_path()
    if active and path.resolve() == active.resolve():
        raise ValueError("Switch to another map before removing the active pack.")
    if path.parent.resolve() != PACK_DIR.resolve() or not path.is_file():
        raise FileNotFoundError("Map pack not found.")
    path.unlink()


def free_bytes() -> int:
    PACK_DIR.mkdir(parents=True, exist_ok=True)
    return shutil.disk_usage(PACK_DIR).free


def commit_upload(temp: Path, filename: str) -> tuple[Path, dict]:
    """Validate a completed temporary upload and atomically publish it."""
    name = safe_name(filename)
    info = describe(temp)
    target = PACK_DIR / name
    os.replace(temp, target)
    return target, {**info, "name": name, "title": info.get("title") or Path(name).stem}
