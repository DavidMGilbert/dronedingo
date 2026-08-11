# Push notifications — device registration & "our own ntfy"

Goal: a farmer registers a phone in appliance **Settings → Alerts** — by scanning
a **QR code** or entering a **phone number** — and gets push alerts when a drone
breaches the ring, without depending on the public ntfy.sh service.

This is a delivery-transport question. The honest constraint: **an appliance on a
farm LAN cannot push to a phone that is elsewhere without a public broker in the
middle.** So the design is about *which broker* and *how the phone registers*.

## Shipped now: QR registration (works today)

Settings → Alerts shows a **QR of the alert channel URL** (`<ntfy-server>/<topic>`).
The farmer scans it with the ntfy app (or phone camera) and is subscribed. This
already gives the "register by QR" experience and works against **either** the
public ntfy.sh **or a self-hosted ntfy** — no code change to switch, just point
`alerts.ntfy_server` at your own host.

- Pro: zero new infrastructure; instant; the debounced one-alert-per-sighting
  logic and operator-location deep link already work.
- Con: relies on the ntfy app being installed; topic is a shared secret.

## Recommended path

### Phase 1 (now) — self-hosted ntfy + QR   ✅ this is "our own ntfy"
Run the open-source **ntfy server** on infrastructure you control (a small VPS,
or `push.dronedingo.com.au`). It's a single Go binary / Docker container:

```
docker run -p 80:80 -v /var/lib/ntfy:/var/lib/ntfy binwiederhier/ntfy serve
```

Point every appliance at it (`alerts.ntfy_server: https://push.dronedingo.com.au`)
and keep the QR flow. Now the whole pipeline is yours end-to-end; ntfy.sh is out
of the loop. You can enable auth/ACLs on the ntfy server so topics aren't world-
readable. **Lowest effort, fully "own", and it reuses everything already built.**

### Phase 2 (SaaS) — DroneDingo relay + Web Push
When appliances phone home (the SaaS direction), replace the topic model with a
**device registry + Web Push (VAPID)**:

1. Appliance shows a QR that opens `https://app.dronedingo.com.au/register?node=<id>&token=<t>`.
2. That URL is a **PWA**; the phone subscribes to Web Push (one tap, VAPID key),
   and the subscription is stored against the node in your cloud.
3. Detections post to the DroneDingo relay, which fans out Web Push to every
   registered device for that node.

- Pro: no third-party app, real per-device management (revoke, name, mute),
  native-feeling notifications, ties into billing/licensing.
- Con: needs the cloud relay + a PWA; iOS requires "Add to Home Screen"
  (iOS 16.4+) for Web Push. This is a real project, not a config change.

## On phone-number registration (SMS)

Entering a phone number implies **SMS**, which needs a paid gateway (Twilio,
MessageBird, etc.) with per-message cost and per-account credentials. Baking SMS
into each appliance is a poor fit (cost, credential sprawl, no delivery once the
farm's internet drops). **Recommendation:** don't put SMS on the appliance.
Offer phone-number/SMS **through the Phase-2 cloud relay** as a paid tier — the
relay holds one gateway account and meters it. Until then, QR + push covers the
"register a device" need without recurring cost.

## Summary

| Option | Effort | "Ours"? | Cost | When |
|---|---|---|---|---|
| Public ntfy.sh + QR | done | no (public broker) | free | fallback |
| **Self-hosted ntfy + QR** | **low** | **yes** | ~$5/mo VPS | **do this next** |
| Cloud relay + Web Push (QR→PWA) | high | yes | hosting | SaaS phase |
| SMS by phone number | med + ongoing | via relay only | per-message | paid tier, later |

**Next concrete step when you're ready:** stand up an ntfy container on a small
VPS or `push.dronedingo.com.au`, set `alerts.ntfy_server` to it, and the QR flow
is your own push system. I can add ntfy **access tokens/ACLs** support to the
appliance config so self-hosted topics are authenticated, if you want that.
