"""FastAPI 이벤트 전송 클라이언트.

API 서버가 꺼져 있거나 요청이 실패해도 Vision AI 파이프라인은 종료되지 않는다.
실패는 로그로만 기록한다.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict

import requests

from src.common.types import Event

LOGGER = logging.getLogger(__name__)

_LOG_COOLDOWN_SEC = 5.0


class EventApiClient:
    """Vision AI → FastAPI 이벤트/상태 전송 클라이언트."""

    def __init__(self, base_url: str = "http://localhost:8000") -> None:
        self._base_url = base_url.rstrip("/")
        self._session = requests.Session()
        self._last_warn_time: float = 0.0

    def _warn(self, msg: str, *args: Any) -> None:
        now = time.monotonic()
        if now - self._last_warn_time >= _LOG_COOLDOWN_SEC:
            LOGGER.warning(msg, *args)
            self._last_warn_time = now

    def send_event(self, event: Event) -> bool:
        """이벤트를 POST /events로 전송한다.

        Returns:
            True if 201, False otherwise (pipeline does not stop on failure).
        """
        payload = {
            "event_id": event.event_id,
            "timestamp": event.timestamp,
            "event_type": event.event_type,
            "track_id": event.track_id,
            "zone_id": event.zone_id,
            "bbox": event.bbox,
            "foot_point": event.foot_point,
            "frame_number": event.frame_number,
            "video_source": event.video_source,
        }
        try:
            resp = self._session.post(
                f"{self._base_url}/events",
                json=payload,
                timeout=2.0,
            )
            if resp.status_code == 201:
                return True
            if resp.status_code == 409:
                # 중복 event_id: 재시작 등으로 발생 가능 → 무시
                return True
            self._warn(
                "POST /events 실패: status=%d body=%s",
                resp.status_code,
                resp.text[:200],
            )
            return False
        except requests.RequestException as exc:
            self._warn("POST /events 요청 실패 (API 서버 확인 필요): %s", exc)
            return False

    def send_current_status(self, status: Dict[str, Any]) -> bool:
        """현재 감지 상태를 PUT /status/current로 전송한다.

        Returns:
            True if 2xx, False otherwise.
        """
        try:
            resp = self._session.put(
                f"{self._base_url}/status/current",
                json=status,
                timeout=2.0,
            )
            if resp.ok:
                return True
            self._warn(
                "PUT /status/current 실패: status=%d body=%s",
                resp.status_code,
                resp.text[:200],
            )
            return False
        except requests.RequestException as exc:
            self._warn("PUT /status/current 요청 실패 (API 서버 확인 필요): %s", exc)
            return False

    def close(self) -> None:
        self._session.close()
