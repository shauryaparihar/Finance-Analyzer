"""
Shared FastAPI dependencies, mainly "who is the logged-in user?".
"""
import uuid

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from backend.api.errors import AppError
from backend.core import repository as repo
from backend.core.database import get_db
from backend.core.models import User
from backend.core.security import TokenError, decode_access_token

bearer_scheme = HTTPBearer(auto_error=False)

_UNAUTHENTICATED_MESSAGES = {
    "NOT_AUTHENTICATED": "Please log in to continue.",
    "TOKEN_EXPIRED": "Your session has expired. Please log in again.",
    "TOKEN_INVALID": "Your session is not valid. Please log in again.",
}


def _unauthenticated(code: str) -> AppError:
    return AppError(401, code, _UNAUTHENTICATED_MESSAGES[code], headers={"WWW-Authenticate": "Bearer"})


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise _unauthenticated("NOT_AUTHENTICATED")
    try:
        user_id = decode_access_token(credentials.credentials)
    except TokenError as e:
        raise _unauthenticated(e.code)
    user = repo.get_user(db, user_id)
    if user is None or not user.is_active:
        raise _unauthenticated("TOKEN_INVALID")
    request.state.user_id = str(user.id)  # read by the request log
    return user


def get_current_user_id(user: User = Depends(get_current_user)) -> uuid.UUID:
    return user.id


def get_writer_user(user: User = Depends(get_current_user)) -> User:
    """Like get_current_user, but the read-only demo account may not change anything."""
    if user.role == "demo":
        raise AppError(403, "READ_ONLY_ACCOUNT", "The demo account is read-only. Create an account to upload and edit.")
    return user


def get_writer_user_id(user: User = Depends(get_writer_user)) -> uuid.UUID:
    return user.id


def get_admin_user(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        # 404, not 403: the existence of the admin area is not revealed to other accounts
        raise AppError(404, "NOT_FOUND", "Not found.")
    return user
