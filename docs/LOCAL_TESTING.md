# Running DroneDingo locally & testing push notifications

## 1. Run the appliance on your PC

From the project folder:

```powershell
powershell -File deploy\run-local.ps1
```

(That makes/uses `.venv`, installs deps, and starts the server on
`http://localhost:8000`. Or run it by hand:
`.\.venv\Scripts\python -m uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8000`.)

Open **http://localhost:8000**, create the admin login (email + password), and
set your Home Base in **Settings → Location** (Binderra is the current default).
The simulator flies two drones around Home Base so the map and alerts are live.

---

## 2. Test DroneDingo Push — two ways

Web Push needs a **secure context (HTTPS)**. `localhost` counts as secure, so
you can test the whole send pipeline on this PC with no phone and no certs.

### A) Quickest — this PC's browser (no phone, no HTTPS setup)

1. Log in at `http://localhost:8000`.
2. Go to **Settings → Alerts → DroneDingo Push → Add a phone**. A QR appears and
   the link is shown beneath it (e.g. `http://localhost:8000/push?t=…`).
3. **Open that link in a new tab** in the same browser → **Enable alerts on this
   phone** → **Allow** notifications. You'll get an "enabled" notification.
4. Back on the dashboard: **Settings → Alerts → DroneDingo Push → Send test
   push**. A desktop notification appears.

That exercises the real pipeline: the appliance encrypts the payload, signs it
with its VAPID key, and the browser's push service delivers it. If this works,
the engine is proven.

> You can also just let the **simulator** trigger it: when a drone crosses the
> alert ring, a push fires (once per sighting).

### B) A real phone (needs the relay on HTTPS)

Phones can't open `http://localhost`, so use the relay:

1. **Deploy the relay** (`dronedingo-notify-site.zip`) to
   `notify.dronedingo.com.au` — docroot → `public/`, HTTPS on. Set the shared
   secret: env `DRONEDINGO_RELAY_KEY=<long-random-string>`.
2. **Point the local appliance at it** — in `config/dronedingo.yaml`:
   ```yaml
   push:
     public_url: "https://notify.dronedingo.com.au"
     relay_url:  "https://notify.dronedingo.com.au"
     relay_key:  "<the same long-random-string>"
   ```
   Restart the appliance (Ctrl+C, run again). It logs
   `DroneDingo Push relay poller started`.
3. On the dashboard: **Add a phone** → the QR now points at the relay (carrying
   the node id + this appliance's VAPID key). **Scan it with the phone.**
   - **Android:** open the link → Enable → Allow.
   - **iPhone (16.4+):** open in Safari → Share → **Add to Home Screen** → open
     it from there → Enable → Allow.
4. Within ~20 s the appliance polls the relay, ingests the subscription, and
   sends a **confirmation push to the phone**. Trigger more with **Send test
   push** or by letting the simulator cross the ring.

**Why this stays private:** the relay only brokers the subscription; your local
appliance still encrypts and sends every alert directly to the phone. No
detection data touches the relay. (Your PC does need normal internet access to
send — that's the outbound push.)

---

## Troubleshooting
- **"This page must be served over HTTPS"** on a phone → you opened an `http://`
  or LAN address. Use the relay (B).
- **Test push says "0 devices"** → no device registered yet; do A3 or B3 first.
- **Nothing arrives** → check the browser/phone allowed notifications, and that
  the PC has internet (sending is outbound to Apple/Google push services).
