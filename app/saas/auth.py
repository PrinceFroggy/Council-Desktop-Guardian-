"""Minimal auth helpers for optional SaaS mode.

Security note: for real production, use a battle-tested auth stack.
This is intentionally minimal to keep the repo runnable.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import time
from typing import Optional, Dict, Any

from ..config import settings


def _jwt_secret() -> str:
    # If not set, generate a deterministic-but-unique secret per machine.
    if settings.JWT_SECRET:
        return settings.JWT_SECRET
    return hashlib.sha256((os.uname().nodename + ":council").encode()).hexdigest()


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 120_000)
    return salt.hex() + ":" + digest.hex()


def verify_password(password: str, stored: str) -> bool:
    try:
        salt_hex, digest_hex = stored.split(":", 1)
        salt = bytes.fromhex(salt_hex)
        digest = bytes.fromhex(digest_hex)
        cand = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 120_000)
        return hmac.compare_digest(cand, digest)
    except Exception:
        return False


def create_jwt(email: str, ttl_seconds: int = 60 * 60 * 24) -> str:
    try:
        import jwt  # type: ignore
    except Exception as e:
        raise RuntimeError("PyJWT not installed") from e

    now = int(time.time())
    payload = {"sub": email, "iat": now, "exp": now + int(ttl_seconds)}
    return jwt.encode(payload, _jwt_secret(), algorithm="HS256")


def decode_jwt(token: str) -> Optional[Dict[str, Any]]:
    try:
        import jwt  # type: ignore
    except Exception:
        return None
    try:
        return jwt.decode(token, _jwt_secret(), algorithms=["HS256"])
    except Exception:
        return None
