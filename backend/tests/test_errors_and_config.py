import pytest
from fastapi.testclient import TestClient

import backend.main as main
from backend.core.config import (
    DEV_JWT_SECRET,
    Settings,
    cors_origins,
    validate_runtime_settings,
)

GOOD_PROD = dict(environment="production", jwt_secret="x" * 40, frontend_url="https://app.example.com")


def test_every_response_carries_a_request_id_and_errors_repeat_it(client):
    ok = client.get("/healthz")
    assert ok.headers["x-request-id"]
    err = client.get("/api/auth/me")
    assert err.json()["error"]["request_id"] == err.headers["x-request-id"]


def test_a_safe_incoming_request_id_is_kept_and_an_unsafe_one_replaced(client):
    assert client.get("/healthz", headers={"X-Request-ID": "abc-12345678"}).headers["x-request-id"] == "abc-12345678"
    replaced = client.get("/healthz", headers={"X-Request-ID": "bad id\nwith stuff"}).headers["x-request-id"]
    assert replaced != "bad id\nwith stuff" and len(replaced) == 32


def test_unexpected_errors_return_a_generic_message_without_internals():
    @main.app.get("/_boom")
    def boom():
        raise RuntimeError("password=hunter2 select * from users")

    try:
        response = TestClient(main.app, raise_server_exceptions=False).get("/_boom")
    finally:
        main.app.router.routes = [r for r in main.app.router.routes if getattr(r, "path", "") != "/_boom"]
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    assert "hunter2" not in response.text and "select" not in response.text


def test_unknown_route_uses_the_standard_error_shape(client):
    response = client.get("/api/nope")
    assert response.status_code == 404 and response.json()["error"]["code"] == "NOT_FOUND"


@pytest.mark.parametrize(
    "overrides",
    [
        dict(jwt_secret=""),
        dict(jwt_secret=DEV_JWT_SECRET),
        dict(jwt_secret="short"),
        dict(frontend_url="http://localhost:5173"),
        dict(frontend_url="http://app.example.com"),
        dict(frontend_url="https://*.example.com"),
    ],
)
def test_production_refuses_unsafe_configuration(overrides):
    with pytest.raises(RuntimeError):
        validate_runtime_settings(Settings(**{**GOOD_PROD, **overrides}))


def test_production_accepts_a_safe_configuration_and_development_needs_nothing():
    validate_runtime_settings(Settings(**GOOD_PROD))
    validate_runtime_settings(Settings(environment="development"))


def test_cors_allows_only_the_exact_frontend_in_production():
    assert cors_origins(Settings(**GOOD_PROD)) == ["https://app.example.com"]
    dev = cors_origins(Settings(environment="development"))
    assert "*" not in dev and "http://localhost:5173" in dev


def test_extra_frontend_origins_are_allowed_but_only_as_exact_https_origins_in_production():
    extra = Settings(**{**GOOD_PROD, "extra_frontend_origins": "https://myfinance.example.com/, https://preview.example.com"})
    assert cors_origins(extra) == ["https://app.example.com", "https://myfinance.example.com", "https://preview.example.com"]
    validate_runtime_settings(extra)
    for bad in ("http://myfinance.example.com", "https://*.example.com", "https://localhost:3000"):
        with pytest.raises(RuntimeError):
            validate_runtime_settings(Settings(**{**GOOD_PROD, "extra_frontend_origins": bad}))
    assert "http://127.0.0.1:9999" in cors_origins(Settings(environment="development", extra_frontend_origins="http://127.0.0.1:9999"))
