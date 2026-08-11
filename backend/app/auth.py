"""Authentication — session login gating the whole UI.

Single admin account for the appliance model, designed to extend to per-user
accounts for a managed/SaaS deployment later. The password is stored only as a
PBKDF2-HMAC-SHA256 hash in data/state.json (never in the YAML, never in git).
On first visit, when no password is set, the login page becomes a "create
admin password" page.

The session secret is generated once and persisted, so logins survive restarts
but a fresh install starts clean.
"""
from __future__ import annotations
import hashlib
import hmac
import secrets

from . import config as cfg

_ALGO = "pbkdf2_sha256"
_ITERATIONS = 240_000


# --- session secret --------------------------------------------------------
def session_secret() -> str:
    state = cfg.get_state()
    auth = state.get("auth") or {}
    sec = auth.get("secret")
    if not sec:
        sec = secrets.token_hex(32)
        auth["secret"] = sec
        cfg.update_state(auth=auth)
    return sec


# --- password --------------------------------------------------------------
def is_configured() -> bool:
    return bool((cfg.get_state().get("auth") or {}).get("hash"))


def set_password(password: str) -> None:
    if not password or len(password) < 8:
        raise ValueError("Password must be at least 8 characters.")
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), bytes.fromhex(salt), _ITERATIONS).hex()
    state = cfg.get_state()
    auth = state.get("auth") or {}
    auth.update({"algo": _ALGO, "salt": salt, "hash": digest,
                 "iterations": _ITERATIONS})
    cfg.update_state(auth=auth)


def verify(password: str) -> bool:
    auth = cfg.get_state().get("auth") or {}
    if not auth.get("hash"):
        return False
    calc = hashlib.pbkdf2_hmac(
        "sha256", (password or "").encode(),
        bytes.fromhex(auth["salt"]), int(auth.get("iterations", _ITERATIONS))).hex()
    # Constant-time comparison.
    return hmac.compare_digest(calc, auth["hash"])


def change_password(current: str, new: str) -> None:
    if not verify(current):
        raise PermissionError("Current password is incorrect.")
    set_password(new)
