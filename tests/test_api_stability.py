import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.api.main import app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    default_db_path = Path("outputs/kidcafe_events.db")
    default_db_exists = default_db_path.exists()
    db_path = tmp_path / "kidcafe_phase25_stability.db"
    monkeypatch.setenv("KIDCAFE_DB_PATH", str(db_path))
    with TestClient(app) as test_client:
        yield test_client
    assert os.path.exists(db_path)
    assert default_db_path.exists() == default_db_exists


@pytest.mark.parametrize(
    "origin",
    [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
    ],
)
def test_cors_allows_react_development_origins(client, origin):
    response = client.options(
        "/health",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin
    assert response.headers["access-control-allow-credentials"] == "true"
    assert "GET" in response.headers["access-control-allow-methods"]


def test_validation_error_keeps_fastapi_default_detail_response(client):
    response = client.post("/events", json={})

    assert response.status_code == 422
    body = response.json()
    assert "detail" in body
    assert "status" not in body
    assert isinstance(body["detail"], list)


def test_status_current_accepts_optional_zone_name(client):
    payload = {
        "source": "camera_optional_zone_name",
        "frame_number": 10,
        "active_track_count": 1,
        "zone_occupancy": [
            {
                "zone_id": "playground_bottom_right",
                "zone_name": None,
                "current_count": 1,
                "risk_level": "HIGH",
            }
        ],
        "updated_at": "2026-06-25T10:00:00+09:00",
    }

    put_response = client.put("/status/current", json=payload)
    get_response = client.get("/status/current")

    assert put_response.status_code == 200
    assert put_response.json()["data"] == {
        "source": "camera_optional_zone_name",
        "updated": True,
    }
    assert get_response.status_code == 200
    assert get_response.json()["data"] == payload
