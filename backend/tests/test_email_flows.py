import re

import pytest
from sqlalchemy import select, text

from backend.api.auth import CSRF_HEADER, REFRESH_COOKIE
from backend.core import mail
from backend.core import repository as repo
from backend.core.config import settings
from backend.core.models import EmailToken
from backend.tests.conftest import PASSWORD

CSRF = {CSRF_HEADER: "1"}
EMAIL = "reader@example.com"


@pytest.fixture
def outbox(monkeypatch):
    monkeypatch.setattr(settings, "mail_backend", "console")
    sent = []
    monkeypatch.setattr(mail, "send", lambda to, subject, body: sent.append((to, subject, body)))
    return sent


def _token(message) -> str:
    return re.search(r"token=([\w\-]+)", message[2]).group(1)


def _register(client, email=EMAIL):
    assert client.post("/api/auth/register", json={"email": email, "password": PASSWORD}).status_code == 201


def _login_headers(client, email=EMAIL, password=PASSWORD):
    token = client.post("/api/auth/login", json={"email": email, "password": password}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_the_email_features_are_off_unless_a_backend_is_configured(client):
    assert client.get("/api/auth/providers").json()["email"] is False
    for path, body in (("forgot-password", {"email": EMAIL}), ("reset-password", {"token": "x" * 20, "password": PASSWORD}), ("verify-email", {"token": "x" * 20})):
        assert client.post(f"/api/auth/{path}", json=body, headers=CSRF).status_code == 404


def test_registering_sends_a_verification_link_that_works_once(client, outbox, db):
    _register(client)
    assert len(outbox) == 1 and outbox[0][0] == EMAIL and "confirm" in outbox[0][1].lower()
    headers = _login_headers(client)
    assert client.get("/api/auth/me", headers=headers).json()["email_verified"] is False
    token = _token(outbox[0])
    assert client.post("/api/auth/verify-email", json={"token": token}, headers=CSRF).status_code == 204
    assert client.get("/api/auth/me", headers=headers).json()["email_verified"] is True
    again = client.post("/api/auth/verify-email", json={"token": token}, headers=CSRF)
    assert again.status_code == 400 and again.json()["error"]["code"] == "INVALID_LINK"


def test_only_a_hash_of_the_link_secret_is_stored(client, outbox, db):
    _register(client)
    raw = _token(outbox[0])
    stored = db.scalars(select(EmailToken)).all()
    assert len(stored) == 1 and raw not in stored[0].token_hash and len(stored[0].token_hash) == 64


def test_an_expired_or_made_up_link_is_refused(client, outbox, db):
    _register(client)
    token = _token(outbox[0])
    db.execute(text("UPDATE email_tokens SET expires_at = now() - interval '1 minute'"))
    db.commit()
    assert client.post("/api/auth/verify-email", json={"token": token}, headers=CSRF).status_code == 400
    assert client.post("/api/auth/verify-email", json={"token": "made-up-token-value"}, headers=CSRF).status_code == 400


def test_the_cookie_endpoints_need_the_safety_header(client, outbox):
    assert client.post("/api/auth/forgot-password", json={"email": EMAIL}).status_code == 403
    assert client.post("/api/auth/verify-email", json={"token": "x" * 20}).status_code == 403


def test_a_failing_email_service_never_breaks_registration(client, monkeypatch):
    monkeypatch.setattr(settings, "mail_backend", "console")

    def broken(*args):
        raise mail.MailError("down")

    monkeypatch.setattr(mail, "send", broken)
    _register(client)
    assert client.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD}).status_code == 200


def test_forgot_password_answers_the_same_for_known_and_unknown_addresses(client, outbox):
    _register(client)
    outbox.clear()
    known = client.post("/api/auth/forgot-password", json={"email": EMAIL}, headers=CSRF)
    unknown = client.post("/api/auth/forgot-password", json={"email": "nobody@example.com"}, headers=CSRF)
    assert known.status_code == unknown.status_code == 202 and known.json() == unknown.json()
    assert [m[0] for m in outbox] == [EMAIL]  # only the real account got an email


def test_asking_again_within_a_minute_sends_nothing_more(client, outbox):
    _register(client)
    outbox.clear()
    for _ in range(3):
        client.post("/api/auth/forgot-password", json={"email": EMAIL}, headers=CSRF)
    assert len(outbox) == 1


def test_a_reset_link_sets_a_new_password_ends_old_sessions_and_works_once(client, outbox):
    _register(client)
    outbox.clear()
    old_cookie = client.cookies.get(REFRESH_COOKIE) or client.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD}).cookies.get(REFRESH_COOKIE)
    client.post("/api/auth/forgot-password", json={"email": EMAIL}, headers=CSRF)
    token = _token(outbox[0])
    done = client.post("/api/auth/reset-password", json={"token": token, "password": "a-brand-new-pass"}, headers=CSRF)
    assert done.status_code == 204
    assert client.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD}).status_code == 401
    assert client.post("/api/auth/login", json={"email": EMAIL, "password": "a-brand-new-pass"}).status_code == 200
    client.cookies.clear()
    client.cookies.set(REFRESH_COOKIE, old_cookie, path="/api/auth")
    assert client.post("/api/auth/refresh", headers=CSRF).status_code == 401  # the session from before the reset is gone
    reuse = client.post("/api/auth/reset-password", json={"token": token, "password": "another-new-pass"}, headers=CSRF)
    assert reuse.status_code == 400
    me = client.get("/api/auth/me", headers=_login_headers(client, password="a-brand-new-pass")).json()
    assert me["email_verified"] is True  # reaching the inbox proves the address


def test_only_the_newest_reset_link_works_and_weak_passwords_are_refused(client, outbox, db):
    _register(client)
    outbox.clear()
    client.post("/api/auth/forgot-password", json={"email": EMAIL}, headers=CSRF)
    first = _token(outbox[0])
    db.execute(text("UPDATE email_tokens SET created_at = now() - interval '5 minutes'"))
    db.commit()
    client.post("/api/auth/forgot-password", json={"email": EMAIL}, headers=CSRF)
    second = _token(outbox[1])
    assert client.post("/api/auth/reset-password", json={"token": first, "password": "a-brand-new-pass"}, headers=CSRF).status_code == 400
    assert client.post("/api/auth/reset-password", json={"token": second, "password": "short"}, headers=CSRF).status_code == 422
    assert client.post("/api/auth/reset-password", json={"token": second, "password": "a-brand-new-pass"}, headers=CSRF).status_code == 204


def test_disabled_and_demo_accounts_get_no_reset_email(client, outbox, db):
    _register(client)
    user = repo.get_user_by_email(db, EMAIL)
    repo.set_user_active(db, user.id, False)
    repo.get_or_create_demo_user(db)
    outbox.clear()
    client.post("/api/auth/forgot-password", json={"email": EMAIL}, headers=CSRF)
    client.post("/api/auth/forgot-password", json={"email": repo.DEMO_EMAIL}, headers=CSRF)
    assert outbox == []


def test_resending_the_verification_email_needs_login_and_respects_the_cooldown(client, outbox):
    _register(client)
    headers = _login_headers(client)
    outbox.clear()
    assert client.post("/api/auth/send-verification").status_code == 401
    assert client.post("/api/auth/send-verification", headers=headers).status_code == 202
    assert outbox == []  # the registration email was sent seconds ago, so the cooldown holds it back
