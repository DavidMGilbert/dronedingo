# DroneDingo update protocol

How an appliance updates itself from **dronedingo.com.au** instead of GitHub.
This is the contract the website must implement; the appliance side is built to
match it. Private source never leaves the build machine.

## Overview

```
 Appliance                          dronedingo.com.au
 ---------                          -----------------
 1. GET  /api/v1/updates/latest ─▶  returns manifest JSON (latest release)
 2. compare versions (semver)
 3. GET  <artifact.url>         ─▶  returns the release .zip
 4. verify sha256 (+ signature)
 5. stage, back up, swap, restart
```

The appliance **never auto-installs** — it checks (optionally on a schedule),
surfaces "update available" in the admin UI, and installs only when an operator
clicks. Nothing about this needs GitHub.

---

## 1. Check endpoint

```
GET https://dronedingo.com.au/api/v1/updates/latest
        ?channel=stable          # or "beta"
        &current=0.2.0           # appliance's running version
        &node=dingo-01           # node id (for your telemetry/metering)

Headers:
  Authorization: Bearer <appliance_token>     # if you gate downloads (see §5)
  User-Agent: DroneDingo/0.2.0 (dingo-01)
```

**Response `200`** — always return the latest release for the channel; the
appliance decides whether it is newer:

```json
{
  "version": "0.3.0",
  "channel": "stable",
  "released": "2026-08-20T12:00:00Z",
  "notes": "Acoustic night detector; OcuSync 4 fingerprints; bug fixes.",
  "min_upgradable_from": "0.1.0",
  "artifact": {
    "url": "https://dl.dronedingo.com.au/releases/dronedingo-0.3.0.zip",
    "size": 5242880,
    "sha256": "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
    "signature": "base64(ed25519 signature of the 32 raw sha256 bytes)",
    "signature_alg": "ed25519"
  }
}
```

- `signature`/`signature_alg` are **optional but strongly recommended** (§4).
- `min_upgradable_from` (optional): if the appliance's version is older than
  this, it must step through an intermediate release first.
- **`204 No Content`** or **`404`** ⇒ "no releases for this channel".
- **`401`** ⇒ token required and missing/invalid.

Versions are **semantic versions**; the appliance installs only if
`manifest.version > current`.

---

## 2. Artifact download

```
GET <artifact.url>
Headers:
  Authorization: Bearer <appliance_token>     # if gated
```

Returns the raw `.zip`. HTTP range/resume is nice-to-have, not required.
Host it on the CDN/path of your choice — the appliance only knows the URL from
the manifest, so you can move releases freely.

---

## 3. Release .zip layout

The archive contains the application tree **at its root** (no wrapping folder):

```
VERSION                         # exactly the version string, e.g. "0.3.0"
backend/                        # the app
frontend/
deploy/
config/dronedingo.example.yaml  # shipped DEFAULTS only
```

Rules:
- **MUST NOT** contain `data/` (the runtime SQLite DB + state.json).
- **MUST NOT** contain `config/dronedingo.yaml` — that is the operator's own
  config and is never overwritten. Ship defaults as
  `config/dronedingo.example.yaml`; the appliance merges any *new* keys.
- `VERSION` at the root must match `manifest.version`.
- Build it straight from a clean checkout at the tagged release commit.

---

## 4. Integrity & signing (why this matters)

The installer runs **as root**. If someone can substitute the zip — a breached
web host, a hijacked CDN, a MITM — they own every appliance in the field. Two
defences, layered:

1. **`sha256` (mandatory).** The appliance rejects the download unless the hash
   matches the manifest.
2. **Ed25519 signature (recommended).** You generate a keypair **once**:
   - the **private key stays on your release/build machine** and signs the
     sha256 of each release;
   - the **public key** is baked into the appliance config
     (`updates.public_key`).

   Because the private key never leaves your build machine, a compromised
   website *cannot* forge a release. This is the single most important control
   for a fleet you can't physically reach.

Signing is opt-in on the appliance: if `updates.public_key` is set, an unsigned
or bad-signature release is refused; if it is not set, the appliance falls back
to sha256-only (fine for early testing, not for production).

---

## 5. Download authentication (your choice)

| Option | Website work | What it buys you |
|---|---|---|
| **Open + signed** | none — serve the zip publicly | integrity via signature, but the binaries are world-downloadable |
| **Per-appliance token** (recommended) | check `Authorization: Bearer` on both endpoints | licensing, per-device revocation, metering, private binaries |

For a paid product, issue a **per-appliance token at provisioning** and store
it in `updates.token`. The website validates it, can revoke a single device,
and can tie updates to an active licence. Signing (§4) still provides integrity
independently of the token.

---

## 6. Appliance config (`config/dronedingo.yaml`)

```yaml
updates:
  channel: "stable"
  check_url: "https://dronedingo.com.au/api/v1/updates/latest"
  token: null            # per-appliance bearer token (from provisioning)
  public_key: null       # base64 Ed25519 public key that signs releases
  auto_check: true       # poll on a schedule; NEVER auto-install
```

---

## 7. What the website team must build

1. A releases store (S3/R2/any static host) holding `dronedingo-<ver>.zip`.
2. The **check endpoint** (§1) returning the manifest JSON for a channel.
3. Optionally, **token validation** (§5) on the check + download.
4. A release step that, per version: builds the zip (§3), computes `sha256`,
   signs it (§4), and publishes the manifest.

Everything else — download, verify, stage, back up, atomic swap, restart,
rollback on failure — is handled on the appliance.

## 8. Reference: signing a release (build machine)

```bash
# one-time keypair (keep dronedingo-release.key SECRET, off the appliances)
openssl genpkey -algorithm ed25519 -out dronedingo-release.key
openssl pkey -in dronedingo-release.key -pubout -out dronedingo-release.pub

# per release
sha256sum dronedingo-0.3.0.zip | cut -d' ' -f1 | xxd -r -p > digest.bin
openssl pkeyutl -sign -inkey dronedingo-release.key -rawin -in digest.bin \
  | base64 -w0                       # -> manifest.artifact.signature
```

The base64 public key from `dronedingo-release.pub` goes into every appliance's
`updates.public_key`.
