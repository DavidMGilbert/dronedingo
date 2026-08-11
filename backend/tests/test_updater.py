"""Tests for the update channel: semver comparison and signature verification.

The signature test is the important one — the updater runs privileged, so a
forged or tampered release MUST be rejected.
"""
from __future__ import annotations
import base64
import hashlib
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import updater  # noqa: E402


class TestSemver(unittest.TestCase):
    def test_ordering(self):
        self.assertTrue(updater._newer("0.3.0", "0.2.9"))
        self.assertTrue(updater._newer("1.0.0", "0.9.9"))
        self.assertTrue(updater._newer("0.2.10", "0.2.9"))
        self.assertFalse(updater._newer("0.2.0", "0.2.0"))
        self.assertFalse(updater._newer("0.1.9", "0.2.0"))

    def test_prerelease_suffix_ignored(self):
        self.assertEqual(updater._semver("0.3.0-beta1"), (0, 3, 0))
        self.assertEqual(updater._semver("1.2"), (1, 2, 0))

    def test_garbage_is_safe(self):
        self.assertEqual(updater._semver("weird"), (0, 0, 0))


class TestSignatureVerification(unittest.TestCase):
    def setUp(self):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives import serialization
        self._priv = Ed25519PrivateKey.generate()
        raw_pub = self._priv.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw)
        self.pub_b64 = base64.b64encode(raw_pub).decode()
        self.payload = b"pretend release zip bytes " * 100
        self.digest = hashlib.sha256(self.payload).digest()

    def _sign(self, digest: bytes) -> str:
        return base64.b64encode(self._priv.sign(digest)).decode()

    def test_valid_signature_accepted(self):
        sig = self._sign(self.digest)
        self.assertTrue(updater._verify_signature(self.digest, sig, self.pub_b64))

    def test_tampered_payload_rejected(self):
        """A different digest (tampered zip) must fail the original signature."""
        sig = self._sign(self.digest)
        bad_digest = hashlib.sha256(self.payload + b"x").digest()
        self.assertFalse(updater._verify_signature(bad_digest, sig, self.pub_b64))

    def test_wrong_key_rejected(self):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives import serialization
        other = Ed25519PrivateKey.generate()
        other_pub = base64.b64encode(other.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw)).decode()
        sig = self._sign(self.digest)          # signed by self._priv
        self.assertFalse(updater._verify_signature(self.digest, sig, other_pub))

    def test_corrupt_signature_rejected(self):
        self.assertFalse(updater._verify_signature(
            self.digest, base64.b64encode(b"not a real signature").decode(),
            self.pub_b64))


if __name__ == "__main__":
    unittest.main(verbosity=2)
