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


def _connect():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
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
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO saved_scenarios (username, label, params_json, created_at) VALUES (?, ?, ?, ?)",
            (username, label, json.dumps(params), datetime.now().strftime("%Y-%m-%d %H:%M")),
        )
        conn.commit()
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


def delete_scenario(scenario_id, username):
    conn = _connect()
    try:
        conn.execute("DELETE FROM saved_scenarios WHERE id = ? AND username = ?", (scenario_id, username))
        conn.commit()
    finally:
        conn.close()
