# Phone alerts (ntfy)

DroneDingo pushes a notification to the farmer's phone the moment a drone comes
within the alert ring. It uses **ntfy** — free, no account, no app-store
subscription, and it works over any internet connection the Pi has.

## Setup (5 minutes)

1. **Install the ntfy app** on the phone (iOS App Store / Google Play / F-Droid).
2. **Choose a topic name.** Anyone who knows the topic can read your alerts, so
   treat it like a password — make it long and random:
   ```
   dronedingo-oakfield-7fq2p8xk
   ```
3. **Subscribe** to that topic in the app (+ → Subscribe to topic).
4. **Tell the appliance**, in `config/dronedingo.yaml`:
   ```yaml
   alerts:
     ntfy_topic: "dronedingo-oakfield-7fq2p8xk"
   ```
5. Restart and test:
   ```bash
   sudo systemctl restart dronedingo
   ```
   Then open the dashboard → **⚙ → Send test alert**. The phone should buzz.

Everyone who needs alerting (farmer, farm manager, a neighbour) just subscribes
to the same topic on their own phone.

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

When the operator's position is broadcast, the notification carries a **tap
action that opens their location on a map** — the single most useful thing to
have on a phone at 2am.

## Alert tuning

| Setting | Default | What it does |
|---|---|---|
| `alert_ring_m` | innermost range ring (250 m) | Alert when a contact comes this close |
| `resight_after_s` | 300 | Don't re-alert the same drone until it's been gone this long |
| `quiet_hours` | null | e.g. `"22:00-06:00"` |
| `quiet_hours_suppress` | **false** | Quiet hours only silence alerts if you set this true |

**On debouncing:** a drone broadcasts several times a second. Without
`resight_after_s` one overflight would produce hundreds of notifications and
the farmer would mute the app within a week — which means no alerting at all
when it matters. DroneDingo therefore sends **one alert per sighting**.

**On quiet hours:** overnight is exactly when theft happens, so quiet hours are
deliberately *not* suppressing by default. You must opt in.

## Privacy note

ntfy.sh is a public relay: the alert body (including operator coordinates)
passes through it. For sensitive deployments, self-host ntfy and point
`ntfy_server` at your own instance.

## Other integrations

Set `webhook_url` to receive the full detection record as JSON — for a siren
relay, a VMS, an SMS gateway, or a control room.
