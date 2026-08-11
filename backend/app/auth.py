"""Authentication — email + password login gating the whole UI.

Single admin account for the appliance model, designed to extend to per-user
accounts for a managed/SaaS deployment later. Credentials are the admin's email
(username) and a password stored only as a PBKDF2-HMAC-SHA256 hash in
data/state.json — never in the YAML, never in git.

Credentials are set at installation (installer) or, if none exist, on first
visit to the web UI. A locked-out admin is recovered from the Pi console with
deploy/reset-admin.sh, which calls reset()/set_credentials() here.
"""
from __future__ import annotations
import hashlib
import hmac
import re
import secrets

from . import config as cfg

_ALGO = "pbkdf2_sha256"
_ITERATIONS = 240_000
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _norm_email(email: str) -> str:
    return (email or "").strip().lower()


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


# --- credentials -----------------------------------------------------------
def is_configured() -> bool:
    return bool((cfg.get_state().get("auth") or {}).get("hash"))


def get_email() -> str | None:
    return (cfg.get_state().get("auth") or {}).get("email")


def _hash(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", (password or "").encode(), bytes.fromhex(salt), _ITERATIONS).hex()


def set_credentials(email: str, password: str) -> None:
    email = _norm_email(email)
    if not _EMAIL_RE.match(email):
        raise ValueError("Enter a valid email address.")
    if not password or len(password) < 8:
        raise ValueError("Password must be at least 8 characters.")
    salt = secrets.token_hex(16)
    state = cfg.get_state()
    auth = state.get("auth") or {}
    auth.update({"email": email, "algo": _ALGO, "salt": salt,
                 "hash": _hash(password, salt), "iterations": _ITERATIONS})
    cfg.update_state(auth=auth)


def verify(email: str, password: str) -> bool:
    auth = cfg.get_state().get("auth") or {}
    if not auth.get("hash"):
        return False
    email_ok = hmac.compare_digest(_norm_email(email), auth.get("email", ""))
    calc = hashlib.pbkdf2_hmac(
        "sha256", (password or "").encode(),
        bytes.fromhex(auth["salt"]), int(auth.get("iterations", _ITERATIONS))).hex()
    pass_ok = hmac.compare_digest(calc, auth["hash"])
    return email_ok and pass_ok


def change_password(current: str, new: str) -> None:
    email = get_email() or ""
    if not verify(email, current):
        raise PermissionError("Current password is incorrect.")
    set_credentials(email, new)


def change_email(new_email: str, current_password: str) -> None:
    email = get_email() or ""
    if not verify(email, current_password):
        raise PermissionError("Password is incorrect.")
    new_email = _norm_email(new_email)
    if not _EMAIL_RE.match(new_email):
        raise ValueError("Enter a valid email address.")
    state = cfg.get_state()
    auth = state.get("auth") or {}
    auth["email"] = new_email
    cfg.update_state(auth=auth)


def reset() -> None:
    """Clear the admin credentials (keeps the session secret). Forces the
    first-run 'create admin' flow on next visit. Used by reset-admin.sh."""
    state = cfg.get_state()
    auth = state.get("auth") or {}
    for k in ("email", "salt", "hash", "iterations", "algo"):
        auth.pop(k, None)
    cfg.update_state(auth=auth)
