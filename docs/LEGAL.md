# Legal & compliance posture

SkyWarden is a **passive detection and logging** system. It listens; it never
transmits, jams, spoofs, or takes control of any aircraft.

## What it does

- Receives **Remote ID / DJI DroneID** broadcasts (ASTM F3411) that compliant
  drones are legally required to emit in the clear.
- Optionally detects **RF energy** on ISM bands with an RTL-SDR to flag
  non-compliant/analog drones — energy detection only, no decoding of protected
  communications.
- Logs detections with timestamps and (where broadcast) drone and operator GPS.

## What it deliberately does NOT do

- No jamming, no signal interference, no "drone takeover", no GPS spoofing.
  In most jurisdictions (incl. the US under the Communications Act, 47 U.S.C.
  §333, and 18 U.S.C. §32) those actions are **criminal offences** for private
  parties. Only specific federal agencies hold mitigation authority.

## Receiving broadcasts

Passively receiving unencrypted Remote ID beacons is broadly permissible — they
are public safety broadcasts. Regulations differ by country; confirm your local
position. Do not attempt to receive or decode **encrypted** control links.

## Using logs as evidence

The database is timestamped and retains raw payloads to support evidentiary
use. Whether a log is **admissible**, and how it should be collected and
preserved, is a legal question — engage local law enforcement early; they can
often tell you the exact format they can act on. This project provides tooling,
not legal advice.

## Data protection

Logs may contain an operator's location (personal data). Restrict access,
set a sensible `retention_days`, and handle exports responsibly.
