# notify.dronedingo.com.au — DroneDingo Push registration relay

A small, standalone site that lets a phone register for **DroneDingo Push** when
the appliance itself isn't reachable over public HTTPS. It is deliberately dumb:
it serves the registration PWA over trusted HTTPS and **brokers push
subscriptions to the appliance**. It never receives, stores, or sees any
detection data — the appliance still encrypts and sends every alert itself.

## Why this exists

Web Push requires the registration page to be served from a **trusted HTTPS
origin**. A farm appliance on `http://192.168.x.x` can't be that. So the phone
loads this page (HTTPS), subscribes using the **appliance's** VAPID public key
(passed in the QR), and the resulting subscription is parked here until the
appliance collects it.

```
Appliance ──first boot──▶ /api/enroll.php   (claims its unique node id +
          registers a HASH of its own unique key; auth: enroll secret)

Phone ──scan QR──▶ notify.dronedingo.com.au  (this site, HTTPS PWA)
      subscribe with appliance's VAPID pubkey (from the QR)
      POST subscription ─▶ /api/register.php   (parked in a mailbox)

Appliance ──poll (its own key)──▶ /api/pending.php ─▶ takes its subscriptions
          ──▶ /api/ack.php  (clears them)
          ──▶ sends encrypted Web Push DIRECTLY to the phone (VAPID)

 ↑ Only the push subscription transits this site. Detection data never does.
```

## What transits this site

- The push **subscription** (endpoint URL + the phone's public keys). That's the
  address to deliver to — not the alert content. Alert bodies are encrypted by
  the appliance end-to-end; this site never composes or sees them.

## Deploy (any PHP 8+ host)

1. Upload the **contents** of `public/` into the site's docroot (e.g.
   `public_html/notify.dronedingo.com.au/`, so `index.php` is at the site root).
2. The SQLite database self-creates at `dd-data/notify.sqlite` inside the
   docroot; a shipped `dd-data/.htaccess` (plus a global rule) blocks it from the
   web, so it's inside `public_html` but not downloadable. PHP just needs to be
   able to write the `dd-data/` folder (the default on cPanel-style hosts). To
   place it elsewhere, set `DRONEDINGO_DB_PATH`. Tables auto-create.
3. Set the **enrollment secret** — either edit `ENROLL_SECRET_FALLBACK` in
   `public/api/_config.php` or set the env var `DRONEDINGO_ENROLL_SECRET`. This
   is the ONE shared secret; it only authorises an appliance to *claim a node*,
   never to read any node's data.
4. HTTPS is mandatory (Let's Encrypt). Web Push will not work otherwise.
5. Brand icons are already in `public/icons/`.

Appliances need no config editing — each one **self-enrolls** on first boot,
minting its own unique node id + key. Just provision the matching enroll secret
at install:

```bash
sudo DRONEDINGO_ENROLL_SECRET='<same value as this site>' bash deploy/install.sh
```

## Multi-tenant model

- Each appliance holds a **unique key**; the relay stores only its **hash**
  (`appliances.key_hash`). `pending.php` / `ack.php` authorise **per node**, so
  one appliance's key only ever unlocks its own mailbox.
- `enroll.php` is **claim-once**: once a node is enrolled, a different key is
  rejected (409), so nobody can hijack another appliance's node id. Re-enrolling
  with the same key is idempotent (survives a reinstall that kept `state.json`).
- The **enroll secret** only permits claiming/refreshing a node — it grants no
  access to parked registrations. Far less sensitive than a per-node key.
- Legacy: a fleet-wide `DRONEDINGO_RELAY_KEY` (if set) is still accepted for
  nodes that haven't enrolled yet, easing rollout. Leave it empty to require
  enrollment for everyone.

## Security notes

- `register.php` is unauthenticated (a phone posts to it), but a subscription is
  only *accepted* once the appliance validates the one-time registration token
  it minted — junk posts are discarded on the appliance and never become live
  subscriptions.
