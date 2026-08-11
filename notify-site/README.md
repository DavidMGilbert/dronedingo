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
Phone ──scan QR──▶ notify.dronedingo.com.au  (this site, HTTPS PWA)
      subscribe with appliance's VAPID pubkey (from the QR)
      POST subscription ─▶ /api/register.php   (parked in a mailbox)

Appliance ──poll (auth)──▶ /api/pending.php ─▶ takes its subscriptions
          ──▶ /api/ack.php  (clears them)
          ──▶ sends encrypted Web Push DIRECTLY to the phone (VAPID)

 ↑ Only the push subscription transits this site. Detection data never does.
```

## What transits this site

- The push **subscription** (endpoint URL + the phone's public keys). That's the
  address to deliver to — not the alert content. Alert bodies are encrypted by
  the appliance end-to-end; this site never composes or sees them.

## Deploy (any PHP 8+ host)

1. Point the `notify.dronedingo.com.au` docroot at `public/`.
2. Ensure PHP can write a data dir one level **above** the docroot (the SQLite
   mailbox lives at `../notify-data/notify.sqlite`, outside the web root).
3. Set the shared secret the appliances use to poll — either edit
   `public/api/_config.php` or set the env var `DRONEDINGO_RELAY_KEY`.
4. HTTPS is mandatory (Let's Encrypt). Web Push will not work otherwise.
5. Copy your brand icons into `public/icons/` (mark-dark.png, icon-192.png,
   icon-512.png, favicon-64.png) — or they're already included here.

On each appliance set, in `config/dronedingo.yaml`:

```yaml
push:
  public_url: "https://notify.dronedingo.com.au"   # where the PWA lives
  relay_url:  "https://notify.dronedingo.com.au"   # where the appliance polls
  relay_key:  "the-same-shared-secret"             # matches this site
```

## Security notes

- `register.php` is unauthenticated (a phone posts to it), but a subscription is
  only *accepted* once the appliance validates the one-time registration token
  it minted — junk posts are discarded on the appliance and never become live
  subscriptions.
- `pending.php` / `ack.php` require the shared `relay_key`; without it nobody can
  read parked subscriptions.
- Start with one fleet-wide `relay_key`; move to per-node keys when you add
  provisioning. Rotate by changing it here and on the appliances.
