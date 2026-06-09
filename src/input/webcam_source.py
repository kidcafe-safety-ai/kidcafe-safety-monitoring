"""웹캠 입력 소스."""

from __future__ import annotations

import logging
import time
from typing import Optional, Tuple

import cv2
import numpy as np

from src.input.base import InputSource

LOGGER = logging.getLogger(__name__)

_WEBCAM_FPS_FALLBACK = 30.0
_WARMUP_DELAY_SEC = 0.5   # 카메라 하드웨어 초기화 대기
_WARMUP_MAX_RETRIES = 10  # 첫 프레임 read 재시도 횟수


class WebcamSource(InputSource):
    """USB/내장 웹캠에서 실시간 프레임을 읽는 소스.

    CAP_PROP_FPS가 부정확하거나 0인 경우가 많으므로 30.0으로 고정 fallback한다.
    DWELL 타임아웃 계산은 FPS 기반이므로 부정확한 값보다 고정값이 일관성 있다.
    """

    def __init__(
        self,
        device: int = 0,
        fps_override: Optional[float] = None,
        width: Optional[int] = None,
        height: Optional[int] = None,
    ) -> None:
        """
        Args:
            device: 카메라 인덱스 (0 = 기본 내장 카메라).
            fps_override: None이면 CAP_PROP_FPS 읽은 뒤 0 이하면 30.0 사용.
            width/height: 카메라에 해상도를 요청한다. 미지원 시 카메라 기본값으로 fallback.
        """
        self._device = device
        self._fps_override = fps_override
        self._req_width = width
        self._req_height = height
        self._cap: Optional[cv2.VideoCapture] = None
        self._fps: float = fps_override if fps_override is not None else _WEBCAM_FPS_FALLBACK
        self._width: int = 0
        self._height: int = 0

    def open(self) -> None:
        self._cap = cv2.VideoCapture(self._device)
        if not self._cap.isOpened():
            raise RuntimeError(f"웹캠을 열 수 없습니다: device={self._device}")

        if self._req_width is not None:
            self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._req_width)
        if self._req_height is not None:
            self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._req_height)

        # 하드웨어 초기화 대기: macOS/Continuity Camera 등에서 첫 read가 실패하는 경우 처리
        time.sleep(_WARMUP_DELAY_SEC)
        for attempt in range(_WARMUP_MAX_RETRIES):
            ret, _ = self._cap.read()
            if ret:
                break
            LOGGER.debug("웹캠 warm-up 재시도 %d/%d", attempt + 1, _WARMUP_MAX_RETRIES)
        else:
            self._cap.release()
            raise RuntimeError(f"웹캠이 열렸지만 프레임을 읽을 수 없습니다: device={self._device}")

        self._width = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self._height = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        if self._fps_override is not None:
            self._fps = self._fps_override
        else:
            raw_fps = self._cap.get(cv2.CAP_PROP_FPS)
            self._fps = raw_fps if raw_fps > 0 else _WEBCAM_FPS_FALLBACK

        LOGGER.info(
            "웹캠 준비 완료: device=%d  %dx%d  fps=%.1f",
            self._device, self._width, self._height, self._fps,
        )

    def read(self) -> Tuple[bool, Optional[np.ndarray]]:
        if self._cap is None:
            return False, None
        ret, frame = self._cap.read()
        return ret, frame if ret else None

    def release(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None

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
        return f"webcam:{self._device}"
