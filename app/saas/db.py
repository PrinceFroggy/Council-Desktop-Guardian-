"""Tiny SQLite user DB for optional SaaS mode.

This keeps the project self-contained.
For production, swap to Postgres + migrations.
"""

from __future__ import annotations

import os
import sqlite3
from typing import Optional, Dict, Any

from ..config import settings


def _sqlite_path() -> str:
    url = settings.DATABASE_URL or "sqlite:///./council.db"
    if url.startswith("sqlite:///"):
        return url.replace("sqlite:///", "", 1)
    # Fallback: treat as path
    return url


def _conn() -> sqlite3.Connection:
    path = _sqlite_path()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    return sqlite3.connect(path)


def init_db() -> None:
    con = _conn()
    try:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                stripe_customer_id TEXT,
                plan TEXT
            );
            """
        )
        con.commit()
    finally:
        con.close()


def get_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    con = _conn()
    try:
        cur = con.execute("SELECT id,email,password_hash,created_at,stripe_customer_id,plan FROM users WHERE email=?", (email,))
        row = cur.fetchone()
        if not row:
            return None
        return {
            "id": row[0],
            "email": row[1],
            "password_hash": row[2],
            "created_at": row[3],
            "stripe_customer_id": row[4],
            "plan": row[5],
        }
    finally:
        con.close()


def create_user(email: str, password_hash: str, created_at: int) -> Dict[str, Any]:
    con = _conn()
    try:
        con.execute(
            "INSERT INTO users(email,password_hash,created_at,plan) VALUES(?,?,?,?)",
            (email, password_hash, int(created_at), "free"),
        )
        con.commit()
        return get_user_by_email(email) or {"email": email}
    finally:
        con.close()


def update_user_plan(email: str, plan: str, stripe_customer_id: Optional[str] = None) -> None:
    con = _conn()
    try:
        if stripe_customer_id:
            con.execute("UPDATE users SET plan=?, stripe_customer_id=? WHERE email=?", (plan, stripe_customer_id, email))
        else:
            con.execute("UPDATE users SET plan=? WHERE email=?", (plan, email))
        con.commit()
    finally:
        con.close()