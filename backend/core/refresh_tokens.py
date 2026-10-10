"""
Refresh tokens: random secrets kept in an HttpOnly cookie, stored in the database only as SHA-256 hashes.

  issue()   start a new login session (a "family") and return the raw token to put in the cookie
  rotate()  exchange a valid token for the next one in its family; detects replay of an already-used token
  is_valid()  read-only check that a token is a live one (changes nothing)
  revoke()  end a session (logout)
"""
import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from backend.core.config import settings
from backend.core.models import RefreshToken


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _new_secret() -> str:
    return secrets.token_urlsafe(48)


def _db_now(db: Session) -> datetime:
    return db.scalar(select(func.now()))  # the database's clock, so several instances agree


def issue(db: Session, user_id: uuid.UUID, family_id: Optional[uuid.UUID] = None, family_expires_at: Optional[datetime] = None) -> str:
    """Create a token (a new family unless one is given) and return the raw secret. Only its hash is stored."""
    now = _db_now(db)
    family_expires_at = family_expires_at or now + timedelta(days=settings.refresh_family_max_days)
    raw = _new_secret()
    db.add(
        RefreshToken(
            user_id=user_id,
            family_id=family_id or uuid.uuid4(),
            token_hash=hash_token(raw),
            expires_at=min(now + timedelta(days=settings.refresh_token_days), family_expires_at),
            family_expires_at=family_expires_at,
        )
    )
    db.commit()
    return raw


@dataclass
class Rotation:
    outcome: str  # ok | invalid | expired | race | reuse
    user_id: Optional[uuid.UUID] = None
    new_token: Optional[str] = None
    family_id: Optional[uuid.UUID] = None


def _revoke_family(db: Session, family_id: uuid.UUID, reason: str, now: datetime) -> None:
    db.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=now, revoke_reason=reason)
    )


def rotate(db: Session, raw: Optional[str]) -> Rotation:
    if not raw:
        return Rotation("invalid")
    row = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == hash_token(raw)).with_for_update())
    if row is None:
        return Rotation("invalid")
    now = _db_now(db)

    if row.revoked_at is not None:
        if row.revoke_reason == "rotated":
            if now - row.revoked_at <= timedelta(seconds=settings.refresh_grace_seconds):
                # Two tabs refreshed at the same moment: the loser holds the previous token. Not theft; the winner's
                # new cookie is already in the browser, so the caller should simply try again.
                db.rollback()
                return Rotation("race", row.user_id, family_id=row.family_id)
            _revoke_family(db, row.family_id, "reuse", now)  # an old token came back: assume it was copied
            db.commit()
            return Rotation("reuse", row.user_id, family_id=row.family_id)
        db.rollback()
        return Rotation("invalid", row.user_id, family_id=row.family_id)  # logged out, or already revoked as reuse

    if row.expires_at <= now or row.family_expires_at <= now:
        row.revoked_at, row.revoke_reason = now, "expired"
        db.commit()
        return Rotation("expired", row.user_id, family_id=row.family_id)

    new_raw = _new_secret()
    new_row = RefreshToken(
        user_id=row.user_id,
        family_id=row.family_id,
        token_hash=hash_token(new_raw),
        expires_at=min(now + timedelta(days=settings.refresh_token_days), row.family_expires_at),
        family_expires_at=row.family_expires_at,
    )
    db.add(new_row)
    db.flush()
    row.revoked_at, row.revoke_reason, row.replaced_by_id = now, "rotated", new_row.id
    db.commit()
    return Rotation("ok", row.user_id, new_raw, row.family_id)


def is_valid(db: Session, raw: Optional[str]) -> bool:
    """True if this is a current, unexpired token. Unlike rotate() it never changes anything, so asking is free."""
    if not raw:
        return False
    row = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == hash_token(raw)))
    if row is None or row.revoked_at is not None:
        return False
    now = _db_now(db)
    return row.expires_at > now and row.family_expires_at > now


def revoke(db: Session, raw: Optional[str]) -> bool:
    """Log out: end the whole session this token belongs to. Returns whether a session was found."""
    if not raw:
        return False
    row = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == hash_token(raw)))
    if row is None:
        return False
    _revoke_family(db, row.family_id, "logout", _db_now(db))
    db.commit()
    return True


def purge_expired(db: Session) -> int:
    """Delete sessions that ended more than a week ago, so the table does not grow forever."""
    cutoff = _db_now(db) - timedelta(days=7)
    result = db.execute(delete(RefreshToken).where(RefreshToken.family_expires_at < cutoff))
    db.commit()
    return result.rowcount
