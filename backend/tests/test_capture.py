"""DroneDingo self-tests — capture decoding and alert logic.

Pure stdlib unittest so it runs on the appliance with no extra packages:

    /opt/dronedingo/.venv/bin/python -m unittest discover -s /opt/dronedingo/backend/tests -v

These validate the decoders against synthetic packets built to spec. They prove
the parsing logic is self-consistent; confirming the *spec interpretation*
still requires one known real capture (see docs/VALIDATION.md).
"""
from __future__ import annotations
import math
import os
import struct
import sys
import unittest
from datetime import time as dtime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.capture import dji, dot11, odid, radiotap          # noqa: E402
from app.alerts import Alerter, _parse_quiet, _in_window     # noqa: E402
from app.geo import haversine_m, bearing_deg, compass        # noqa: E402

_RAD = 1e7 * math.pi / 180.0
_enc = lambda deg: round(deg * _RAD)          # noqa: E731

LAT, LON = 52.24050, -0.90270
OP_LAT, OP_LON = 52.23800, -0.90010


# --------------------------------------------------------------------------
# Open Drone ID (ASTM F3411) — used by both the WiFi and Bluetooth sources
# --------------------------------------------------------------------------
def _odid_location(lat, lon, alt, height, speed, heading):
    m = bytearray(25)
    m[0] = odid.MSG_LOCATION << 4
    m[2] = heading & 0xFF
    m[3] = round(speed / 0.25) & 0xFF
    struct.pack_into("<i", m, 5, round(lat / 1e-7))
    struct.pack_into("<i", m, 9, round(lon / 1e-7))
    struct.pack_into("<H", m, 13, round((0 + 1000) / 0.5))
    struct.pack_into("<H", m, 15, round((alt + 1000) / 0.5))
    struct.pack_into("<H", m, 17, round((height + 1000) / 0.5))
    return bytes(m)


def _odid_basic_id(uid, ua_type=2):
    m = bytearray(25)
    m[0] = odid.MSG_BASIC_ID << 4
    m[1] = ua_type & 0x0F
    b = uid.encode()[:20]
    m[2:2 + len(b)] = b
    return bytes(m)


def _odid_system(op_lat, op_lon):
    m = bytearray(25)
    m[0] = odid.MSG_SYSTEM << 4
    struct.pack_into("<i", m, 2, round(op_lat / 1e-7))
    struct.pack_into("<i", m, 6, round(op_lon / 1e-7))
    return bytes(m)


class TestOpenDroneID(unittest.TestCase):
    def setUp(self):
        msgs = (_odid_basic_id("1581F5EXAMPLE00042")
                + _odid_location(LAT, LON, 120.0, 40.0, 11.0, 149)
                + _odid_system(OP_LAT, OP_LON))
        self.pack = bytes([0xF0, 25, 3]) + msgs

    def test_message_pack_decodes_all_fields(self):
        d = odid.decode_pack(self.pack)
        self.assertEqual(d["drone_id"], "1581F5EXAMPLE00042")
        self.assertEqual(d["model"], "Multirotor")
        self.assertAlmostEqual(d["drone_lat"], LAT, places=4)
        self.assertAlmostEqual(d["drone_lon"], LON, places=4)
        self.assertAlmostEqual(d["alt_msl_m"], 120.0, delta=0.5)
        self.assertAlmostEqual(d["height_agl_m"], 40.0, delta=0.5)
        self.assertAlmostEqual(d["speed_mps"], 11.0, delta=0.3)
        self.assertEqual(d["heading_deg"], 149.0)

    def test_operator_position_recovered(self):
        d = odid.decode_pack(self.pack)
        self.assertAlmostEqual(d["operator_lat"], OP_LAT, places=4)
        self.assertAlmostEqual(d["operator_lon"], OP_LON, places=4)

    def test_single_message_bluetooth_path(self):
        d = odid.decode_single(_odid_location(LAT, LON, 60.0, 30.0, 5.0, 90))
        self.assertAlmostEqual(d["drone_lat"], LAT, places=4)

    def test_extracted_from_wifi_vendor_ie(self):
        ie = odid.ODID_OUI + bytes([odid.ODID_VENDOR_TYPE]) + b"\x07" + self.pack
        tail = dot11.find_vendor(ie, odid.ODID_OUI, odid.ODID_VENDOR_TYPE)
        self.assertIsNotNone(tail)
        self.assertEqual(odid.decode_pack(tail[1:])["drone_id"],
                         "1581F5EXAMPLE00042")

    def test_garbage_does_not_raise(self):
        self.assertIsInstance(odid.decode_pack(b"\x00" * 40), dict)
        self.assertEqual(odid.decode_pack(b""), {})


# --------------------------------------------------------------------------
# DJI DroneID (proprietary)
# --------------------------------------------------------------------------
def _dji_v2_body(serial=b"1581F5FKD2440100", device_type=27):
    b = bytearray(80)
    struct.pack_into("<HH", b, 0, 4242, 0x1234)
    b[4:4 + len(serial[:16])] = serial[:16]
    struct.pack_into("<ii", b, 20, _enc(LON), _enc(LAT))
    struct.pack_into("<hhhhh", b, 28, 1200, 400, 60, 80, -15)
    struct.pack_into("<hhh", b, 38, 0, 0, 900)
    struct.pack_into("<ii", b, 44, _enc(OP_LAT), _enc(OP_LON))
    struct.pack_into("<ii", b, 52, _enc(-0.90100), _enc(52.23900))
    b[60] = device_type
    return b


def _dji_packet(body, version=2):
    return bytes([0x10, version, len(body)]) + bytes(body)


class TestDjiDroneID(unittest.TestCase):
    def test_v2_full_decode(self):
        d = dji.decode(_dji_packet(_dji_v2_body()))
        self.assertEqual(d["drone_id"], "1581F5FKD2440100")
        self.assertEqual(d["model"], "DJI Mavic 3")
        self.assertAlmostEqual(d["drone_lat"], LAT, places=4)
        self.assertAlmostEqual(d["drone_lon"], LON, places=4)
        self.assertAlmostEqual(d["alt_msl_m"], 120.0, delta=0.2)
        self.assertAlmostEqual(d["height_agl_m"], 40.0, delta=0.2)
        self.assertAlmostEqual(d["speed_mps"], 10.0, delta=0.2)
        self.assertAlmostEqual(d["vspeed_mps"], -1.5, delta=0.2)
        self.assertAlmostEqual(d["heading_deg"], 53.1, delta=0.5)

    def test_v2_operator_and_home_position(self):
        d = dji.decode(_dji_packet(_dji_v2_body()))
        self.assertAlmostEqual(d["operator_lat"], OP_LAT, places=4)
        self.assertAlmostEqual(d["operator_lon"], OP_LON, places=4)
        self.assertAlmostEqual(d["_home_lat"], 52.23900, places=4)

    def test_unknown_device_type_falls_back(self):
        d = dji.decode(_dji_packet(_dji_v2_body(device_type=254)))
        self.assertEqual(d["model"], "DJI aircraft")

    def test_v1_decode(self):
        b = bytearray(64)
        b[0:16] = b"P3XSERIAL0001234"
        struct.pack_into("<ii", b, 16, _enc(LON), _enc(LAT))
        struct.pack_into("<hhhhh", b, 24, 900, 300, 0, 50, 0)
        struct.pack_into("<ii", b, 40, _enc(OP_LAT), _enc(OP_LON))
        d = dji.decode(_dji_packet(b, version=1))
        self.assertEqual(d["drone_id"], "P3XSERIAL0001234")
        self.assertAlmostEqual(d["drone_lat"], LAT, places=4)
        self.assertAlmostEqual(d["operator_lat"], OP_LAT, places=4)

    def test_implausible_coordinates_rejected(self):
        """A mis-decode must degrade to nothing, never fabricate telemetry."""
        b = _dji_v2_body()
        struct.pack_into("<ii", b, 20, 2 ** 31 - 1, 2 ** 31 - 1)
        self.assertEqual(dji.decode(_dji_packet(b)), {})

    def test_zero_fix_rejected(self):
        b = _dji_v2_body()
        struct.pack_into("<ii", b, 20, 0, 0)
        self.assertEqual(dji.decode(_dji_packet(b)), {})

    def test_truncated_input_safe(self):
        self.assertEqual(dji.decode(b"\x10\x02"), {})
        self.assertEqual(dji.decode(b""), {})

    def test_extracted_from_vendor_ie(self):
        ie = odid.DJI_OUI + _dji_packet(_dji_v2_body())
        payload = dot11.find_vendor(ie, odid.DJI_OUI)
        self.assertEqual(dji.decode(payload)["drone_id"], "1581F5FKD2440100")


# --------------------------------------------------------------------------
# 802.11 / radiotap
# --------------------------------------------------------------------------
class TestFrameParsing(unittest.TestCase):
    def test_radiotap_signal(self):
        buf = struct.pack("<BBHI", 0, 0, 9, 0x20) + struct.pack("<b", -42)
        rt = radiotap.parse(buf)
        self.assertEqual(rt.length, 9)
        self.assertEqual(rt.dbm_signal, -42)

    def test_radiotap_rejects_short_and_bad_version(self):
        self.assertIsNone(radiotap.parse(b"\x00\x00"))
        self.assertIsNone(radiotap.parse(struct.pack("<BBHI", 9, 0, 8, 0)))

    def test_beacon_vendor_ie_extraction(self):
        hdr = (bytes([0x80, 0x00]) + b"\x00\x00" + b"\xff" * 6
               + b"\xaa\xbb\xcc\xdd\xee\xff" + b"\x11" * 6 + b"\x00\x00")
        fixed = b"\x00" * 8 + b"\x64\x00" + b"\x01\x04"
        ssid = bytes([0, 4]) + b"TEST"
        payload = odid.ODID_OUI + b"\x0d\x00"
        vie = bytes([221, len(payload)]) + payload
        f = dot11.parse(hdr + fixed + ssid + vie)
        self.assertEqual(f.subtype, 8)
        self.assertEqual(f.src, "aa:bb:cc:dd:ee:ff")   # addr2 = transmitter
        self.assertTrue(any(o == odid.ODID_OUI for o, _ in f.vendor_ies))

    def test_malformed_frame_safe(self):
        self.assertIsNone(dot11.parse(b"\x80\x00"))
        self.assertIsInstance(dot11.parse(b"\x80" + b"\x00" * 40).vendor_ies, list)


# --------------------------------------------------------------------------
# Alerting
# --------------------------------------------------------------------------
class TestAlerts(unittest.TestCase):
    def _alerter(self, **over):
        conf = {"alerts": {"ntfy_topic": "t", "resight_after_s": 300,
                           "alert_ring_m": 250, **over},
                "map": {"range_rings_m": [250]}}
        return Alerter(conf)

    def test_disabled_without_target(self):
        self.assertFalse(Alerter({"alerts": {}}).enabled)
        self.assertFalse(Alerter({}).enabled)

    def test_fires_once_per_sighting(self):
        a = self._alerter()
        self.assertTrue(a._should_fire("A", 100))
        self.assertFalse(a._should_fire("A", 100), "repeat beacons debounced")

    def test_outside_ring_never_fires(self):
        self.assertFalse(self._alerter()._should_fire("A", 900))

    def test_positionless_detection_never_fires(self):
        """RF presence hits have no range and must not alert."""
        self.assertFalse(self._alerter()._should_fire("RF:900MHz", None))

    def test_drones_debounced_independently(self):
        a = self._alerter()
        self.assertTrue(a._should_fire("A", 100))
        self.assertTrue(a._should_fire("B", 100))

    def test_ring_defaults_to_inner_range_ring(self):
        a = Alerter({"alerts": {"ntfy_topic": "t"}, "map": {"range_rings_m": [400, 800]}})
        self.assertEqual(a.ring_m, 400)

    def test_quiet_hours_window_crossing_midnight(self):
        s, e = _parse_quiet("22:00-06:00")
        self.assertTrue(_in_window(dtime(23, 30), s, e))
        self.assertTrue(_in_window(dtime(2, 0), s, e))
        self.assertFalse(_in_window(dtime(12, 0), s, e))

    def test_bad_quiet_hours_ignored(self):
        self.assertIsNone(_parse_quiet("nonsense"))
        self.assertIsNone(_parse_quiet(None))

    def test_message_includes_operator_location(self):
        title, body = self._alerter()._compose({
            "model": "DJI Mavic 3", "range_m": 147, "compass": "NE",
            "drone_id": "X1", "height_agl_m": 44.2, "speed_mps": 11.0,
            "operator_lat": 52.238, "operator_lon": -0.9001,
            "source": "DroneID/WiFi"})
        self.assertIn("147", title)
        self.assertIn("Operator", body)
        self.assertIn("X1", body)


# --------------------------------------------------------------------------
# Geo helpers (range/bearing shown on every contact card)
# --------------------------------------------------------------------------
class TestGeo(unittest.TestCase):
    def test_known_distance(self):
        # 0.01 degrees of latitude is ~1.11 km anywhere.
        self.assertAlmostEqual(haversine_m(52.0, -1.0, 52.01, -1.0), 1111, delta=5)

    def test_zero_distance(self):
        self.assertAlmostEqual(haversine_m(52.0, -1.0, 52.0, -1.0), 0.0, places=6)

    def test_cardinal_bearings(self):
        self.assertAlmostEqual(bearing_deg(52.0, -1.0, 52.1, -1.0), 0.0, delta=0.5)
        self.assertAlmostEqual(bearing_deg(52.0, -1.0, 52.0, -0.9), 90.0, delta=0.5)

    def test_compass_labels(self):
        self.assertEqual(compass(0), "N")
        self.assertEqual(compass(90), "E")
        self.assertEqual(compass(225), "SW")
        self.assertEqual(compass(359), "N")


if __name__ == "__main__":
    unittest.main(verbosity=2)
