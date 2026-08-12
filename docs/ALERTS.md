# Phone alerts

DroneDingo pushes a notification to the farmer's phone the moment a drone comes
within the alert ring. Alerts are delivered by **DroneDingo Push** — proprietary,
end-to-end encrypted Web Push sent straight from the appliance. No third-party
app, no ntfy, no Apple/Google developer account.

## Setup

Register a phone from the dashboard: **⚙ Settings → Alerts → Add a phone**.
Scan the QR with the phone's camera, open the link, and tap **Enable alerts**.
Repeat for everyone who needs alerting (farmer, farm manager, a neighbour) — each
phone registers itself and appears in the device list, where it can also be
removed.

Then send a test: **⚙ Settings → Alerts → Send test push**. The phone should buzz.

For the mechanics (VAPID keys, the notify.dronedingo.com.au relay for appliances
without their own public HTTPS, and what production installs do and don't need),
see [PUSH_SETUP.md](PUSH_SETUP.md) and [PUSH_NOTIFICATIONS.md](PUSH_NOTIFICATIONS.md).

## What an alert looks like

```
DJI Mavic 3 detected — 147 m NE
ID: 1581F5FKD2440100
Range: 147 m NE
Height: 44 m
Speed: 11.0 m/s
Operator: 52.23800, -0.90010
Source: DroneID/WiFi
```

Tapping the alert opens the **DroneDingo portal deep-linked to the operator's
location and the aircraft** — the single most useful thing to have on a phone at
2am.

## Alert tuning

| Setting | Default | What it does |
|---|---|---|
| `alert_ring_m` | innermost range ring (250 m) | Alert when a contact comes this close |
| `resight_after_s` | 300 | Don't re-alert the same drone until it's been gone this long |
| `quiet_hours` | null | e.g. `"22:00-06:00"` |
| `quiet_hours_suppress` | **false** | Quiet hours only silence alerts if you set this true |

**On debouncing:** a drone broadcasts several times a second. Without
`resight_after_s` one overflight would produce hundreds of notifications and
the farmer would mute alerts within a week — which means no alerting at all
when it matters. DroneDingo therefore sends **one alert per sighting**.

**On quiet hours:** overnight is exactly when theft happens, so quiet hours are
deliberately *not* suppressing by default. You must opt in.

## Privacy note

Detection data is never relayed through a third party. The appliance encrypts
each alert (RFC 8291) and sends it directly to the phone's push service; only
the phone can decrypt it. When the notify.dronedingo.com.au relay is used, it
only parks a phone's subscription at registration time — no detection data ever
passes through it.

## Other integrations

Set `webhook_url` to receive the full detection record as JSON — for a siren
relay, a VMS, an SMS gateway, or a control room.
