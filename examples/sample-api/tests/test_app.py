from fastapi.testclient import TestClient
from sample_api.app import app

client = TestClient(app)


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_products() -> None:
    response = client.get("/products")
    assert response.status_code == 200
    assert len(response.json()) == 4
