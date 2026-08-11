# Validating the decoders against real hardware

The decoders are tested against synthetic packets built to spec (30 tests,
`backend/tests/`). That proves the parsing logic is self-consistent. It does
**not** prove our reading of the specification matches what real aircraft emit
— that needs one known capture. This is the single most valuable thing to do
when hardware arrives.

Run the suite any time:

```bash
/opt/skywarden/.venv/bin/python -m unittest discover -s /opt/skywarden/backend/tests -v
```

## Validating Remote ID (ASTM F3411)

Easiest reference: a phone running a Remote ID viewer app (e.g. "Drone Scanner"
or "OpenDroneID Receiver"), stood next to the SkyWarden node.

1. Fly a compliant drone, or have the phone app broadcast a test beacon.
2. Compare, field by field, what SkyWarden shows against the phone:
   - serial / UAS ID
   - drone lat/lon (should agree to ~5 decimal places)
   - **height vs altitude** — the most common place to get scaling wrong
   - speed (m/s, not km/h) and heading
   - operator lat/lon
3. Any mismatch is almost always a scale factor or a byte offset. The raw hex
   of every capture is stored in the `raw` column of the `detections` table:

   ```sql
   SELECT ts, drone_id, json_extract(raw,'$.hex') FROM detections
   WHERE source LIKE 'RID%' ORDER BY ts DESC LIMIT 5;
   ```

   Paste that hex into a test case in `backend/tests/test_capture.py`, assert
   the values you observed on the phone, then adjust
   `backend/app/capture/odid.py` until it passes. You now have a regression
   test built from real hardware.

## Validating DJI DroneID

Same method with a DJI aircraft. Points to check specifically:

| Field | Watch for |
|---|---|
| lat/lon | DJI encodes **radians x 1e7** — divisor 174532.925, not 1e7 |
| altitude / height | assumed decimetres (value/10); confirm against the app |
| speed | assumed decimetres/s; check a known hover (0) and a fast pass |
| `device_type` | add unseen codes to `DEVICE_TYPES` in `capture/dji.py` |
| record version | logged as `_dji_version` in `raw` — note which your aircraft uses |

**The decoder is deliberately conservative:** any decode producing impossible
coordinates is discarded and logged as a presence-only hit rather than
inventing telemetry (`test_implausible_coordinates_rejected`). So a wrong
scaling shows up as *missing* data, not as false evidence — which is the right
failure mode for something whose logs may end up in front of law enforcement.

## Validating the RF presence scanner

With the RTL-SDR connected and `rtlsdr_scan` enabled:

1. Watch the log with nothing transmitting — you should see no hits once the
   noise floor settles (about a minute).
2. Trigger a known emitter in one of the configured bands (e.g. a 433 MHz
   remote). You should get an `RF/RTL-SDR` contact.
3. If you get constant false hits, raise `trigger_db`; if nothing registers,
   lower it. Farms are RF-quiet, so 8–10 dB is usually a good starting point.
