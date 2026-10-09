from fastapi.testclient import TestClient

from backend.main import app


def test_health_endpoint():
    # No "with" block: startup hooks (and the database) are intentionally not run.
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}
