# DroneDingo Push — phone setup (Android & iOS)

DroneDingo Push is **proprietary and appliance-direct**: the appliance holds its
own signing keys and sends the alert itself, end-to-end encrypted. No ntfy, no
DroneDingo cloud, no third-party app.

## Do I need Apple or Google services / accounts?

**No.** No Apple Developer account, no Google/Firebase project, no App Store or
Play Store, nothing paid.

This works because of **Web Push + VAPID**: the appliance generates its own key
pair and uses it to authenticate directly to the browser's push service. The
notification body is encrypted (RFC 8291), so that push service only ever sees
ciphertext. Those push services (Apple's for Safari, Google's for Chrome) are
the same OS pipes every app on the phone uses — you don't register with them,
pay them, or get a certificate from them. They're just the delivery road.

> The only thing that *would* need Apple/Google developer accounts is a **native
> app** in the stores (Apple Developer $99/yr + APNs, and a Firebase/FCM project).
> The PWA path deliberately avoids all of that.

## One-time setup

On the **dashboard** (a laptop/desktop): Settings → Alerts → **DroneDingo Push** →
**Add a phone**. A QR code appears (valid ~15 minutes).

### Android (Chrome / Edge / Firefox)
1. Scan the QR with the phone camera; open the link.
2. Tap **Enable alerts on this phone**, then **Allow** notifications.
3. A confirmation notification arrives. Done.
4. Optional but recommended: browser menu → **Add to Home screen** for reliability.

*No Google account or Firebase needed.*

### iPhone / iPad (iOS 16.4 or later)
1. Scan the QR; the link opens in Safari.
2. Tap the **Share** icon → **Add to Home Screen**. (iOS only delivers Web Push
   to an installed app — a plain Safari tab won't receive alerts. This is Apple's
   rule, not ours.)
3. Open **DroneDingo** from the Home Screen.
4. Tap **Enable alerts on this phone**, then **Allow** notifications. Done.

*No Apple ID or Developer account needed.*

Repeat "Add a phone" for each device (farmer, manager, a neighbour…). Test any
time from Settings → **Send test push**.

## The one requirement: HTTPS

Web Push only works from an **https://** origin the phone trusts. A bare LAN
address (`http://192.168.x.x`) will be refused by the phone browser, and the
registration page will say so. Options:

1. **Give the appliance a hostname + certificate** (Let's Encrypt via your
   domain, or a reverse proxy in front of it). Then everything — registration
   *and* sending — stays on the appliance.
2. **Host the registration page at your alerts site** (e.g.
   `https://app.dronedingo.com.au`) and set `push.public_url` in config to it.
   The appliance still *sends* the push directly; the cloud only serves the
   static registration page over trusted HTTPS. Detection data never touches it.

Until an HTTPS origin is configured, use the **ntfy** channel (Settings →
Alerts → ntfy) as the interim — it needs no HTTPS on the appliance.

## How it works (for the record)

```
Phone (PWA)                         Appliance
scan QR ─▶ open registration page
tap Enable ─▶ browser push subscription (your VAPID public key)
subscription ───────────────────▶  stored on the appliance (data/state.json)

drone breaches ring ─▶ appliance encrypts (RFC 8291) + signs (VAPID/RFC 8292)
                       ─▶ OS push pipe ─▶ phone ─▶ service worker shows the alert
                       (tap → opens the operator's location on a map)
```

Everything in that diagram is DroneDingo code and keys except the "OS push pipe".
