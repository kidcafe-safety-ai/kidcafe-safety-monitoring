"""scripts/api_smoke_test.py, scripts/sqlite_db.py 테스트."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from scripts import api_smoke_test as smoke
from scripts import sqlite_db
from src.api.live_frame_store import live_frame_store
from src.api.main import app


@pytest.fixture()
def db_path(tmp_path, monkeypatch):
    path = tmp_path / "kidcafe_events.db"
    monkeypatch.setenv("KIDCAFE_DB_PATH", str(path))
    return path


@pytest.fixture()
def zones_path(tmp_path, monkeypatch):
    path = tmp_path / "zones_runtime.json"
    path.write_text("[]", encoding="utf-8")
    monkeypatch.setenv("KIDCAFE_ZONES_PATH", str(path))
    return path


def make_request_fn(client: TestClient) -> smoke.RequestFn:
    def request(method, path, body, headers):
        response = client.request(method, path, content=body, headers=headers)
        return response.status_code, dict(response.headers), response.content

    return request


def insert_event(db_path, event_id=None):
    conn = sqlite3.connect(db_path)
    with conn:
        conn.execute(
            """
            INSERT INTO events (
                event_id, event_type, track_id, zone_id, frame_number,
                timestamp, bbox_json, foot_point_json, video_source
            ) VALUES (?, 'ENTER', 1, 'z', 1, '00:00:01.000', '[0,0,1,1]', '[0,0]', 'v')
            """,
            (event_id or f"event-{uuid4()}",),
        )
    conn.close()


# --- smoke test -----------------------------------------------------------


def test_smoke_read_only_checks_pass_and_do_not_write(db_path, zones_path):
    live_frame_store.clear()
    with TestClient(app) as client:
        results = smoke.run_checks(make_request_fn(client))

        assert all(result.ok for result in results), results
        assert client.get("/events").json()["data"]["total"] == 0


def test_smoke_write_checks_create_one_event_and_detect_duplicate(db_path, zones_path):
    with TestClient(app) as client:
        results = smoke.run_checks(make_request_fn(client), write=True)

        assert all(result.ok for result in results), results
        items = client.get("/events").json()["data"]["items"]
        assert len(items) == 1
        assert items[0]["video_source"] == smoke.SMOKE_VIDEO_SOURCE


def test_smoke_reports_failure_when_zone_runtime_missing(db_path, tmp_path, monkeypatch):
    monkeypatch.setenv("KIDCAFE_ZONES_PATH", str(tmp_path / "missing.json"))
    with TestClient(app) as client:
        results = {r.name: r for r in smoke.run_checks(make_request_fn(client))}

    assert results["GET /zones"].ok is False
    assert results["GET /health"].ok is True


def test_smoke_main_returns_1_when_api_unreachable(capsys):
    exit_code = smoke.main(["--base-url", "http://127.0.0.1:9", "--timeout", "0.5"])

    assert exit_code == 1
    assert "FAIL" in capsys.readouterr().out


# --- sqlite_db ------------------------------------------------------------


def test_backup_copies_rows_with_timestamped_name(db_path, tmp_path):
    sqlite_db.init_db()
    insert_event(db_path)
    dest_dir = tmp_path / "backups"

    first = sqlite_db.backup(db_path, dest_dir, now=datetime(2026, 10, 12, 10, 15, 0))
    second = sqlite_db.backup(db_path, dest_dir, now=datetime(2026, 10, 12, 10, 15, 0))

    assert first.name == "kidcafe_events_20261012_101500.db"
    assert second != first
    assert sqlite_db.count_rows(first) == {"events": 1, "current_status": 0}


def test_backup_fails_when_db_missing(db_path, tmp_path):
    with pytest.raises(FileNotFoundError):
        sqlite_db.backup(db_path, tmp_path / "backups")


def test_reset_backs_up_then_empties_db(db_path, tmp_path):
    sqlite_db.init_db()
    insert_event(db_path)
    dest_dir = tmp_path / "backups"

    previous = sqlite_db.reset(db_path, dest_dir)

    assert sqlite_db.count_rows(previous)["events"] == 1
    assert sqlite_db.count_rows(db_path) == {"events": 0, "current_status": 0}


def test_reset_restarts_event_ids_and_api_keeps_working(db_path, tmp_path):
    with TestClient(app) as client:
        insert_event(db_path)
        insert_event(db_path)
        sqlite_db.reset(db_path, tmp_path / "backups")

        insert_event(db_path)
        items = client.get("/events").json()["data"]["items"]

    assert [item["id"] for item in items] == [1]


def test_restore_replaces_db_and_keeps_previous_backup(db_path, tmp_path):
    sqlite_db.init_db()
    insert_event(db_path, "kept-in-backup")
    dest_dir = tmp_path / "backups"
    snapshot = sqlite_db.backup(db_path, dest_dir)
    insert_event(db_path, "added-after-backup")

    previous = sqlite_db.restore(snapshot, db_path, dest_dir)

    assert sqlite_db.count_rows(previous)["events"] == 2
    conn = sqlite3.connect(db_path)
    ids = [row[0] for row in conn.execute("SELECT event_id FROM events")]
    conn.close()
    assert ids == ["kept-in-backup"]


def test_restore_rejects_non_kidcafe_database(db_path, tmp_path):
    other = tmp_path / "other.db"
    conn = sqlite3.connect(other)
    conn.execute("CREATE TABLE something (id INTEGER)")
    conn.close()

    with pytest.raises(ValueError):
        sqlite_db.restore(other, db_path, tmp_path / "backups")


@pytest.mark.parametrize("command", [["reset"], ["restore", "x.db"]])
def test_destructive_commands_require_yes(db_path, command):
    assert sqlite_db.main(command) == 2
    assert not db_path.exists()


def test_main_backup_returns_1_when_db_missing(db_path, capsys):
    assert sqlite_db.main(["backup"]) == 1
    assert "실패" in capsys.readouterr().out
