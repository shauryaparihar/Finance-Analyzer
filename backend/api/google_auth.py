"""
"Continue with Google" endpoints. See backend/core/google_oauth.py for the flow.
"""
import logging
import secrets

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from backend.api.auth import _set_refresh_cookie
from backend.api.errors import AppError
from backend.core import google_oauth, refresh_tokens
from backend.core import repository as repo
from backend.core.config import cookie_secure_enabled
from backend.core.database import get_db
from backend.core.google_oauth import OAuthError
from backend.core.logging import log_event

router = APIRouter(prefix="/api/auth/google", tags=["auth"])
logger = logging.getLogger("finsight.google")
FAILED = "/login?google=failed"


def _require_enabled() -> None:
    if not google_oauth.enabled():
        raise AppError(404, "NOT_FOUND", "Not found.")


@router.get("/login")
def start():
    """Send the browser to Google's sign-in page."""
    _require_enabled()
    address, flow_cookie = google_oauth.start_flow()
    response = RedirectResponse(address, status_code=302)
    response.set_cookie(
        google_oauth.FLOW_COOKIE, flow_cookie, max_age=google_oauth.FLOW_SECONDS, path=google_oauth.FLOW_COOKIE_PATH,
        httponly=True, secure=cookie_secure_enabled(),
        samesite="lax",  # Google sends the browser back with a top-level GET from another site; Strict would drop the cookie
    )
    return response


@router.get("/callback")
def callback(request: Request, code: str | None = None, state: str | None = None, error: str | None = None, db: Session = Depends(get_db)):
    """Google sends the browser back here after the person agreed (or refused)."""
    _require_enabled()
    fail = RedirectResponse(FAILED, status_code=302)
    fail.delete_cookie(google_oauth.FLOW_COOKIE, path=google_oauth.FLOW_COOKIE_PATH)
    try:
        if error or not code or not state:
            raise OAuthError(f"no code ({error or 'missing parameters'})")
        flow = google_oauth.read_flow_cookie(request.cookies.get(google_oauth.FLOW_COOKIE))
        if not secrets.compare_digest(str(flow["state"]), state):
            raise OAuthError("state mismatch")
        identity = google_oauth.identity_from_claims(google_oauth.exchange_code(code, flow["verifier"]), flow["nonce"])
        user, linked = repo.resolve_google_user(db, identity.sub, identity.email)
        if not user.is_active:
            raise OAuthError("account disabled")
    except (OAuthError, ValueError) as e:
        log_event(logger, logging.WARNING, "google_sign_in_rejected", reason=str(e))
        return fail

    if linked:
        refresh_tokens.revoke_all_for_user(db, user.id, "google_linked")
    refresh_tokens.purge_expired(db)
    response = RedirectResponse("/", status_code=302)
    _set_refresh_cookie(response, refresh_tokens.issue(db, user.id))
    response.delete_cookie(google_oauth.FLOW_COOKIE, path=google_oauth.FLOW_COOKIE_PATH)
    log_event(logger, logging.INFO, "google_sign_in", user_id=str(user.id), linked_existing=linked)
    return response
