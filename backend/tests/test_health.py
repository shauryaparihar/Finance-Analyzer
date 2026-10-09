from fastapi.testclient import TestClient
from sqlalchemy import create_engine

import backend.main as main


def test_healthz_does_not_need_the_database():
    client = TestClient(main.app)
    assert client.get("/healthz").json() == {"status": "healthy"}


def test_readyz_succeeds_when_database_is_reachable(test_engine, monkeypatch):
    monkeypatch.setattr(main, "engine", test_engine)
    response = TestClient(main.app).get("/readyz")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_readyz_fails_when_database_is_unreachable(monkeypatch):
    unreachable = create_engine("postgresql+psycopg://nobody:nopass@127.0.0.1:1/none", connect_args={"connect_timeout": 1})
    monkeypatch.setattr(main, "engine", unreachable)
    response = TestClient(main.app).get("/readyz")
    assert response.status_code == 503
    assert "127.0.0.1" not in response.text
