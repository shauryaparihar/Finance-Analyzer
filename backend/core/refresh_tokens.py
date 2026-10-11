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
    new_token: Optional[str] = None  # None with outcome "ok": the token is still fresh, so the browser keeps its cookie
    family_id: Optional[uuid.UUID] = None


def _revoke_family(db: Session, family_id: uuid.UUID, reason: str, now: datetime) -> None:
    db.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=now, revoke_reason=reason)
    )


MAX_CHAIN_HOPS = 8


def _follow_rotation_chain(db: Session, row: RefreshToken, now: datetime) -> Optional[RefreshToken]:
    """From a recently rotated token, walk its replacements (each replaced within the grace window) to the live head.
    Returns the locked head row, or None if the chain ends in something that is not usable (revoked, missing)."""
    grace = timedelta(seconds=settings.refresh_grace_seconds)
    current = row
    for _ in range(MAX_CHAIN_HOPS):
        if current.revoked_at is None:
            return current
        if current.revoke_reason != "rotated" or current.replaced_by_id is None or now - current.revoked_at > grace:
            return None
        current = db.scalar(select(RefreshToken).where(RefreshToken.id == current.replaced_by_id).with_for_update())
        if current is None:
            return None
    return None


def rotate(db: Session, raw: Optional[str]) -> Rotation:
    if not raw:
        return Rotation("invalid")
    row = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == hash_token(raw)).with_for_update())
    if row is None:
        return Rotation("invalid")
    now = _db_now(db)
    came_through_chain = False

    if row.revoked_at is not None:
        if row.revoke_reason == "rotated":
            if now - row.revoked_at <= timedelta(seconds=settings.refresh_grace_seconds):
                # A just-replaced token came back within the grace window. This is what a page reload looks like when
                # the server's answer (carrying the new cookie) was cut off: the server rotated, the browser never
                # received the new token and still holds the old one. Follow the chain of replacements to the newest
                # live token and rotate that, so the person simply gets a fresh session instead of being logged out.
                head = _follow_rotation_chain(db, row, now)
                if head is None:
                    db.rollback()
                    return Rotation("race", row.user_id, family_id=row.family_id)
                row, came_through_chain = head, True  # the browser holds a stale cookie, so it must be given the new one
            else:
                _revoke_family(db, row.family_id, "reuse", now)  # an old token came back: assume it was copied
                db.commit()
                return Rotation("reuse", row.user_id, family_id=row.family_id)
        else:
            db.rollback()
            return Rotation("invalid", row.user_id, family_id=row.family_id)  # logged out, or already revoked as reuse

    if row.expires_at <= now or row.family_expires_at <= now:
        row.revoked_at, row.revoke_reason = now, "expired"
        db.commit()
        return Rotation("expired", row.user_id, family_id=row.family_id)

    if not came_through_chain and now - row.created_at < timedelta(seconds=settings.refresh_rotate_after_seconds):
        # Fresh enough: keep it. Swapping the cookie on every page load is what could lose it when a reload cut off the
        # answer; swapping only once it is half a day old makes that a rare event instead of a routine one.
        user_id, family_id = row.user_id, row.family_id
        db.rollback()  # nothing to write; release the row lock
        return Rotation("ok", user_id, None, family_id)

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


def revoke_all_for_user(db: Session, user_id: uuid.UUID, reason: str = "account_change") -> None:
    """End every login session of one user (used when how they sign in changes)."""
    db.execute(
        update(RefreshToken).where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None)).values(revoked_at=_db_now(db), revoke_reason=reason)
    )
    db.commit()


def purge_expired(db: Session) -> int:
    """Delete sessions that ended more than a week ago, so the table does not grow forever."""
    cutoff = _db_now(db) - timedelta(days=7)
    result = db.execute(delete(RefreshToken).where(RefreshToken.family_expires_at < cutoff))
    db.commit()
    return result.rowcount
