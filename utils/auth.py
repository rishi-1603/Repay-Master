"""Lightweight local auth + saved-scenario history using stdlib sqlite3.

No bcrypt (a prior deployment had bcrypt native-build compatibility problems),
so passwords are hashed with PBKDF2-HMAC-SHA256 + a random per-user salt.
"""
import sqlite3
import hashlib
import secrets
import json
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "app.db")


# Paths whose schema this process has already created. The point is the per-call
# cost: `_connect()` is called once per request, and the two CREATE TABLE statements
# plus the index cost ~56 microseconds every time (~0.076 ms vs ~0.020 ms for a bare
# connect, Day 7 measurement) for a schema that cannot have changed in between.
_SCHEMA_ENSURED: set[str] = set()


def _ensure_schema(conn):
    """Create the tables and indexes if they are missing. Idempotent by design."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password_hash TEXT NOT NULL,
            salt TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS saved_scenarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            label TEXT NOT NULL,
            params_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    # Every history read is "WHERE username = ? ORDER BY id DESC" -- without this the
    # plan is a full scan of saved_scenarios (measured on 20k rows Day 7).
    conn.execute("CREATE INDEX IF NOT EXISTS idx_saved_scenarios_username "
                 "ON saved_scenarios (username)")


def _connect():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    # checked BEFORE connecting: sqlite3.connect() creates the file, after which
    # "is this a new database?" is no longer answerable
    is_new_file = not os.path.exists(DB_PATH)
    conn = sqlite3.connect(DB_PATH)
    if is_new_file or DB_PATH not in _SCHEMA_ENSURED:
        _ensure_schema(conn)
        _SCHEMA_ENSURED.add(DB_PATH)
    return conn


def _hash_password(password, salt):
    return hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), bytes.fromhex(salt), 100_000).hex()


def register_user(username, password):
    username = username.strip()
    if not username or not password:
        return False, "Username and password are required."
    conn = _connect()
    try:
        existing = conn.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone()
        if existing:
            return False, "That username is already taken."
        salt = secrets.token_hex(16)
        pw_hash = _hash_password(password, salt)
        conn.execute("INSERT INTO users (username, password_hash, salt) VALUES (?, ?, ?)",
                     (username, pw_hash, salt))
        conn.commit()
        return True, "Registration successful. Please log in."
    finally:
        conn.close()


def authenticate(username, password):
    conn = _connect()
    try:
        row = conn.execute("SELECT password_hash, salt FROM users WHERE username = ?",
                            (username.strip(),)).fetchone()
        if not row:
            return False, "No account with that username."
        pw_hash, salt = row
        if _hash_password(password, salt) == pw_hash:
            return True, "Logged in."
        return False, "Incorrect password."
    finally:
        conn.close()


def save_scenario(username, label, params: dict):
    """Returns the new row's id (the Streamlit UI ignores the return value,
    so adding it is backward compatible; the FastAPI /history endpoint uses
    it to hand the client back a complete record without re-querying)."""
    conn = _connect()
    try:
        cur = conn.execute(
            "INSERT INTO saved_scenarios (username, label, params_json, created_at) VALUES (?, ?, ?, ?)",
            (username, label, json.dumps(params), datetime.now().strftime("%Y-%m-%d %H:%M")),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def get_saved_scenarios(username):
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT id, label, params_json, created_at FROM saved_scenarios WHERE username = ? ORDER BY id DESC",
            (username,),
        ).fetchall()
        return [
            {'id': r[0], 'label': r[1], 'params': json.loads(r[2]), 'created_at': r[3]}
            for r in rows
        ]
    finally:
        conn.close()


def get_scenario(scenario_id, username):
    """One saved scenario by id, scoped to its owner.

    Added on Day 7 because the FastAPI `POST /history` handler used to call
    `get_saved_scenarios(username)` and then scan the returned list for the row it
    had just inserted -- i.e. it read and JSON-parsed every scenario the user owned
    (54 ms for 20,000 rows) to answer a query about one row. The `AND username = ?`
    keeps ownership enforcement at the SQL layer, exactly like `delete_scenario`.
    Returns None when the row does not exist or belongs to someone else.
    """
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT id, label, params_json, created_at FROM saved_scenarios "
            "WHERE id = ? AND username = ?",
            (scenario_id, username),
        ).fetchone()
        if row is None:
            return None
        return {'id': row[0], 'label': row[1], 'params': json.loads(row[2]), 'created_at': row[3]}
    finally:
        conn.close()


def delete_scenario(scenario_id, username):
    """Returns True if a row was actually deleted. The AND username = ?
    clause means a user can never delete another user's scenario even by
    guessing an id -- ownership is enforced here at the SQL layer, not in
    whatever calls this function. (The Streamlit UI ignores the return
    value, so adding it is backward compatible; the FastAPI /history
    endpoint uses it to return 404 instead of silently no-op'ing.)"""
    conn = _connect()
    try:
        cur = conn.execute("DELETE FROM saved_scenarios WHERE id = ? AND username = ?", (scenario_id, username))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()
