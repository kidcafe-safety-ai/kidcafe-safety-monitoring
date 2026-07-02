"""RTSP 입력 소스.

Phase 2.5에서는 연결 시도 및 기본 구현만 제공한다.
reconnect 안정화는 장비 확보 후 Phase 3에서 검증한다.
"""

from __future__ import annotations

import logging
from typing import Optional, Tuple

import cv2
import numpy as np

from src.input.base import InputSource

LOGGER = logging.getLogger(__name__)

_RTSP_FPS_FALLBACK = 25.0


class RTSPSource(InputSource):
    """RTSP/IP 카메라에서 실시간 프레임을 읽는 소스.

    CAP_FFMPEG 백엔드를 우선 시도한다.
    연결 실패 시 RuntimeError를 발생시키며,
    프레임 읽기 실패 시 False를 반환한다 (재연결은 호출자 책임).
    """

    def __init__(self, url: str, alias: Optional[str] = None) -> None:
        self._url = url
        self._alias = alias
        self._safe_url = self._sanitize_url(url)
        self._cap: Optional[cv2.VideoCapture] = None
        self._fps: float = _RTSP_FPS_FALLBACK
        self._width: int = 0
        self._height: int = 0

    @staticmethod
    def _sanitize_url(url: str) -> str:
        """계정 정보가 포함된 URL에서 비밀번호를 마스킹한다 (로깅용)."""
        if "://" in url and "@" in url:
            scheme, rest = url.split("://", 1)
            credentials, host = rest.split("@", 1)
            user = credentials.split(":")[0]
            return f"{scheme}://{user}:***@{host}"
        return url

    def open(self) -> None:
        LOGGER.info("RTSP 연결 시도: %s", self._safe_url)
        self._cap = cv2.VideoCapture(self._url, cv2.CAP_FFMPEG)
        if not self._cap.isOpened():
            raise RuntimeError(f"RTSP 스트림을 열 수 없습니다: {self._safe_url}")

        self._width = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self._height = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        raw_fps = self._cap.get(cv2.CAP_PROP_FPS)
        self._fps = raw_fps if raw_fps > 0 else _RTSP_FPS_FALLBACK

        LOGGER.info(
            "RTSP 연결 성공: %dx%d @ %.1ffps",
            self._width, self._height, self._fps,
        )

    def read(self) -> Tuple[bool, Optional[np.ndarray]]:
        if self._cap is None:
            return False, None
        ret, frame = self._cap.read()
        if not ret:
            LOGGER.warning("RTSP 프레임 읽기 실패 (스트림 종료 또는 네트워크 끊김): %s", self._safe_url)
        return ret, frame if ret else None

    def release(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None
            LOGGER.info("RTSP 소스 해제: %s", self._safe_url)

    @property
    def fps(self) -> float:
        return self._fps

    @property
    def width(self) -> int:
        return self._width

    @property
    def height(self) -> int:
        return self._height

    @property
    def source_id(self) -> str:
        return self._alias if self._alias else self._url
