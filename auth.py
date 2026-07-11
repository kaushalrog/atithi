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
import json
import os
import re
import secrets
import smtplib
import sqlite3
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
"""


def _now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_FILE, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(_SCHEMA)
    _migrate_legacy_json(conn)
    return conn


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


def _check_password_strength(password: str):
    if len(password) < 6:
        raise ValueError("Password must be at least 6 characters")


# ---- accounts -----------------------------------------------------------------

def ensure_admin_seed():
    """Create/refresh the platform admin account from .env (idempotent)."""
    email = os.getenv("ADMIN_EMAIL", "").strip().lower()
    password = os.getenv("ADMIN_PASSWORD", "")
    if not email or not password:
        return
    with _db() as conn:
        row = conn.execute("SELECT salt FROM users WHERE email=?", (email,)).fetchone()
        salt = row["salt"] if row else secrets.token_hex(16)
        conn.execute(
            "INSERT INTO users VALUES (?,?,?,?,NULL,?) "
            "ON CONFLICT(email) DO UPDATE SET password_hash=excluded.password_hash, role='admin'",
            (email, _hash(password, salt), salt, "admin", _now()),
        )


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
    if user is None or _hash(password, user["salt"]) != user["password_hash"]:
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
    return {"token": token, "email": email, "role": user["role"],
            "client_id": user["client_id"]}


def user_for_token(token: str) -> dict | None:
    with _db() as conn:
        row = conn.execute(
            "SELECT u.email, u.role, u.client_id FROM tokens t "
            "JOIN users u ON u.email = t.email "
            "WHERE t.token=? AND t.expires >= ?", (token, _now()),
        ).fetchone()
    return dict(row) if row else None


def attach_client(email: str, client_id: str):
    """Link a freshly onboarded business to the owner's account."""
    with _db() as conn:
        conn.execute("UPDATE users SET client_id=? WHERE email=?", (client_id, email))


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
