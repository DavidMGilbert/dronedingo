"""Offline basemap tile serving.

The appliance serves its own basemap so a farm with no internet still gets a
map. Two container formats are supported, both read directly with the standard
library:

* **MBTiles** — SQLite; the long-standing interchange format.
* **PMTiles v3** — single-file archive; what a Protomaps region extract
  produces, and the easiest way to obtain a small area.

Either may hold raster (PNG/JPEG/WebP) or vector (Mapbox Vector Tile) data;
:meth:`TileStore.tile_format` reports which so the style generator can pick the
right layer type.
"""
from __future__ import annotations
import gzip
import json
import logging
import sqlite3
import struct
import zlib
from pathlib import Path
from typing import Optional

log = logging.getLogger("dronedingo")

# PMTiles compression identifiers.
_C_NONE, _C_GZIP, _C_BROTLI, _C_ZSTD = 1, 2, 3, 4
# PMTiles tile type identifiers.
_T_MVT, _T_PNG, _T_JPEG, _T_WEBP, _T_AVIF = 1, 2, 3, 4, 5

_MIME = {
    "pbf": "application/x-protobuf", "mvt": "application/x-protobuf",
    "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
    "webp": "image/webp", "avif": "image/avif",
}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _decompress(data: bytes, compression: int) -> bytes:
    if compression == _C_GZIP:
        return gzip.decompress(data)
    if compression == _C_NONE:
        return data
    if compression == _C_ZSTD:
        try:
            import zstandard
        except ImportError as exc:                      # pragma: no cover
            raise RuntimeError("PMTiles uses zstd; pip install zstandard") from exc
        return zstandard.ZstdDecompressor().decompress(data)
    if compression == _C_BROTLI:                        # pragma: no cover
        try:
            import brotli
        except ImportError as exc:
            raise RuntimeError("PMTiles uses brotli; pip install brotli") from exc
        return brotli.decompress(data)
    return data


def _read_varint(buf: bytes, pos: int) -> tuple[int, int]:
    result = shift = 0
    while True:
        b = buf[pos]
        pos += 1
        result |= (b & 0x7F) << shift
        if not (b & 0x80):
            return result, pos
        shift += 7


def _zxy_to_tileid(z: int, x: int, y: int) -> int:
    """PMTiles addresses tiles by Hilbert-curve index within a zoom level."""
    base = ((1 << (z * 2)) - 1) // 3       # (4^z - 1) / 3
    n = 1 << z
    rx = ry = 0
    d = 0
    s = n >> 1
    tx, ty = x, y
    while s > 0:
        rx = 1 if (tx & s) > 0 else 0
        ry = 1 if (ty & s) > 0 else 0
        d += s * s * ((3 * rx) ^ ry)
        # rotate
        if ry == 0:
            if rx == 1:
                tx = s - 1 - tx
                ty = s - 1 - ty
            tx, ty = ty, tx
        s >>= 1
    return base + d


# ---------------------------------------------------------------------------
# MBTiles
# ---------------------------------------------------------------------------
class MBTilesStore:
    def __init__(self, path: Path) -> None:
        self.path = str(path)
        self._meta: dict[str, str] = {}
        db = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)
        try:
            try:
                self._meta = {k: v for k, v in
                              db.execute("SELECT name, value FROM metadata")}
            except sqlite3.Error:
                self._meta = {}
        finally:
            db.close()

    @property
    def tile_format(self) -> str:
        return (self._meta.get("format") or "png").lower()

    @property
    def metadata(self) -> dict:
        return dict(self._meta)

    @property
    def minzoom(self) -> int:
        return int(self._meta.get("minzoom", 0))

    @property
    def maxzoom(self) -> int:
        return int(self._meta.get("maxzoom", 14))

    def get(self, z: int, x: int, y: int) -> Optional[bytes]:
        # MBTiles stores rows in TMS order (y flipped relative to XYZ).
        flipped = (1 << z) - 1 - y
        db = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)
        try:
            row = db.execute(
                "SELECT tile_data FROM tiles WHERE zoom_level=? AND "
                "tile_column=? AND tile_row=?", (z, x, flipped)).fetchone()
        finally:
            db.close()
        if not row:
            return None
        data = row[0]
        # Vector MBTiles are conventionally gzipped inside the container.
        if data[:2] == b"\x1f\x8b":
            try:
                data = gzip.decompress(data)
            except (OSError, zlib.error):
                pass
        return data


# ---------------------------------------------------------------------------
# PMTiles v3
# ---------------------------------------------------------------------------
class PMTilesStore:
    _HEADER_LEN = 127

    def __init__(self, path: Path) -> None:
        self.path = path
        with open(path, "rb") as f:
            hdr = f.read(self._HEADER_LEN)
        if hdr[:7] != b"PMTiles":
            raise ValueError(f"{path} is not a PMTiles archive")
        if hdr[7] != 3:
            raise ValueError(f"{path}: only PMTiles v3 is supported")
        (self.root_off, self.root_len, self.meta_off, self.meta_len,
         self.leaf_off, self.leaf_len, self.data_off, self.data_len) = \
            struct.unpack_from("<QQQQQQQQ", hdr, 8)
        self.internal_compression = hdr[97]
        self.tile_compression = hdr[98]
        self.tile_type = hdr[99]
        self.minzoom = hdr[100]
        self.maxzoom = hdr[101]
        self._root = self._read_dir(self.root_off, self.root_len)

    # -- directories --
    def _read_dir(self, offset: int, length: int) -> list[tuple[int, int, int, int]]:
        with open(self.path, "rb") as f:
            f.seek(offset)
            raw = f.read(length)
        buf = _decompress(raw, self.internal_compression)
        n, pos = _read_varint(buf, 0)
        ids, runs, lengths, offsets = [], [], [], []
        last = 0
        for _ in range(n):
            delta, pos = _read_varint(buf, pos)
            last += delta
            ids.append(last)
        for _ in range(n):
            v, pos = _read_varint(buf, pos)
            runs.append(v)
        for _ in range(n):
            v, pos = _read_varint(buf, pos)
            lengths.append(v)
        for i in range(n):
            v, pos = _read_varint(buf, pos)
            # 0 means "immediately after the previous entry"
            offsets.append(offsets[i - 1] + lengths[i - 1] if v == 0 and i > 0
                           else v - 1)
        return list(zip(ids, runs, lengths, offsets))

    @staticmethod
    def _find(entries, tile_id: int):
        lo, hi = 0, len(entries) - 1
        best = None
        while lo <= hi:
            mid = (lo + hi) // 2
            if entries[mid][0] <= tile_id:
                best = entries[mid]
                lo = mid + 1
            else:
                hi = mid - 1
        if best is None:
            return None
        tid, run, length, off = best
        if run == 0:                       # leaf-directory pointer
            return best
        return best if tid + run > tile_id else None

    @property
    def tile_format(self) -> str:
        return {_T_MVT: "pbf", _T_PNG: "png", _T_JPEG: "jpg",
                _T_WEBP: "webp", _T_AVIF: "avif"}.get(self.tile_type, "png")

    @property
    def metadata(self) -> dict:
        with open(self.path, "rb") as f:
            f.seek(self.meta_off)
            raw = f.read(self.meta_len)
        try:
            return json.loads(_decompress(raw, self.internal_compression))
        except Exception:
            return {}

    def get(self, z: int, x: int, y: int) -> Optional[bytes]:
        if z < self.minzoom or z > self.maxzoom:
            return None
        tile_id = _zxy_to_tileid(z, x, y)
        entries = self._root
        for _ in range(4):                       # root + up to 3 leaf levels
            hit = self._find(entries, tile_id)
            if hit is None:
                return None
            tid, run, length, off = hit
            if run == 0:                         # descend into a leaf directory
                entries = self._read_dir(self.leaf_off + off, length)
                continue
            with open(self.path, "rb") as f:
                f.seek(self.data_off + off)
                raw = f.read(length)
            return _decompress(raw, self.tile_compression)
        return None


# ---------------------------------------------------------------------------
# facade
# ---------------------------------------------------------------------------
class TileStore:
    """Opens whichever container is configured and serves tiles from it."""

    def __init__(self, path: str | Path) -> None:
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"basemap not found: {p}")
        suffix = p.suffix.lower()
        if suffix == ".pmtiles":
            self._store = PMTilesStore(p)
        elif suffix in (".mbtiles", ".sqlite", ".db"):
            self._store = MBTilesStore(p)
        else:
            raise ValueError(f"unsupported basemap format: {p.suffix}")
        self.path = p
        log.info("basemap loaded: %s (%s, z%d-%d)", p.name, self.tile_format,
                 self.minzoom, self.maxzoom)

    @property
    def tile_format(self) -> str:
        return self._store.tile_format

    @property
    def is_vector(self) -> bool:
        return self.tile_format in ("pbf", "mvt")

    @property
    def content_type(self) -> str:
        return _MIME.get(self.tile_format, "application/octet-stream")

    @property
    def minzoom(self) -> int:
        return int(getattr(self._store, "minzoom", 0))

    @property
    def maxzoom(self) -> int:
        return int(getattr(self._store, "maxzoom", 14))

    @property
    def metadata(self) -> dict:
        return self._store.metadata

    def get(self, z: int, x: int, y: int) -> Optional[bytes]:
        try:
            return self._store.get(z, x, y)
        except Exception:
            log.exception("tile read failed z=%s x=%s y=%s", z, x, y)
            return None
