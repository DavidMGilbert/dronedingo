"""Offline map-pack validation and persistence tests."""
from __future__ import annotations

import sqlite3
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import basemaps  # noqa: E402


def make_mbtiles(path: Path) -> None:
    db = sqlite3.connect(path)
    try:
        db.execute("CREATE TABLE metadata (name TEXT, value TEXT)")
        db.execute("CREATE TABLE tiles (zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER, tile_data BLOB)")
        db.executemany("INSERT INTO metadata VALUES (?, ?)", [
            ("name", "Test district"), ("format", "png"),
            ("minzoom", "0"), ("maxzoom", "15"),
        ])
        db.execute("INSERT INTO tiles VALUES (0, 0, 0, ?)", (b"png",))
        db.commit()
    finally:
        db.close()


class TestBasemapPacks(unittest.TestCase):
    def test_filename_is_restricted_to_supported_archives(self):
        self.assertEqual(basemaps.safe_name("../My district.mbtiles"), "My-district.mbtiles")
        with self.assertRaises(ValueError):
            basemaps.safe_name("map.zip")

    def test_pack_is_described_and_activated_in_persistent_data(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pack_dir = root / "data" / "basemaps"
            pack_dir.mkdir(parents=True)
            pack = pack_dir / "district.mbtiles"
            make_mbtiles(pack)
            with patch.object(basemaps, "BASE", root), \
                 patch.object(basemaps, "PACK_DIR", pack_dir), \
                 patch.object(basemaps.cfg, "load", return_value={"map": {"basemap": {"path": None}}}), \
                 patch.object(basemaps.cfg, "save_settings") as save:
                info = basemaps.list_packs()[0]
                self.assertEqual(info["title"], "Test district")
                self.assertEqual(info["maxzoom"], 15)
                basemaps.activate("district.mbtiles")
                save.assert_called_once_with("map", {"basemap": {
                    "path": "data/basemaps/district.mbtiles", "schema": "protomaps",
                }})


if __name__ == "__main__":
    unittest.main()
