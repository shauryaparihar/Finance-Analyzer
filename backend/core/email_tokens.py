"""
Single-use emailed links. issue() makes a random secret and stores only its hash; consume() accepts it once.
"""
import hashlib
import secrets
import uuid
from datetime import timedelta
from typing import Optional

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from backend.core.config import settings
from backend.core.models import EmailToken

COOLDOWN_SECONDS = 60  # at most one email of each kind per person per minute


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def recently_issued(db: Session, user_id: uuid.UUID, purpose: str) -> bool:
    cutoff = func.now() - timedelta(seconds=COOLDOWN_SECONDS)
    stmt = select(EmailToken.id).where(EmailToken.user_id == user_id, EmailToken.purpose == purpose, EmailToken.created_at > cutoff).limit(1)
    return db.scalar(stmt) is not None


def issue(db: Session, user_id: uuid.UUID, purpose: str) -> str:
    # Older unused links of the same kind stop working: only the newest email is valid.
    db.execute(
        update(EmailToken).where(EmailToken.user_id == user_id, EmailToken.purpose == purpose, EmailToken.used_at.is_(None)).values(used_at=func.now())
    )
    raw = secrets.token_urlsafe(32)
    db.add(EmailToken(user_id=user_id, purpose=purpose, token_hash=_hash(raw), expires_at=func.now() + timedelta(minutes=settings.email_token_minutes)))
    db.commit()
    return raw


def consume(db: Session, raw: Optional[str], purpose: str) -> Optional[uuid.UUID]:
    """Use the link: returns the user id, or None if it is unknown, expired or already used. One atomic step, so
    two clicks at the same moment cannot both succeed."""
    if not raw:
        return None
    result = db.execute(
        update(EmailToken)
        .where(EmailToken.token_hash == _hash(raw), EmailToken.purpose == purpose, EmailToken.used_at.is_(None), EmailToken.expires_at > func.now())
        .values(used_at=func.now())
        .returning(EmailToken.user_id)
    ).first()
    db.commit()
    return result[0] if result else None
