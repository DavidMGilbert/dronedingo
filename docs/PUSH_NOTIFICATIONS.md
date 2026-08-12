# Push notifications — design history (superseded)

> **Superseded.** This document captured an earlier plan that delivered phone
> alerts through an ntfy broker ("our own ntfy" — a self-hosted ntfy server plus
> a QR-of-topic registration flow). That approach has been **replaced by
> DroneDingo Push**: the appliance holds its own VAPID signing keys and sends the
> alert directly to the phone's push service, end-to-end encrypted (RFC 8291).
> There is no ntfy app, no shared-secret topic, and no third-party broker in the
> path. The ntfy code and settings have been removed from the appliance.
>
> For the current system, see:
> - [PUSH_SETUP.md](PUSH_SETUP.md) — how to register phones and configure it
> - [ALERTS.md](ALERTS.md) — alert behaviour and tuning
>
> The original ntfy notes are retained below only as design history.

---

## Why the broker question existed

An appliance on a farm LAN cannot push to a phone that is elsewhere without a
publicly reachable HTTPS endpoint in the middle. The old plan solved this with a
self-hosted ntfy server; DroneDingo Push solves the same constraint with the
optional **notify.dronedingo.com.au relay**, which only parks a phone's push
subscription at registration time — detection data never passes through it, and
the appliance sends each alert directly and encrypted.
