"""
Password hashing (Argon2) and short-lived JWT access tokens.
"""
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from pwdlib import PasswordHash

from backend.core.config import effective_jwt_secret, settings

_hasher = PasswordHash.recommended()  # Argon2id
# Verified against when the email is unknown, so "no such user" and "wrong password" take similar time.
_DUMMY_HASH = _hasher.hash("not-a-real-password")


class TokenError(Exception):
    """The token is missing, malformed, tampered with, or expired."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: Optional[str]) -> bool:
    """Check a password. A missing or unusable hash still costs one verification."""
    if not password_hash or not password_hash.startswith("$argon2"):
        _hasher.verify(password, _DUMMY_HASH)
        return False
    return _hasher.verify(password, password_hash)


def create_access_token(user_id: uuid.UUID, expires_delta: Optional[timedelta] = None) -> str:
    now = datetime.now(timezone.utc)
    lifetime = expires_delta if expires_delta is not None else timedelta(minutes=settings.access_token_expire_minutes)
    payload = {"sub": str(user_id), "iat": now, "exp": now + lifetime}
    return jwt.encode(payload, effective_jwt_secret(), algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> uuid.UUID:
    """Return the user id in a valid token, or raise TokenError."""
    try:
        # The accepted algorithm is fixed by us, never taken from the token header.
        payload = jwt.decode(
            token,
            effective_jwt_secret(),
            algorithms=[settings.jwt_algorithm],
            options={"require": ["sub", "exp"]},
        )
    except jwt.ExpiredSignatureError:
        raise TokenError("TOKEN_EXPIRED")
    except jwt.PyJWTError:
        raise TokenError("TOKEN_INVALID")
    try:
        return uuid.UUID(payload["sub"])
    except (ValueError, TypeError):
        raise TokenError("TOKEN_INVALID")
