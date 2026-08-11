"""DroneDingo Push — proprietary Web Push, sent directly from the appliance.

No ntfy, no third-party app, no Apple/Google developer account. The appliance
holds a self-generated VAPID key pair, stores browser push subscriptions, and
sends encrypted Web Push notifications itself:

* **VAPID** (RFC 8292) authenticates the appliance to the browser's push
  service — this is what replaces any need for an FCM server key or APNs
  certificate. You generate the key; nobody issues it to you.
* **aes128gcm** message encryption (RFC 8291 / RFC 8188) means the push
  service only ever sees ciphertext — the alert content is end-to-end encrypted
  between the appliance and the phone.

The only shared infrastructure is the OS push transport (APNs/FCM) that every
app on the phone uses; detection data never passes through it in the clear, and
never touches any DroneDingo cloud in this mode.

Built on `cryptography` (already a dependency) — no copyleft libraries.
"""
from __future__ import annotations
import base64
import json
import logging
import os
import secrets
import struct
import threading
import time
import urllib.request
from urllib.parse import urlparse

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from . import config as cfg

log = logging.getLogger("dronedingo")
# Reentrant: several helpers hold the lock and then call ensure_keys(), which
# takes it again. A plain Lock would deadlock.
_lock = threading.RLock()


# --------------------------------------------------------------------------
# base64url helpers (unpadded, per JOSE)
# --------------------------------------------------------------------------
def b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def b64u_dec(s: str) -> bytes:
    s = s + "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s)


# --------------------------------------------------------------------------
# VAPID key management (persisted in state.json)
# --------------------------------------------------------------------------
def _load_push_state() -> dict:
    return (cfg.get_state().get("push") or {})


def _save_push_state(push: dict) -> None:
    cfg.update_state(push=push)


def ensure_keys() -> dict:
    """Generate the VAPID key pair once; return the push state."""
    with _lock:
        push = _load_push_state()
        if not push.get("vapid_private_pem"):
            priv = ec.generate_private_key(ec.SECP256R1())
            pem = priv.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption()).decode()
            pub_raw = priv.public_key().public_bytes(
                serialization.Encoding.X962,
                serialization.PublicFormat.UncompressedPoint)
            push["vapid_private_pem"] = pem
            push["vapid_public_b64"] = b64u(pub_raw)
            push.setdefault("subscriptions", [])
            _save_push_state(push)
        return push


def public_key_b64() -> str:
    """The applicationServerKey the PWA subscribes with (base64url raw point)."""
    return ensure_keys()["vapid_public_b64"]


def _private_key() -> ec.EllipticCurvePrivateKey:
    pem = ensure_keys()["vapid_private_pem"]
    return serialization.load_pem_private_key(pem.encode(), password=None)


# --------------------------------------------------------------------------
# subscription store
# --------------------------------------------------------------------------
def add_subscription(sub: dict) -> None:
    endpoint = sub.get("endpoint")
    keys = sub.get("keys") or {}
    if not endpoint or not keys.get("p256dh") or not keys.get("auth"):
        raise ValueError("invalid subscription")
    with _lock:
        push = ensure_keys()
        subs = [s for s in push.get("subscriptions", []) if s.get("endpoint") != endpoint]
        subs.append({"endpoint": endpoint, "keys": {"p256dh": keys["p256dh"], "auth": keys["auth"]},
                     "added": time.time(), "ua": sub.get("ua", "")})
        push["subscriptions"] = subs
        _save_push_state(push)


def remove_subscription(endpoint: str) -> None:
    with _lock:
        push = ensure_keys()
        push["subscriptions"] = [s for s in push.get("subscriptions", []) if s.get("endpoint") != endpoint]
        _save_push_state(push)


def subscription_count() -> int:
    return len(_load_push_state().get("subscriptions", []))


# --------------------------------------------------------------------------
# registration tokens — let a phone register via the QR without logging in
# --------------------------------------------------------------------------
def new_reg_token(ttl: int = 900) -> str:
    with _lock:
        push = ensure_keys()
        now = time.time()
        toks = {k: v for k, v in (push.get("reg_tokens") or {}).items() if v > now}
        tok = secrets.token_urlsafe(9)
        toks[tok] = now + ttl
        push["reg_tokens"] = toks
        _save_push_state(push)
        return tok


def check_reg_token(tok: str) -> bool:
    if not tok:
        return False
    toks = _load_push_state().get("reg_tokens") or {}
    return tok in toks and toks[tok] > time.time()


# --------------------------------------------------------------------------
# RFC 8291 message encryption (aes128gcm)
# --------------------------------------------------------------------------
def _encrypt(payload: bytes, p256dh_b64: str, auth_b64: str) -> bytes:
    ua_public_bytes = b64u_dec(p256dh_b64)          # 65-byte uncompressed point
    auth_secret = b64u_dec(auth_b64)                # 16 bytes
    ua_pub = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_public_bytes)

    server_priv = ec.generate_private_key(ec.SECP256R1())
    server_pub_bytes = server_priv.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    shared = server_priv.exchange(ec.ECDH(), ua_pub)

    # IKM per RFC 8291 §3.4
    key_info = b"WebPush: info\x00" + ua_public_bytes + server_pub_bytes
    ikm = HKDF(algorithm=hashes.SHA256(), length=32, salt=auth_secret,
               info=key_info).derive(shared)

    salt = os.urandom(16)
    cek = HKDF(algorithm=hashes.SHA256(), length=16, salt=salt,
               info=b"Content-Encoding: aes128gcm\x00").derive(ikm)
    nonce = HKDF(algorithm=hashes.SHA256(), length=12, salt=salt,
                 info=b"Content-Encoding: nonce\x00").derive(ikm)

    # single record: plaintext + 0x02 delimiter (RFC 8188)
    ciphertext = AESGCM(cek).encrypt(nonce, payload + b"\x02", None)

    record_size = 4096
    header = salt + struct.pack("!I", record_size) + bytes([len(server_pub_bytes)]) + server_pub_bytes
    return header + ciphertext


def _vapid_auth(endpoint: str) -> str:
    u = urlparse(endpoint)
    aud = f"{u.scheme}://{u.netloc}"
    subject = (cfg.load().get("push") or {}).get("subject") or "mailto:admin@dronedingo.local"
    header = b64u(json.dumps({"typ": "JWT", "alg": "ES256"}, separators=(",", ":")).encode())
    body = b64u(json.dumps({"aud": aud, "exp": int(time.time()) + 12 * 3600, "sub": subject},
                           separators=(",", ":")).encode())
    signing_input = f"{header}.{body}".encode()
    der = _private_key().sign(signing_input, ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der)
    raw_sig = r.to_bytes(32, "big") + s.to_bytes(32, "big")
    jwt = f"{header}.{body}.{b64u(raw_sig)}"
    return f"vapid t={jwt}, k={public_key_b64()}"


def _send_one(sub: dict, payload: bytes, ttl: int = 120) -> int:
    body = _encrypt(payload, sub["keys"]["p256dh"], sub["keys"]["auth"])
    req = urllib.request.Request(sub["endpoint"], data=body, method="POST", headers={
        "Content-Encoding": "aes128gcm",
        "Content-Type": "application/octet-stream",
        "TTL": str(ttl),
        "Authorization": _vapid_auth(sub["endpoint"]),
    })
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.status


def notify(title: str, body: str, data: dict | None = None) -> dict:
    """Send a notification to every registered device. Prunes dead endpoints."""
    payload = json.dumps({"title": title, "body": body, "data": data or {}}).encode()
    push = ensure_keys()
    subs = list(push.get("subscriptions", []))
    if not subs:
        return {"ok": False, "sent": 0, "message": "No devices registered."}
    sent, dead = 0, []
    for sub in subs:
        try:
            status = _send_one(sub, payload)
            if 200 <= status < 300:
                sent += 1
        except urllib.error.HTTPError as exc:
            if exc.code in (404, 410):      # subscription gone
                dead.append(sub["endpoint"])
            else:
                log.warning("push send failed (%s): %s", exc.code, sub["endpoint"][:60])
        except Exception as exc:
            log.warning("push send error: %s", exc)
    for ep in dead:
        remove_subscription(ep)
    return {"ok": sent > 0, "sent": sent, "pruned": len(dead), "devices": len(subs)}


def enabled() -> bool:
    return bool((cfg.load().get("push") or {}).get("enabled", True))


# --------------------------------------------------------------------------
# relay poller — collect subscriptions registered via notify.dronedingo.com.au
# --------------------------------------------------------------------------
def _relay() -> tuple[str, str]:
    p = cfg.load().get("push") or {}
    base = (p.get("relay_url") or p.get("public_url") or "").rstrip("/")
    return base, (p.get("relay_key") or "")


def _relay_post(path: str, payload: dict, timeout: int = 15) -> dict:
    base, _ = _relay()
    req = urllib.request.Request(base + path, method="POST",
                                 data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def poll_relay_once() -> int:
    """Fetch subscriptions parked for this node, ingest the valid ones, ack all.
    A subscription is only accepted if its one-time token was minted here."""
    base, key = _relay()
    if not base or not key:
        return 0
    node = cfg.get_node_id()
    try:
        data = _relay_post("/api/pending.php", {"node": node, "key": key})
    except Exception as exc:
        log.debug("relay poll failed: %s", exc)
        return 0
    pending = data.get("pending") or []
    if not pending:
        return 0

    ack_ids, welcomed = [], []
    for row in pending:
        if row.get("id"):
            ack_ids.append(row["id"])
        if not check_reg_token(row.get("token", "")):
            continue                      # junk or expired token — dropped on ack
        try:
            add_subscription(row["subscription"])
            welcomed.append(row["subscription"])
        except Exception:
            pass
    try:
        _relay_post("/api/ack.php", {"key": key, "ids": ack_ids})
    except Exception as exc:
        log.debug("relay ack failed: %s", exc)

    for sub in welcomed:                  # confirm on the newly-registered phone
        try:
            _send_one(sub, json.dumps({"title": "DroneDingo",
                                       "body": "Alerts enabled on this phone."}).encode())
        except Exception:
            pass
    if welcomed:
        log.info("registered %d device(s) via relay", len(welcomed))
    return len(welcomed)


def start_poller() -> None:
    base, key = _relay()
    if not (base and key):
        log.info("DroneDingo Push relay not configured; devices register locally only")
        return

    def _loop():
        while True:
            try:
                poll_relay_once()
            except Exception as exc:
                log.warning("relay poller error: %s", exc)
            time.sleep(20)

    threading.Thread(target=_loop, name="push-relay-poller", daemon=True).start()
    log.info("DroneDingo Push relay poller started -> %s", base)
