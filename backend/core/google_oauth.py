"""
"Continue with Google": the OAuth 2.0 / OpenID Connect authorization-code flow with PKCE, done by the server.

  1. /api/auth/google/login   builds Google's sign-in address (with a random `state`, `nonce` and a PKCE challenge)
                              and remembers them in a short-lived signed cookie.
  2. Google shows its own sign-in page, the person agrees, and Google sends the browser back with a one-time `code`.
  3. /api/auth/google/callback checks `state` against the cookie, exchanges the code (plus the PKCE verifier and the
                              client secret, which only this server knows) for an ID token, and reads who the person is.

Authentication (who are you?) comes from Google's answer; authorization (what may you do here?) stays ours: the
person gets the same ordinary account role and the same per-user data filtering as everyone else.
"""
import base64
import hashlib
import secrets
import time
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx
import jwt

from backend.core.config import effective_jwt_secret, settings

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
ISSUERS = ("https://accounts.google.com", "accounts.google.com")
FLOW_COOKIE = "finsight_oauth"
FLOW_COOKIE_PATH = "/api/auth/google"
FLOW_SECONDS = 600


class OAuthError(Exception):
    """The sign-in could not be completed. The message is for logs and tests, never shown to the person."""


@dataclass
class GoogleIdentity:
    sub: str
    email: str


def enabled() -> bool:
    return bool(settings.google_client_id and settings.google_client_secret)


def redirect_uri() -> str:
    # Same address the browser uses for the website, so the cookies stay on one site (Vercel forwards /api).
    return f"{settings.frontend_url.rstrip('/')}/api/auth/google/callback"


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def pkce_challenge(verifier: str) -> str:
    return _b64url(hashlib.sha256(verifier.encode()).digest())


def start_flow() -> tuple[str, str]:
    """Returns (address to send the browser to, signed value for the flow cookie)."""
    state, nonce, verifier = secrets.token_urlsafe(24), secrets.token_urlsafe(24), secrets.token_urlsafe(64)
    query = urlencode(
        {
            "client_id": settings.google_client_id,
            "redirect_uri": redirect_uri(),
            "response_type": "code",
            "scope": "openid email",
            "state": state,
            "nonce": nonce,
            "code_challenge": pkce_challenge(verifier),
            "code_challenge_method": "S256",
            "prompt": "select_account",
        }
    )
    cookie = jwt.encode(
        {"state": state, "nonce": nonce, "verifier": verifier, "exp": int(time.time()) + FLOW_SECONDS}, effective_jwt_secret(), algorithm="HS256"
    )
    return f"{AUTH_URL}?{query}", cookie


def read_flow_cookie(value: str | None) -> dict:
    if not value:
        raise OAuthError("missing flow cookie")
    try:
        return jwt.decode(value, effective_jwt_secret(), algorithms=["HS256"])
    except jwt.PyJWTError as e:
        raise OAuthError("invalid or expired flow cookie") from e


def exchange_code(code: str, verifier: str) -> dict:
    """Trade the one-time code for Google's ID token and return its claims (a direct, TLS-protected call to
    Google's token address, which is why the token's signature need not be re-checked, as the OpenID spec allows)."""
    try:
        response = httpx.post(
            TOKEN_URL,
            data={
                "code": code, "client_id": settings.google_client_id, "client_secret": settings.google_client_secret,
                "redirect_uri": redirect_uri(), "grant_type": "authorization_code", "code_verifier": verifier,
            },
            timeout=15,
        )
    except httpx.HTTPError as e:
        raise OAuthError("token request failed") from e
    if response.status_code != 200 or "id_token" not in response.json():
        raise OAuthError(f"token endpoint answered {response.status_code}")
    return jwt.decode(response.json()["id_token"], options={"verify_signature": False})


def identity_from_claims(claims: dict, nonce: str) -> GoogleIdentity:
    if claims.get("iss") not in ISSUERS:
        raise OAuthError("wrong issuer")
    audience = claims.get("aud")
    if settings.google_client_id not in (audience if isinstance(audience, list) else [audience]):
        raise OAuthError("token was issued for a different application")
    if int(claims.get("exp", 0)) < time.time():
        raise OAuthError("token expired")
    if claims.get("nonce") != nonce:
        raise OAuthError("nonce mismatch")
    if claims.get("email_verified") is not True or not claims.get("email") or not claims.get("sub"):
        raise OAuthError("Google did not vouch for this email address")
    return GoogleIdentity(sub=str(claims["sub"]), email=str(claims["email"]).strip().lower())
