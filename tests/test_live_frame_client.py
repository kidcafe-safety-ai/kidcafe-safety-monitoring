"""LiveFrameClient 단위 테스트."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import cv2
import numpy as np
import requests

from src.integrations.live_frame_client import LiveFrameClient


def _make_frame(width: int = 1280, height: int = 720) -> np.ndarray:
    return np.zeros((height, width, 3), dtype=np.uint8)


class TestLiveFrameClient:
    def test_encode_rejects_empty_frame(self):
        client = LiveFrameClient(base_url="http://localhost:8000")

        assert client._encode(np.zeros((0, 0, 3), dtype=np.uint8)) is None

    def test_send_frame_puts_jpeg_with_query_params(self):
        client = LiveFrameClient(base_url="http://localhost:8000", min_interval_sec=0.0)
        mock_resp = MagicMock()
        mock_resp.ok = True

        with patch.object(client._session, "put", return_value=mock_resp) as mock_put:
            result = client.send_frame(
                _make_frame(),
                source="webcam:0",
                frame_number=100,
                captured_at="2026-07-08T12:00:00Z",
            )

        assert result is True
        mock_put.assert_called_once()
        _, kwargs = mock_put.call_args
        assert kwargs["params"] == {
            "source": "webcam:0",
            "frame_number": 100,
            "captured_at": "2026-07-08T12:00:00Z",
        }
        assert kwargs["headers"]["Content-Type"] == "image/jpeg"
        assert isinstance(kwargs["data"], bytes)
        assert len(kwargs["data"]) > 0

    def test_default_timeout_matches_adr_017(self):
        """ADR-017 계약: connect timeout 0.5초, read timeout 1.0초 (기본값)."""
        client = LiveFrameClient(base_url="http://localhost:8000", min_interval_sec=0.0)
        mock_resp = MagicMock()
        mock_resp.ok = True

        with patch.object(client._session, "put", return_value=mock_resp) as mock_put:
            client.send_frame(
                _make_frame(),
                source="webcam:0",
                frame_number=1,
                captured_at="2026-07-08T12:00:00Z",
            )

        _, kwargs = mock_put.call_args
        assert kwargs["timeout"] == (0.5, 1.0)

    def test_timeout_is_configurable(self):
        client = LiveFrameClient(
            base_url="http://localhost:8000",
            min_interval_sec=0.0,
            connect_timeout_sec=1.0,
            read_timeout_sec=2.0,
        )
        mock_resp = MagicMock()
        mock_resp.ok = True

        with patch.object(client._session, "put", return_value=mock_resp) as mock_put:
            client.send_frame(
                _make_frame(),
                source="webcam:0",
                frame_number=1,
                captured_at="2026-07-08T12:00:00Z",
            )

        _, kwargs = mock_put.call_args
        assert kwargs["timeout"] == (1.0, 2.0)

    def test_send_frame_preserves_landscape_aspect_ratio(self):
        client = LiveFrameClient(base_url="http://localhost:8000", min_interval_sec=0.0)
        mock_resp = MagicMock()
        mock_resp.ok = True

        with patch.object(client._session, "put", return_value=mock_resp), \
                patch("src.integrations.live_frame_client.cv2.resize") as mock_resize:
            mock_resize.return_value = _make_frame(640, 360)
            client.send_frame(
                _make_frame(1280, 720),
                source="webcam:0",
                frame_number=1,
                captured_at="2026-07-08T12:00:00Z",
            )

        args, kwargs = mock_resize.call_args
        assert args[1] == (640, 360)
        assert kwargs["interpolation"] == cv2.INTER_AREA

    def test_send_frame_preserves_portrait_aspect_ratio(self):
        client = LiveFrameClient(base_url="http://localhost:8000", min_interval_sec=0.0)
        mock_resp = MagicMock()
        mock_resp.ok = True

        with patch.object(client._session, "put", return_value=mock_resp), \
                patch("src.integrations.live_frame_client.cv2.resize") as mock_resize:
            mock_resize.return_value = _make_frame(270, 480)
            client.send_frame(
                _make_frame(1080, 1920),
                source="webcam:0",
                frame_number=1,
                captured_at="2026-07-08T12:00:00Z",
            )

        args, _ = mock_resize.call_args
        assert args[1] == (270, 480)

    def test_send_frame_does_not_upscale_small_frame(self):
        client = LiveFrameClient(base_url="http://localhost:8000", min_interval_sec=0.0)
        mock_resp = MagicMock()
        mock_resp.ok = True

        with patch.object(client._session, "put", return_value=mock_resp), \
                patch("src.integrations.live_frame_client.cv2.resize") as mock_resize:
            client.send_frame(
                _make_frame(320, 240),
                source="webcam:0",
                frame_number=1,
                captured_at="2026-07-08T12:00:00Z",
            )

        mock_resize.assert_not_called()

    def test_send_frame_applies_quality_setting(self):
        client = LiveFrameClient(
            base_url="http://localhost:8000", quality=42, min_interval_sec=0.0
        )
        mock_resp = MagicMock()
        mock_resp.ok = True

        with patch.object(client._session, "put", return_value=mock_resp), \
                patch("src.integrations.live_frame_client.cv2.imencode") as mock_imencode:
            mock_imencode.return_value = (True, np.zeros(10, dtype=np.uint8))
            client.send_frame(
                _make_frame(),
                source="webcam:0",
                frame_number=1,
                captured_at="2026-07-08T12:00:00Z",
            )

        encode_params = mock_imencode.call_args[0][2]
        assert encode_params == [cv2.IMWRITE_JPEG_QUALITY, 42]

    def test_send_frame_returns_true_on_204(self):
        client = LiveFrameClient(base_url="http://localhost:8000", min_interval_sec=0.0)
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.status_code = 204

        with patch.object(client._session, "put", return_value=mock_resp):
            result = client.send_frame(
                _make_frame(),
                source="webcam:0",
                frame_number=1,
                captured_at="2026-07-08T12:00:00Z",
            )

        assert result is True

    def test_send_frame_returns_false_on_500(self):
        client = LiveFrameClient(base_url="http://localhost:8000", min_interval_sec=0.0)
        mock_resp = MagicMock()
        mock_resp.ok = False
        mock_resp.status_code = 500
        mock_resp.text = "Internal Server Error"

        with patch.object(client._session, "put", return_value=mock_resp):
            result = client.send_frame(
                _make_frame(),
                source="webcam:0",
                frame_number=1,
                captured_at="2026-07-08T12:00:00Z",
            )

        assert result is False

    def test_send_frame_rate_limits_after_connection_error(self):
        """API 장애로 실패해도 rate limit은 걸려야 한다 (FPS 급락 방지)."""
        client = LiveFrameClient(base_url="http://localhost:8000", min_interval_sec=10.0)

        with patch.object(
            client._session, "put", side_effect=requests.ConnectionError("refused")
        ) as mock_put:
            first = client.send_frame(
                _make_frame(),
                source="webcam:0",
                frame_number=1,
                captured_at="2026-07-08T12:00:00Z",
            )
            second = client.send_frame(
                _make_frame(),
                source="webcam:0",
                frame_number=2,
                captured_at="2026-07-08T12:00:01Z",
            )

        assert first is False
        assert second is False
        mock_put.assert_called_once()

    def test_send_frame_returns_false_on_connection_error(self):
        client = LiveFrameClient(base_url="http://localhost:8000", min_interval_sec=0.0)

        with patch.object(
            client._session, "put", side_effect=requests.ConnectionError("refused")
        ):
            result = client.send_frame(
                _make_frame(),
                source="webcam:0",
                frame_number=1,
                captured_at="2026-07-08T12:00:00Z",
            )

        assert result is False

    def test_send_frame_does_not_raise_on_failure(self):
        client = LiveFrameClient(base_url="http://localhost:8000", min_interval_sec=0.0)

        with patch.object(
            client._session, "put", side_effect=requests.Timeout("timed out")
        ):
            try:
                result = client.send_frame(
                    _make_frame(),
                    source="webcam:0",
                    frame_number=1,
                    captured_at="2026-07-08T12:00:00Z",
                )
            except Exception as exc:  # noqa: BLE001
                assert False, f"send_frame raised {exc!r}"

        assert result is False

    def test_send_frame_skips_when_rate_limited(self):
        client = LiveFrameClient(base_url="http://localhost:8000", min_interval_sec=10.0)
        mock_resp = MagicMock()
        mock_resp.ok = True

        with patch.object(client._session, "put", return_value=mock_resp) as mock_put:
            first = client.send_frame(
                _make_frame(),
                source="webcam:0",
                frame_number=1,
                captured_at="2026-07-08T12:00:00Z",
            )
            second = client.send_frame(
                _make_frame(),
                source="webcam:0",
                frame_number=2,
                captured_at="2026-07-08T12:00:01Z",
            )

        assert first is True
        assert second is False
        mock_put.assert_called_once()

    def test_send_frame_allows_next_send_after_interval(self):
        client = LiveFrameClient(base_url="http://localhost:8000", min_interval_sec=0.05)
        mock_resp = MagicMock()
        mock_resp.ok = True

        with patch.object(client._session, "put", return_value=mock_resp) as mock_put:
            client.send_frame(
                _make_frame(),
                source="webcam:0",
                frame_number=1,
                captured_at="2026-07-08T12:00:00Z",
            )
            time.sleep(0.06)
            result = client.send_frame(
                _make_frame(),
                source="webcam:0",
                frame_number=2,
                captured_at="2026-07-08T12:00:01Z",
            )

        assert result is True
        assert mock_put.call_count == 2
