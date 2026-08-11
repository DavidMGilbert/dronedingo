"""Validate the DroneDingo Push crypto: RFC 8291 encryption round-trip and the
RFC 8292 VAPID JWT. This is hand-rolled security code, so these prove it against
the spec's own inverse operations before it ever runs against a real device.
"""
from __future__ import annotations
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app import push  # noqa: E402


def _fake_subscription():
    """A browser-side subscription: UA key pair + auth secret."""
    ua_priv = ec.generate_private_key(ec.SECP256R1())
    p256dh = ua_priv.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    auth = os.urandom(16)
    return ua_priv, push.b64u(p256dh), push.b64u(auth)


def _decrypt(body: bytes, ua_priv, auth_b64: str) -> bytes:
    """Inverse of push._encrypt — the operation the phone performs."""
    salt = body[:16]
    idlen = body[20]
    server_pub_bytes = body[21:21 + idlen]
    ciphertext = body[21 + idlen:]
    ua_public_bytes = ua_priv.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    server_pub = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), server_pub_bytes)
    shared = ua_priv.exchange(ec.ECDH(), server_pub)
    ikm = HKDF(algorithm=hashes.SHA256(), length=32, salt=push.b64u_dec(auth_b64),
               info=b"WebPush: info\x00" + ua_public_bytes + server_pub_bytes).derive(shared)
    cek = HKDF(algorithm=hashes.SHA256(), length=16, salt=salt,
               info=b"Content-Encoding: aes128gcm\x00").derive(ikm)
    nonce = HKDF(algorithm=hashes.SHA256(), length=12, salt=salt,
                 info=b"Content-Encoding: nonce\x00").derive(ikm)
    plain = AESGCM(cek).decrypt(nonce, ciphertext, None)
    return plain.rstrip(b"\x02")


class TestWebPushEncryption(unittest.TestCase):
    def test_round_trip(self):
        ua_priv, p256dh, auth = _fake_subscription()
        msg = json.dumps({"title": "Drone detected", "body": "147 m NE"}).encode()
        body = push._encrypt(msg, p256dh, auth)
        self.assertEqual(_decrypt(body, ua_priv, auth), msg)

    def test_header_structure(self):
        ua_priv, p256dh, auth = _fake_subscription()
        body = push._encrypt(b"x", p256dh, auth)
        self.assertEqual(len(body[:16]), 16)          # salt
        self.assertEqual(body[20], 65)                # server key id length
        self.assertGreater(len(body), 16 + 4 + 1 + 65)

    def test_distinct_salt_each_time(self):
        ua_priv, p256dh, auth = _fake_subscription()
        a = push._encrypt(b"same", p256dh, auth)
        b = push._encrypt(b"same", p256dh, auth)
        self.assertNotEqual(a[:16], b[:16])           # fresh salt -> different ciphertext

    def test_wrong_auth_fails_to_decrypt(self):
        ua_priv, p256dh, _ = _fake_subscription()
        body = push._encrypt(b"secret", p256dh, push.b64u(os.urandom(16)))
        with self.assertRaises(Exception):
            _decrypt(body, ua_priv, push.b64u(os.urandom(16)))


class TestVapidJwt(unittest.TestCase):
    def test_jwt_verifies_and_claims(self):
        push.ensure_keys()
        auth = push._vapid_auth("https://fcm.googleapis.com/fcm/send/abc123")
        self.assertTrue(auth.startswith("vapid t="))
        parts = dict(p.strip().split("=", 1) for p in auth[len("vapid "):].split(","))
        jwt, k = parts["t"], parts["k"]
        h, b, sig = jwt.split(".")

        pub = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), push.b64u_dec(k))
        raw = push.b64u_dec(sig)
        der = encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big"))
        pub.verify(der, f"{h}.{b}".encode(), ec.ECDSA(hashes.SHA256()))   # raises if invalid

        claims = json.loads(push.b64u_dec(b))
        self.assertEqual(claims["aud"], "https://fcm.googleapis.com")
        self.assertIn("exp", claims)
        self.assertTrue(str(claims["sub"]).startswith("mailto:"))

    def test_public_key_is_uncompressed_point(self):
        self.assertEqual(push.b64u_dec(push.public_key_b64())[0], 0x04)  # uncompressed
        self.assertEqual(len(push.b64u_dec(push.public_key_b64())), 65)


if __name__ == "__main__":
    unittest.main(verbosity=2)
