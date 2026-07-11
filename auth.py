"""auth.py — email + password accounts for the portal.

Two roles:
    admin  — the platform owner (Sai). Seeded from ADMIN_EMAIL/ADMIN_PASSWORD
             in .env, logs in and lands on /admin.
    owner  — a business owner. Signs up, onboards their business (linked via
             client_id), sees only their own dashboard.

Storage is two small JSON files (gitignored — they hold emails and hashes):
    users.json   {email: {password_hash, salt, role, client_id, created}}
    tokens.json  {token: {email, expires}}   30-day sessions

Passwords are salted PBKDF2-SHA256 (stdlib) — never stored in plain text.
When real scale arrives this becomes a users table in the database; the
functions here keep the same names.
"""

import datetime as dt
import hashlib
import json
import os
import re
import secrets
import threading
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
USERS_FILE = BASE_DIR / "users.json"
TOKENS_FILE = BASE_DIR / "tokens.json"
TOKEN_DAYS = 30

_lock = threading.Lock()

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _load(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _save(path: Path, data: dict):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def _hash(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode(), bytes.fromhex(salt), 200_000
    ).hex()


def ensure_admin_seed():
    """Create/refresh the platform admin account from .env (idempotent)."""
    email = os.getenv("ADMIN_EMAIL", "").strip().lower()
    password = os.getenv("ADMIN_PASSWORD", "")
    if not email or not password:
        return
    with _lock:
        users = _load(USERS_FILE)
        salt = users.get(email, {}).get("salt") or secrets.token_hex(16)
        users[email] = {
            "password_hash": _hash(password, salt),
            "salt": salt,
            "role": "admin",
            "client_id": users.get(email, {}).get("client_id"),
            "created": users.get(email, {}).get("created")
                       or dt.datetime.now().isoformat(timespec="seconds"),
        }
        _save(USERS_FILE, users)


def signup(email: str, password: str) -> dict:
    email = email.strip().lower()
    if not EMAIL_RE.match(email):
        raise ValueError("That doesn't look like an email address")
    if len(password) < 6:
        raise ValueError("Password must be at least 6 characters")
    with _lock:
        users = _load(USERS_FILE)
        if email in users:
            raise LookupError("An account with this email already exists — sign in instead")
        salt = secrets.token_hex(16)
        users[email] = {
            "password_hash": _hash(password, salt),
            "salt": salt,
            "role": "owner",
            "client_id": None,
            "created": dt.datetime.now().isoformat(timespec="seconds"),
        }
        _save(USERS_FILE, users)
    return issue_token(email)


def login(email: str, password: str) -> dict:
    ensure_admin_seed()
    email = email.strip().lower()
    with _lock:
        user = _load(USERS_FILE).get(email)
    if user is None or _hash(password, user["salt"]) != user["password_hash"]:
        raise PermissionError("Wrong email or password")
    return issue_token(email)


def issue_token(email: str) -> dict:
    """Returns everything the frontend needs: token + who you are."""
    token = secrets.token_hex(24)
    expires = (dt.datetime.now() + dt.timedelta(days=TOKEN_DAYS)).isoformat(timespec="seconds")
    with _lock:
        tokens = _load(TOKENS_FILE)
        now = dt.datetime.now().isoformat(timespec="seconds")
        tokens = {t: v for t, v in tokens.items() if v["expires"] > now}  # purge stale
        tokens[token] = {"email": email, "expires": expires}
        _save(TOKENS_FILE, tokens)
        user = _load(USERS_FILE)[email]
    return {"token": token, "email": email, "role": user["role"],
            "client_id": user["client_id"]}


def user_for_token(token: str) -> dict | None:
    with _lock:
        entry = _load(TOKENS_FILE).get(token)
        if entry is None or entry["expires"] < dt.datetime.now().isoformat(timespec="seconds"):
            return None
        user = _load(USERS_FILE).get(entry["email"])
    if user is None:
        return None
    return {"email": entry["email"], "role": user["role"], "client_id": user["client_id"]}


def attach_client(email: str, client_id: str):
    """Link a freshly onboarded business to the owner's account."""
    with _lock:
        users = _load(USERS_FILE)
        if email in users:
            users[email]["client_id"] = client_id
            _save(USERS_FILE, users)
