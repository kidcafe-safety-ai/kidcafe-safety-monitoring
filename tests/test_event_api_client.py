"""EventApiClient 단위 테스트."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import requests

from src.integrations.event_api_client import EventApiClient
from src.common.types import Event, EventCause, EventCauseEvidence


def _make_event(**overrides) -> Event:
    defaults = dict(
        event_type="ENTER",
        track_id=1,
        zone_id="zone_a",
        bbox=[10.0, 20.0, 110.0, 220.0],
        foot_point=[60.0, 220.0],
        frame_number=100,
        video_source="webcam:0",
        timestamp="00:00:03.333",
    )
    defaults.update(overrides)
    return Event.create(**defaults)


class TestEventApiClient:
    def test_send_event_returns_true_on_201(self):
        client = EventApiClient(base_url="http://localhost:8000")
        mock_resp = MagicMock()
        mock_resp.status_code = 201

        with patch.object(client._session, "post", return_value=mock_resp):
            result = client.send_event(_make_event())

        assert result is True

    def test_send_event_uses_default_adr_017_timeout(self):
        """ADR-017 계약: connect timeout 0.5초, read timeout 1.0초 (기본값)."""
        client = EventApiClient(base_url="http://localhost:8000")
        mock_resp = MagicMock()
        mock_resp.status_code = 201

        with patch.object(client._session, "post", return_value=mock_resp) as mock_post:
            client.send_event(_make_event())

        assert mock_post.call_args.kwargs["timeout"] == (0.5, 1.0)

    def test_send_current_status_uses_default_adr_017_timeout(self):
        client = EventApiClient(base_url="http://localhost:8000")
        mock_resp = MagicMock()
        mock_resp.ok = True

        with patch.object(client._session, "put", return_value=mock_resp) as mock_put:
            client.send_current_status({"source": "webcam:0"})

        assert mock_put.call_args.kwargs["timeout"] == (0.5, 1.0)

    def test_timeout_is_configurable(self):
        client = EventApiClient(
            base_url="http://localhost:8000",
            connect_timeout_sec=1.0,
            read_timeout_sec=2.0,
        )
        mock_resp = MagicMock()
        mock_resp.status_code = 201

        with patch.object(client._session, "post", return_value=mock_resp) as mock_post:
            client.send_event(_make_event())

        assert mock_post.call_args.kwargs["timeout"] == (1.0, 2.0)

    def test_send_event_payload_includes_confidence_event_confidence_and_cause(self):
        """Phase 3 필드가 조용히 유실되지 않고 payload에 포함돼야 한다."""
        client = EventApiClient(base_url="http://localhost:8000")
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        event = _make_event(
            event_type="FALL_SUSPECT",
            zone_id="__global__",
            confidence=0.91,
            event_confidence=0.82,
            cause=EventCause(
                type="NEARBY_TRACK",
                track_id=7,
                score=0.68,
                evidence=EventCauseEvidence(
                    min_distance_norm=0.31,
                    closing_speed_norm=0.74,
                    time_to_fall_sec=0.42,
                ),
            ),
        )

        with patch.object(client._session, "post", return_value=mock_resp) as mock_post:
            client.send_event(event)

        payload = mock_post.call_args.kwargs["json"]
        assert payload["confidence"] == 0.91
        assert payload["event_confidence"] == 0.82
        assert payload["cause"] == {
            "type": "NEARBY_TRACK",
            "track_id": 7,
            "score": 0.68,
            "evidence": {
                "min_distance_norm": 0.31,
                "closing_speed_norm": 0.74,
                "time_to_fall_sec": 0.42,
            },
        }

    def test_send_event_payload_cause_is_none_when_event_has_no_cause(self):
        client = EventApiClient(base_url="http://localhost:8000")
        mock_resp = MagicMock()
        mock_resp.status_code = 201

        with patch.object(client._session, "post", return_value=mock_resp) as mock_post:
            client.send_event(_make_event())

        payload = mock_post.call_args.kwargs["json"]
        assert payload["cause"] is None
        assert payload["event_confidence"] is None

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
