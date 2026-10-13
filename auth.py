"""auth.py — accounts, sessions, and password resets, backed by SQLite.

Two roles:
    admin  — the platform owner (Sai). Seeded from ADMIN_EMAIL/ADMIN_PASSWORD
             in .env, logs in and lands on /admin.
    owner  — a business owner. Signs up, onboards their business (linked via
             client_id), sees only their own dashboard.

Storage is one SQLite file, voxagent.db (gitignored). WHY SQLite over the
JSON files it replaced: writes are atomic and safe under concurrent requests,
and it's stdlib — no new dependency. Existing users.json/tokens.json are
migrated automatically on first use. Passwords are salted PBKDF2-SHA256.

Password resets: an owner requests a reset -> we mint a short-lived code.
If SMTP_* is configured in .env the code is emailed to them; otherwise it
shows up in the admin console and Sai tells them the code. Either way the
owner enters code + new password, every old session is invalidated.
"""

import datetime as dt
import hashlib
import hmac
import json
import os
import re
import secrets
import smtplib
import sqlite3
import threading
from email.message import EmailMessage
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB_FILE = BASE_DIR / "voxagent.db"
LEGACY_USERS = BASE_DIR / "users.json"
LEGACY_TOKENS = BASE_DIR / "tokens.json"

TOKEN_DAYS = 30
RESET_MINUTES = 60

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    email TEXT PRIMARY KEY, password_hash TEXT NOT NULL, salt TEXT NOT NULL,
    role TEXT NOT NULL, client_id TEXT, created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS tokens (
    token TEXT PRIMARY KEY, email TEXT NOT NULL, expires TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS resets (
    code TEXT PRIMARY KEY, email TEXT NOT NULL, expires TEXT NOT NULL,
    used INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS idx_tokens_email ON tokens(email);
CREATE INDEX IF NOT EXISTS idx_resets_email ON resets(email);
"""

# ---- connection handling -----------------------------------------------------------
#
# Every authenticated API request calls user_for_token(). That used to open a
# fresh SQLite connection, re-run PRAGMA journal_mode, execute the whole schema
# and re-check the legacy-JSON migration — before the actual lookup. Now the
# connection is opened once per thread and the schema/migration run once per
# database file. One connection per thread (not one global) because SQLite
# connections are not safe to use from several threads at once, and FastAPI
# serves sync endpoints from a thread pool.

_local = threading.local()
_prepared: set[str] = set()
_prepare_lock = threading.Lock()


def _now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def _db() -> sqlite3.Connection:
    path = str(DB_FILE)                      # tests repoint DB_FILE at a tmp file
    conn = getattr(_local, "conn", None)
    if conn is not None and getattr(_local, "path", None) == path:
        return conn
    if conn is not None:
        conn.close()
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    with _prepare_lock:
        if path not in _prepared:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")   # WAL makes this safe
            conn.executescript(_SCHEMA)
            _migrate_legacy_json(conn)
            _prepared.add(path)
    _local.conn = conn
    _local.path = path
    return conn


# ---- the token cache ---------------------------------------------------------------
#
# The token -> user lookup is the single hottest query in the app (it runs on
# every request). Tokens change only when someone signs up, logs in, resets a
# password or onboards a business, so we cache the answer in process and clear
# the cache on exactly those events — fast AND never stale.

_token_cache: dict[str, dict] = {}
_cache_lock = threading.Lock()


def _invalidate_cache():
    with _cache_lock:
        _token_cache.clear()


def _migrate_legacy_json(conn: sqlite3.Connection):
    """One-time import of the old users.json/tokens.json into SQLite."""
    if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] > 0:
        return
    if LEGACY_USERS.exists():
        try:
            users = json.loads(LEGACY_USERS.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            users = {}
        for email, u in users.items():
            conn.execute(
                "INSERT OR IGNORE INTO users VALUES (?,?,?,?,?,?)",
                (email, u["password_hash"], u["salt"], u.get("role", "owner"),
                 u.get("client_id"), u.get("created", _now())),
            )
    if LEGACY_TOKENS.exists():
        try:
            tokens = json.loads(LEGACY_TOKENS.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            tokens = {}
        for token, t in tokens.items():
            conn.execute("INSERT OR IGNORE INTO tokens VALUES (?,?,?)",
                         (token, t["email"], t["expires"]))
    conn.commit()


def _hash(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode(), bytes.fromhex(salt), 200_000
    ).hex()


# The admin password unlocks every business's data and login codes, and the
# admin header has no attempt limit yet (TODOS.md) — so a weak one is treated
# as no password at all (admin disabled), never silently accepted. The
# placeholders are the literal values shipped in .env.example (audit M3).
ADMIN_PASSWORD_MIN = 12
_PLACEHOLDER_PASSWORDS = {"choose_a_strong_password"}
_PLACEHOLDER_EMAILS = {"you@example.com"}


def admin_password_problem() -> str | None:
    """Why ADMIN_PASSWORD can't be used, or None if it's fine."""
    password = os.getenv("ADMIN_PASSWORD", "")
    if not password:
        return "Set ADMIN_PASSWORD in .env to use the admin console"
    if password in _PLACEHOLDER_PASSWORDS:
        return "ADMIN_PASSWORD is still the .env.example placeholder — change it"
    if len(password) < ADMIN_PASSWORD_MIN:
        return f"ADMIN_PASSWORD must be at least {ADMIN_PASSWORD_MIN} characters"
    return None


def admin_password_matches(candidate: str | None) -> bool:
    """Constant-time check of a supplied admin key; always False while the
    configured password is missing, a placeholder or too short."""
    if admin_password_problem() or not candidate:
        return False
    return hmac.compare_digest(candidate.encode(), os.getenv("ADMIN_PASSWORD", "").encode())


def _check_password_strength(password: str):
    if len(password) < 6:
        raise ValueError("Password must be at least 6 characters")


# ---- accounts -----------------------------------------------------------------

def ensure_admin_seed():
    """Create/refresh the platform admin account from .env (idempotent)."""
    email = os.getenv("ADMIN_EMAIL", "").strip().lower()
    password = os.getenv("ADMIN_PASSWORD", "")
    # Never create an admin from .env.example's sample values or a weak password.
    if not email or email in _PLACEHOLDER_EMAILS or admin_password_problem():
        return
    with _db() as conn:
        row = conn.execute("SELECT salt FROM users WHERE email=?", (email,)).fetchone()
        salt = row["salt"] if row else secrets.token_hex(16)
        conn.execute(
            "INSERT INTO users VALUES (?,?,?,?,NULL,?) "
            "ON CONFLICT(email) DO UPDATE SET password_hash=excluded.password_hash, role='admin'",
            (email, _hash(password, salt), salt, "admin", _now()),
        )
    _invalidate_cache()


def signup(email: str, password: str) -> dict:
    email = email.strip().lower()
    if not EMAIL_RE.match(email):
        raise ValueError("That doesn't look like an email address")
    _check_password_strength(password)
    with _db() as conn:
        if conn.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
            raise LookupError("An account with this email already exists — sign in instead")
        salt = secrets.token_hex(16)
        conn.execute("INSERT INTO users VALUES (?,?,?,?,NULL,?)",
                     (email, _hash(password, salt), salt, "owner", _now()))
    return issue_token(email)


def login(email: str, password: str) -> dict:
    ensure_admin_seed()
    email = email.strip().lower()
    with _db() as conn:
        user = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
    if user is None or not hmac.compare_digest(_hash(password, user["salt"]),
                                                user["password_hash"]):
        raise PermissionError("Wrong email or password")
    return issue_token(email)


def issue_token(email: str) -> dict:
    """Returns everything the frontend needs: token + who you are."""
    token = secrets.token_hex(24)
    expires = (dt.datetime.now() + dt.timedelta(days=TOKEN_DAYS)).isoformat(timespec="seconds")
    with _db() as conn:
        conn.execute("DELETE FROM tokens WHERE expires < ?", (_now(),))
        conn.execute("INSERT INTO tokens VALUES (?,?,?)", (token, email, expires))
        user = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
    _invalidate_cache()
    return {"token": token, "email": email, "role": user["role"],
            "client_id": user["client_id"]}


def user_for_token(token: str) -> dict | None:
    """Hot path: runs on every authenticated request. Served from cache."""
    with _cache_lock:
        hit = _token_cache.get(token)
    if hit is not None:
        if hit["expires"] >= _now():
            return {k: hit[k] for k in ("email", "role", "client_id")}
        with _cache_lock:
            _token_cache.pop(token, None)
        return None

    conn = _db()
    row = conn.execute(
        "SELECT u.email, u.role, u.client_id, t.expires FROM tokens t "
        "JOIN users u ON u.email = t.email "
        "WHERE t.token=? AND t.expires >= ?", (token, _now()),
    ).fetchone()
    if row is None:
        return None
    entry = dict(row)
    with _cache_lock:
        if len(_token_cache) > 4096:       # bounded; tokens are tiny
            _token_cache.clear()
        _token_cache[token] = entry
    return {k: entry[k] for k in ("email", "role", "client_id")}


def attach_client(email: str, client_id: str):
    """Link a freshly onboarded business to the owner's account."""
    with _db() as conn:
        conn.execute("UPDATE users SET client_id=? WHERE email=?", (client_id, email))
    _invalidate_cache()   # cached sessions still think this owner has no business


# ---- password reset --------------------------------------------------------------

def create_reset(email: str) -> str | None:
    """Mint a reset code for this email (None if no such account — callers must
    answer identically either way, so nobody can probe which emails exist)."""
    email = email.strip().lower()
    with _db() as conn:
        if not conn.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
            return None
        code = "RS-" + secrets.token_hex(3).upper()
        expires = (dt.datetime.now() + dt.timedelta(minutes=RESET_MINUTES)).isoformat(timespec="seconds")
        conn.execute("DELETE FROM resets WHERE email=? OR expires < ?", (email, _now()))
        conn.execute("INSERT INTO resets VALUES (?,?,?,0)", (code, email, expires))
    return code


def reset_password(email: str, code: str, new_password: str) -> dict:
    """Verify the code, set the new password, and kill every old session."""
    _check_password_strength(new_password)
    email = email.strip().lower()
    with _db() as conn:
        row = conn.execute(
            "SELECT * FROM resets WHERE code=? AND email=? AND used=0 AND expires >= ?",
            (code.strip().upper(), email, _now()),
        ).fetchone()
        if row is None:
            raise PermissionError("That reset code is wrong or has expired")
        salt = secrets.token_hex(16)
        conn.execute("UPDATE users SET password_hash=?, salt=? WHERE email=?",
                     (_hash(new_password, salt), salt, email))
        conn.execute("UPDATE resets SET used=1 WHERE code=?", (row["code"],))
        conn.execute("DELETE FROM tokens WHERE email=?", (email,))
    _invalidate_cache()   # every old session must stop working immediately
    return issue_token(email)


def pending_resets() -> list[dict]:
    """Unused, unexpired reset codes — shown in the admin console so the
    platform owner can pass a code to a client when email isn't set up."""
    with _db() as conn:
        rows = conn.execute(
            "SELECT code, email, expires FROM resets WHERE used=0 AND expires >= ? "
            "ORDER BY expires DESC", (_now(),),
        ).fetchall()
    return [dict(r) for r in rows]


def send_reset_email(email: str, code: str) -> bool:
    """Email the reset code if SMTP is configured in .env; False otherwise."""
    host = os.getenv("SMTP_HOST", "")
    user = os.getenv("SMTP_USER", "")
    password = os.getenv("SMTP_PASS", "")
    if not (host and user and password):
        return False
    msg = EmailMessage()
    msg["Subject"] = "Your VoxAgent password reset code"
    msg["From"] = os.getenv("SMTP_FROM", user)
    msg["To"] = email
    msg.set_content(
        f"Your VoxAgent password reset code is: {code}\n\n"
        f"It expires in {RESET_MINUTES} minutes. If you didn't ask for this, ignore it."
    )
    try:
        with smtplib.SMTP(host, int(os.getenv("SMTP_PORT", "587")), timeout=15) as smtp:
            smtp.starttls()
            smtp.login(user, password)
            smtp.send_message(msg)
        return True
    except Exception as e:
        print(f"  [auth] reset email failed: {e}")
        return False
