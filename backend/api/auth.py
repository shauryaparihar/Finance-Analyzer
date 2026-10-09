"""
Registration, login and "who am I" endpoints.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.api.deps import get_current_user
from backend.api.errors import AppError
from backend.api.schemas import LoginRequest, RegisterRequest, TokenOut, UserOut
from backend.core import repository as repo
from backend.core.config import settings
from backend.core.database import get_db
from backend.core.models import User
from backend.core.security import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _user_out(user: User) -> UserOut:
    return UserOut(id=user.id, email=user.email, created_at=user.created_at)


@router.post("/register", response_model=UserOut, status_code=201)
def register(body: RegisterRequest, db: Session = Depends(get_db)):
    if repo.get_user_by_email(db, body.email) is not None:
        raise AppError(409, "EMAIL_ALREADY_REGISTERED", "An account with this email already exists.")
    try:
        user = repo.create_user(db, body.email, hash_password(body.password))
    except IntegrityError:  # two simultaneous registrations for the same email
        db.rollback()
        raise AppError(409, "EMAIL_ALREADY_REGISTERED", "An account with this email already exists.")
    return _user_out(user)


@router.post("/login", response_model=TokenOut)
def login(body: LoginRequest, db: Session = Depends(get_db)):
    user = repo.get_user_by_email(db, body.email)
    password_ok = verify_password(body.password, user.password_hash if user else None)
    if user is None or not password_ok or not user.is_active:
        # Same answer for "unknown email" and "wrong password" so the response does not reveal which emails exist.
        raise AppError(401, "INVALID_CREDENTIALS", "Incorrect email or password.", headers={"WWW-Authenticate": "Bearer"})
    return TokenOut(
        access_token=create_access_token(user.id), expires_in=settings.access_token_expire_minutes * 60
    )


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return _user_out(user)
