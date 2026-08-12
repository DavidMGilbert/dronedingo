"""Make outbound HTTPS verify certificates on every platform.

Windows Python has no usable CA store for urllib by default (Apple/Google push
endpoints fail with CERTIFICATE_VERIFY_FAILED), and even some minimal Linux
images lack a complete bundle. Pin the certifi CA bundle as the default HTTPS
context so every urllib request in the app — push, relay, updates — can
verify. Importing this module applies the fix as a side effect.
"""
from __future__ import annotations
import ssl

try:
    import certifi
    SSL_CONTEXT: ssl.SSLContext | None = ssl.create_default_context(cafile=certifi.where())
    # urllib.request calls ssl._create_default_https_context() with no args.
    ssl._create_default_https_context = lambda *a, **k: SSL_CONTEXT
except Exception:                     # pragma: no cover — fall back to system store
    SSL_CONTEXT = None
