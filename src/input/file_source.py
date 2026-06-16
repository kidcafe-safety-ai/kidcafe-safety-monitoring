"""파일 영상 입력 소스."""

from __future__ import annotations

from typing import Optional, Tuple

import cv2
import numpy as np

from src.input.base import InputSource


class FileVideoSource(InputSource):
    """로컬 mp4 등 파일 영상을 프레임 단위로 읽는 소스."""

    def __init__(self, path: str) -> None:
        self._path = path
        self._cap: Optional[cv2.VideoCapture] = None
        self._fps: float = 30.0
        self._width: int = 0
        self._height: int = 0
        self._total_frames: Optional[int] = None

    def open(self) -> None:
        self._cap = cv2.VideoCapture(self._path)
        if not self._cap.isOpened():
            raise RuntimeError(f"영상 파일을 열 수 없습니다: {self._path}")

        raw_fps = self._cap.get(cv2.CAP_PROP_FPS)
        self._fps = raw_fps if raw_fps > 0 else 30.0
        self._width = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self._height = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        total = int(self._cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self._total_frames = total if total > 0 else None

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
        return self._path

    @property
    def total_frames(self) -> Optional[int]:
        return self._total_frames
