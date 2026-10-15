"""FastAPI Live Frame 전송 클라이언트.

Vision AI 파이프라인의 최신 프레임을 JPEG로 인코딩해 PUT /live/frame으로
전송한다. API 서버가 꺼져 있거나 요청이 실패해도 파이프라인은 종료되지
않는다. 실패는 로그로만 기록한다.

계약: docs/api_contract.md의 `PUT /live/frame`, ADR-015.

HTTP 전송 책임만 가지며, latest-only 비차단 처리(ADR-017)는
`LiveFrameDispatcher`(live_frame_dispatcher.py)가 담당한다.

retry는 구현하지 않는다 (ADR-017: CurrentStatus/Live Frame은 retry 없음).
실패한 frame을 retry로 붙잡는 대신 다음 최신 frame을 보내는 것이
latest-only 목적과 FPS 보호에 맞다.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

import cv2
import numpy as np
import requests

LOGGER = logging.getLogger(__name__)

_LOG_COOLDOWN_SEC = 5.0

_TARGET_WIDTH = 640
_TARGET_HEIGHT = 480
_DEFAULT_QUALITY = 75
_DEFAULT_MIN_INTERVAL_SEC = 0.5  # 1~2 FPS
_DEFAULT_CONNECT_TIMEOUT_SEC = 0.5
_DEFAULT_READ_TIMEOUT_SEC = 1.0


class LiveFrameClient:
    """Vision AI → FastAPI Live Frame 전송 클라이언트."""

    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        quality: int = _DEFAULT_QUALITY,
        min_interval_sec: float = _DEFAULT_MIN_INTERVAL_SEC,
        connect_timeout_sec: float = _DEFAULT_CONNECT_TIMEOUT_SEC,
        read_timeout_sec: float = _DEFAULT_READ_TIMEOUT_SEC,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._quality = quality
        self._min_interval_sec = min_interval_sec
        self._timeout = (connect_timeout_sec, read_timeout_sec)
        self._session = requests.Session()
        self._last_warn_time: float = 0.0
        self._last_sent_time: float = 0.0

    def _warn(self, msg: str, *args: Any) -> None:
        now = time.monotonic()
        if now - self._last_warn_time >= _LOG_COOLDOWN_SEC:
            LOGGER.warning(msg, *args)
            self._last_warn_time = now

    def _should_send(self) -> bool:
        now = time.monotonic()
        if now - self._last_sent_time < self._min_interval_sec:
            return False
        return True

    def _encode(self, frame: np.ndarray) -> Optional[bytes]:
        height, width = frame.shape[:2]
        if height <= 0 or width <= 0:
            self._warn("JPEG 인코딩 실패: 빈 frame")
            return None

        scale = min(_TARGET_WIDTH / width, _TARGET_HEIGHT / height, 1.0)
        if scale < 1.0:
            target_size = (
                max(1, round(width * scale)),
                max(1, round(height * scale)),
            )
            frame = cv2.resize(frame, target_size, interpolation=cv2.INTER_AREA)

        ok, buffer = cv2.imencode(
            ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, self._quality]
        )
        if not ok:
            self._warn("JPEG 인코딩 실패")
            return None
        return buffer.tobytes()

    def send_frame(
        self,
        frame: np.ndarray,
        source: str,
        frame_number: int,
        captured_at: str,
    ) -> bool:
        """최신 frame을 PUT /live/frame으로 전송한다.

        1~2 FPS rate limit에 걸리면 전송하지 않고 False를 반환한다.

        Returns:
            True if 2xx, False otherwise (pipeline does not stop on failure).
        """
        if not self._should_send():
            return False

        jpeg_bytes = self._encode(frame)
        if jpeg_bytes is None:
            return False

        # 성공 여부와 무관하게 "전송 시도 시점"에 rate limit을 건다.
        # 성공 시에만 갱신하면 API 장애 시 매 프레임 재시도로 FPS가 급락한다.
        self._last_sent_time = time.monotonic()

        try:
            resp = self._session.put(
                f"{self._base_url}/live/frame",
                params={
                    "source": source,
                    "frame_number": frame_number,
                    "captured_at": captured_at,
                },
                data=jpeg_bytes,
                headers={"Content-Type": "image/jpeg"},
                timeout=self._timeout,
            )
            if resp.ok:
                return True
            self._warn(
                "PUT /live/frame 실패: status=%d body=%s",
                resp.status_code,
                resp.text[:200],
            )
            return False
        except requests.RequestException as exc:
            self._warn("PUT /live/frame 요청 실패 (API 서버 확인 필요): %s", exc)
            return False

    def close(self) -> None:
        self._session.close()
