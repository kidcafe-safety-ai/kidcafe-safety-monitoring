"""입력 소스 추상 인터페이스."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional, Tuple

import numpy as np


class InputSource(ABC):
    """모든 입력 소스의 공통 인터페이스.

    FileVideoSource, WebcamSource, RTSPSource가 이 인터페이스를 구현한다.
    파이프라인은 InputSource만 바라보므로 입력 종류에 무관하게 동작한다.
    """

    @abstractmethod
    def open(self) -> None:
        """소스를 열고 스트림을 초기화한다."""

    @abstractmethod
    def read(self) -> Tuple[bool, Optional[np.ndarray]]:
        """다음 프레임을 읽는다.

        Returns:
            (success, frame) — success=False이면 스트림 종료.
        """

    @abstractmethod
    def release(self) -> None:
        """소스를 닫고 리소스를 해제한다."""

    @property
    @abstractmethod
    def fps(self) -> float:
        """입력 소스의 FPS."""

    @property
    @abstractmethod
    def width(self) -> int:
        """프레임 가로 픽셀."""

    @property
    @abstractmethod
    def height(self) -> int:
        """프레임 세로 픽셀."""

    @property
    @abstractmethod
    def source_id(self) -> str:
        """소스 식별자 (파일 경로, 카메라 인덱스, RTSP URL 등)."""

    @property
    def total_frames(self) -> Optional[int]:
        """전체 프레임 수. 웹캠/RTSP는 None."""
        return None

    def __enter__(self) -> "InputSource":
        self.open()
        return self

    def __exit__(self, *_) -> None:
        self.release()
