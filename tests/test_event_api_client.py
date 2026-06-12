"""EventApiClient 단위 테스트."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from src.integrations.event_api_client import EventApiClient
from src.common.types import Event


def _make_event() -> Event:
    return Event.create(
        event_type="ENTER",
        track_id=1,
        zone_id="zone_a",
        bbox=[10.0, 20.0, 110.0, 220.0],
        foot_point=[60.0, 220.0],
        frame_number=100,
        video_source="webcam:0",
        timestamp="00:00:03.333",
    )


class TestEventApiClient:
    def test_send_event_returns_true_on_201(self):
        client = EventApiClient(base_url="http://localhost:8000")
        mock_resp = MagicMock()
        mock_resp.status_code = 201

        with patch.object(client._session, "post", return_value=mock_resp):
            result = client.send_event(_make_event())

        assert result is True

    def test_send_event_returns_true_on_409_duplicate(self):
        client = EventApiClient(base_url="http://localhost:8000")
        mock_resp = MagicMock()
        mock_resp.status_code = 409

        with patch.object(client._session, "post", return_value=mock_resp):
            result = client.send_event(_make_event())

        assert result is True

    def test_send_event_returns_false_on_500(self):
        client = EventApiClient(base_url="http://localhost:8000")
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "Internal Server Error"

        with patch.object(client._session, "post", return_value=mock_resp):
            result = client.send_event(_make_event())

        assert result is False

    def test_send_event_returns_false_on_connection_error(self):
        client = EventApiClient(base_url="http://localhost:8000")

        with patch.object(
            client._session,
            "post",
            side_effect=requests.ConnectionError("connection refused"),
        ):
            result = client.send_event(_make_event())

        assert result is False

    def test_send_current_status_returns_true_on_200(self):
        client = EventApiClient(base_url="http://localhost:8000")
        mock_resp = MagicMock()
        mock_resp.ok = True

        with patch.object(client._session, "put", return_value=mock_resp):
            result = client.send_current_status(
                {
                    "source": "webcam:0",
                    "frame_number": 30,
                    "active_track_count": 2,
                    "zone_occupancy": [],
                    "updated_at": "2026-06-09T10:00:00+09:00",
                }
            )

        assert result is True

    def test_send_current_status_returns_false_on_network_error(self):
        client = EventApiClient(base_url="http://localhost:8000")

        with patch.object(
            client._session,
            "put",
            side_effect=requests.Timeout("timeout"),
        ):
            result = client.send_current_status({"source": "webcam:0"})

        assert result is False

    def test_pipeline_survives_api_failure(self):
        """API 실패가 예외를 올리지 않아야 한다."""
        client = EventApiClient(base_url="http://localhost:8000")

        with patch.object(
            client._session,
            "post",
            side_effect=requests.ConnectionError("server down"),
        ):
            # 예외 없이 False 반환
            for _ in range(5):
                result = client.send_event(_make_event())
                assert result is False
