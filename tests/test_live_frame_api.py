import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.api.main import app


JPEG_BYTES = b"\xff\xd8kidcafe-live-frame\xff\xd9"
NEXT_JPEG_BYTES = b"\xff\xd8kidcafe-live-frame-next\xff\xd9"


@pytest.fixture(autouse=True)
def clear_live_frame_store():
    try:
        from src.api.live_frame_store import live_frame_store
    except ModuleNotFoundError:
        yield
        return

    live_frame_store.clear()
    yield
    live_frame_store.clear()


@pytest.fixture()
def client(tmp_path, monkeypatch):
    default_db_path = Path("outputs/kidcafe_events.db")
    default_db_exists = default_db_path.exists()
    db_path = tmp_path / "kidcafe_events_test.db"
    monkeypatch.setenv("KIDCAFE_DB_PATH", str(db_path))
    with TestClient(app) as test_client:
        yield test_client
    assert os.path.exists(db_path)
    assert default_db_path.exists() == default_db_exists


def put_live_frame(client, body=JPEG_BYTES, **params):
    request_params = {
        "source": "webcam:0",
        "frame_number": 100,
        "captured_at": "2026-07-07T12:00:00Z",
    }
    request_params.update(params)
    return client.put(
        "/live/frame",
        params=request_params,
        content=body,
        headers={"Content-Type": "image/jpeg"},
    )


def test_get_live_frame_returns_204_when_empty(client):
    response = client.get("/live/frame")

    assert response.status_code == 204
    assert response.content == b""


def test_put_live_frame_stores_jpeg_and_returns_success(client):
    response = put_live_frame(client)

    assert response.status_code == 200
    assert response.json() == {
        "status": "success",
        "data": {
            "source": "webcam:0",
            "frame_number": 100,
            "stored": True,
        },
        "message": None,
    }


def test_get_live_frame_returns_latest_jpeg_with_headers(client):
    assert put_live_frame(client).status_code == 200

    response = client.get("/live/frame")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-source"] == "webcam:0"
    assert response.headers["x-frame-number"] == "100"
    assert response.headers["x-captured-at"] == "2026-07-07T12:00:00Z"
    assert response.content == JPEG_BYTES


def test_put_live_frame_rejects_non_jpeg_content_type(client):
    response = client.put(
        "/live/frame",
        params={
            "source": "webcam:0",
            "frame_number": 100,
            "captured_at": "2026-07-07T12:00:00Z",
        },
        content=JPEG_BYTES,
        headers={"Content-Type": "application/octet-stream"},
    )

    assert response.status_code == 415
    assert response.json()["status"] == "error"


def test_put_live_frame_rejects_invalid_jpeg_magic_bytes(client):
    response = put_live_frame(client, body=b"not-a-jpeg")

    assert response.status_code == 415
    assert response.json()["status"] == "error"


def test_put_live_frame_rejects_payload_over_one_mib(client):
    too_large = b"\xff\xd8" + (b"x" * (1024 * 1024)) + b"\xff\xd9"

    response = put_live_frame(client, body=too_large)

    assert response.status_code == 413
    assert response.json()["status"] == "error"


def test_put_live_frame_rejects_empty_source(client):
    response = put_live_frame(client, source="")

    assert response.status_code == 422


def test_put_live_frame_rejects_negative_frame_number(client):
    response = put_live_frame(client, frame_number=-1)

    assert response.status_code == 422


def test_put_live_frame_rejects_invalid_captured_at(client):
    response = put_live_frame(client, captured_at="not-a-datetime")

    assert response.status_code == 422
    assert response.json()["status"] == "error"


def test_put_live_frame_normalizes_plus_zero_utc_to_z(client):
    response = put_live_frame(client, captured_at="2026-07-07T12:00:00+00:00")
    assert response.status_code == 200

    get_response = client.get("/live/frame")

    assert get_response.status_code == 200
    assert get_response.headers["x-captured-at"] == "2026-07-07T12:00:00Z"


@pytest.mark.parametrize("elapsed_sec", [3.0, 3.1])
def test_get_live_frame_returns_204_when_stale(client, monkeypatch, elapsed_sec):
    import src.api.live_frame_store as store_module

    now = {"value": 100.0}
    monkeypatch.setattr(store_module.time, "monotonic", lambda: now["value"])
    assert put_live_frame(client).status_code == 200

    now["value"] = 100.0 + elapsed_sec
    response = client.get("/live/frame")

    assert response.status_code == 204
    assert response.content == b""


def test_put_live_frame_replaces_existing_frame_with_latest(client):
    assert put_live_frame(client, body=JPEG_BYTES, frame_number=100).status_code == 200
    assert put_live_frame(client, body=NEXT_JPEG_BYTES, frame_number=101).status_code == 200

    response = client.get("/live/frame")

    assert response.status_code == 200
    assert response.headers["x-frame-number"] == "101"
    assert response.content == NEXT_JPEG_BYTES
