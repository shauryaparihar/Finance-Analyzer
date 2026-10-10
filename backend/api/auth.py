"""
Registration, login and "who am I" endpoints.
"""
import logging

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.api.deps import get_current_user
from backend.api.errors import AppError
from backend.api.schemas import LoginRequest, RegisterRequest, TokenOut, UserOut
from backend.core import refresh_tokens
from backend.core import repository as repo
from backend.core.config import cookie_secure_enabled, cors_origins, settings
from backend.core.database import get_db
from backend.core.logging import log_event
from backend.core.models import User
from backend.core.security import create_access_token, hash_password, verify_password
from backend.services.demo import ensure_demo_analysis

router = APIRouter(prefix="/api/auth", tags=["auth"])
logger = logging.getLogger("finsight.auth")

REFRESH_COOKIE = "finsight_refresh"
REFRESH_COOKIE_PATH = "/api/auth"  # the browser sends this cookie only to the auth endpoints, never with data requests
CSRF_HEADER = "X-FinSight-Request"


def _set_refresh_cookie(response: Response, raw_token: str) -> None:
    response.set_cookie(
        REFRESH_COOKIE,
        raw_token,
        max_age=settings.refresh_token_days * 24 * 3600,
        path=REFRESH_COOKIE_PATH,
        httponly=True,  # page scripts cannot read it, so injected code cannot steal it
        secure=cookie_secure_enabled(),
        samesite="strict",  # never sent on cross-site requests
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(REFRESH_COOKIE, path=REFRESH_COOKIE_PATH, httponly=True, secure=cookie_secure_enabled(), samesite="strict")


def _require_same_site_request(request: Request) -> None:
    """Defence in depth for the two cookie-authenticated endpoints. SameSite=Strict already keeps the cookie off
    cross-site requests; additionally require a custom header (which a cross-site page cannot add without a CORS
    preflight we do not allow) and reject a browser Origin we do not know."""
    origin = request.headers.get("origin")
    has_header = request.headers.get(CSRF_HEADER) == "1"
    origin_known = not origin or origin.rstrip("/") in cors_origins()
    if not has_header or not origin_known:
        # Names the reason for whoever runs the site (for example "the Vercel domain is not in FRONTEND_URL").
        log_event(logger, logging.WARNING, "csrf_rejected", path=request.url.path, header_present=has_header, origin=origin, origin_known=origin_known)
        raise AppError(403, "CSRF_REJECTED", "This request was not accepted.")


def _user_out(user: User) -> UserOut:
    return UserOut(id=user.id, email=user.email, created_at=user.created_at, role=user.role)


@router.post("/register", response_model=UserOut, status_code=201)
def register(body: RegisterRequest, db: Session = Depends(get_db)):
    if body.email.strip().lower() == repo.DEMO_EMAIL or repo.get_user_by_email(db, body.email) is not None:
        raise AppError(409, "EMAIL_ALREADY_REGISTERED", "An account with this email already exists.")
    try:
        user = repo.create_user(db, body.email, hash_password(body.password))
    except IntegrityError:  # two simultaneous registrations for the same email
        db.rollback()
        raise AppError(409, "EMAIL_ALREADY_REGISTERED", "An account with this email already exists.")
    return _user_out(user)


@router.post("/login", response_model=TokenOut)
def login(body: LoginRequest, response: Response, db: Session = Depends(get_db)):
    user = repo.get_user_by_email(db, body.email)
    password_ok = verify_password(body.password, user.password_hash if user else None)
    if user is None or not password_ok or not user.is_active:
        # Same answer for "unknown email" and "wrong password" so the response does not reveal which emails exist.
        raise AppError(401, "INVALID_CREDENTIALS", "Incorrect email or password.", headers={"WWW-Authenticate": "Bearer"})
    refresh_tokens.purge_expired(db)
    _set_refresh_cookie(response, refresh_tokens.issue(db, user.id))  # a new login session
    return TokenOut(
        access_token=create_access_token(user.id), expires_in=settings.access_token_expire_minutes * 60
    )


@router.post("/demo", response_model=TokenOut)
def demo_login(request: Request, response: Response, db: Session = Depends(get_db)):
    """One-click read-only guest session, when the deployment enables it. There is no password to guess:
    the demo account's stored hash can never match one, so this endpoint is the only way in."""
    if not settings.demo_enabled:
        raise AppError(404, "NOT_FOUND", "Not found.")
    _require_same_site_request(request)
    user = repo.get_or_create_demo_user(db)
    if not user.is_active or user.role != "demo":
        raise AppError(404, "NOT_FOUND", "Not found.")
    if ensure_demo_analysis(db, user):
        runner = getattr(request.app.state, "job_runner", None)
        if runner is not None:
            runner.wake()
    refresh_tokens.purge_expired(db)
    _set_refresh_cookie(response, refresh_tokens.issue(db, user.id))
    log_event(logger, logging.INFO, "demo_login")
    return TokenOut(access_token=create_access_token(user.id), expires_in=settings.access_token_expire_minutes * 60)


_REFRESH_FAILURES = {
    "invalid": ("REFRESH_INVALID", "Please log in again."),
    "expired": ("REFRESH_EXPIRED", "Your session expired. Please log in again."),
    "reuse": ("REFRESH_REUSED", "Your session ended for security reasons. Please log in again."),
    "race": ("REFRESH_RACE", "Another tab just renewed the session. Please retry."),
}


@router.post("/refresh", response_model=TokenOut)
def refresh(request: Request, response: Response, db: Session = Depends(get_db)):
    """Exchange the refresh cookie for a new short-lived access token (and a new refresh cookie)."""
    _require_same_site_request(request)
    result = refresh_tokens.rotate(db, request.cookies.get(REFRESH_COOKIE))
    user = repo.get_user(db, result.user_id) if result.outcome == "ok" and result.user_id else None
    if result.outcome == "ok" and (user is None or not user.is_active):
        refresh_tokens.revoke(db, result.new_token)  # the account was disabled: end this session as well
        result.outcome = "invalid"
    if result.outcome != "ok":
        log_event(
            logger, logging.INFO, "refresh_rejected",
            reason=result.outcome, cookie_present=bool(request.cookies.get(REFRESH_COOKIE)), origin=request.headers.get("origin"),
        )
        if result.outcome == "reuse":
            log_event(logger, logging.WARNING, "refresh_token_reuse_detected", user_id=str(result.user_id), family_id=str(result.family_id))
        code, message = _REFRESH_FAILURES[result.outcome]
        headers = {} if result.outcome == "race" else {"Set-Cookie": _expired_cookie_header()}
        raise AppError(401, code, message, headers=headers)
    _set_refresh_cookie(response, result.new_token)
    log_event(logger, logging.INFO, "refresh_token_rotated", user_id=str(result.user_id), family_id=str(result.family_id))
    return TokenOut(access_token=create_access_token(user.id), expires_in=settings.access_token_expire_minutes * 60)


@router.post("/session-check", status_code=204)
def session_check(request: Request, db: Session = Depends(get_db)):
    """Does the browser send back a live refresh cookie? Answers 204 or 401 and changes nothing (no rotation).

    The website asks this right after login. Using /refresh for that would rotate the token while the person
    might reload the page, losing the new cookie in flight and logging them out.
    """
    _require_same_site_request(request)
    if not refresh_tokens.is_valid(db, request.cookies.get(REFRESH_COOKIE)):
        raise AppError(401, "REFRESH_INVALID", "Please log in again.")
    return Response(status_code=204)


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    """End this login session everywhere: the refresh token family is revoked and the cookie is removed."""
    _require_same_site_request(request)
    refresh_tokens.revoke(db, request.cookies.get(REFRESH_COOKIE))
    _clear_refresh_cookie(response)
    response.status_code = 204
    return response


def _expired_cookie_header() -> str:
    secure = "; Secure" if cookie_secure_enabled() else ""
    return f"{REFRESH_COOKIE}=\"\"; Max-Age=0; Path={REFRESH_COOKIE_PATH}; HttpOnly; SameSite=strict{secure}"


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return _user_out(user)
