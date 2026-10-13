"""파일 영상 입력 소스."""

from __future__ import annotations

from typing import Optional, Sequence, Tuple

import cv2
import numpy as np

from src.input.base import InputSource


class FileVideoSource(InputSource):
    """로컬 mp4 등 파일 영상을 프레임 단위로 읽는 소스."""

    def __init__(self, path: str, repeat_count: int = 1) -> None:
        if repeat_count < 1:
            raise ValueError("repeat_count는 1 이상이어야 합니다.")
        self._path = path
        self._repeat_count = repeat_count
        self._cycle_index = 0
        self._cap: Optional[cv2.VideoCapture] = None
        self._fps: float = 30.0
        self._width: int = 0
        self._height: int = 0
        self._total_frames: Optional[int] = None

    def open(self) -> None:
        self.release()
        self._cycle_index = 0
        cap = cv2.VideoCapture(self._path)
        if not cap.isOpened():
            cap.release()
            raise RuntimeError(f"영상 파일을 열 수 없습니다: {self._path}")
        self._cap = cap

        raw_fps = cap.get(cv2.CAP_PROP_FPS)
        self._fps = raw_fps if raw_fps > 0 else 30.0
        self._width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self._height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self._total_frames = total if total > 0 else None

    def read(self) -> Tuple[bool, Optional[np.ndarray]]:
        if self._cap is None:
            return False, None
        ret, frame = self._cap.read()
        if not ret and self._cycle_index + 1 < self._repeat_count:
            if not self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0):
                raise RuntimeError(
                    f"영상 파일을 처음으로 되감을 수 없습니다: {self._path}"
                )
            self._cycle_index += 1
            ret, frame = self._cap.read()
            if not ret:
                raise RuntimeError(
                    f"되감은 영상의 첫 프레임을 읽을 수 없습니다: {self._path}"
                )
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
        if self._total_frames is None:
            return None
        return self._total_frames * self._repeat_count

    @property
    def cycle_index(self) -> int:
        """현재 파일 반복 회차의 0-based index."""
        return self._cycle_index


class FilePlaylistSource(InputSource):
    """여러 원본 영상 파일을 하나의 입력처럼 순서대로 읽는 소스.

    출력 영상 writer가 실행 중 해상도/FPS를 바꾸지 못하므로 첫 파일과 형식이
    다른 파일은 전환 시점에 명확한 오류로 중단한다. 모델은 상위 파이프라인에서
    한 번만 생성되며, ``cycle_index`` 변경을 기준으로 상태만 초기화한다.
    """

    def __init__(self, paths: Sequence[str], repeat_count: int = 1) -> None:
        if not paths:
            raise ValueError("paths에는 영상 파일이 하나 이상 필요합니다.")
        if repeat_count < 1:
            raise ValueError("repeat_count는 1 이상이어야 합니다.")
        self._paths = list(paths)
        self._repeat_count = repeat_count
        self._playlist_index = 0
        self._repeat_index = 0
        self._cycle_index = 0
        self._cap: Optional[cv2.VideoCapture] = None
        self._fps: float = 30.0
        self._width: int = 0
        self._height: int = 0

    def open(self) -> None:
        self.release()
        self._playlist_index = 0
        self._repeat_index = 0
        self._cycle_index = 0
        self._open_current(validate_format=False)

    def _open_current(self, *, validate_format: bool) -> None:
        path = self._paths[self._playlist_index]
        cap = cv2.VideoCapture(path)
        if not cap.isOpened():
            cap.release()
            raise RuntimeError(f"영상 파일을 열 수 없습니다: {path}")

        raw_fps = cap.get(cv2.CAP_PROP_FPS)
        fps = raw_fps if raw_fps > 0 else 30.0
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        if validate_format and (
            width != self._width
            or height != self._height
            or abs(fps - self._fps) > 0.01
        ):
            cap.release()
            raise ValueError(
                f"플레이리스트 영상 형식이 첫 파일과 다릅니다: {path} "
                f"({width}x{height}, {fps:.3f} FPS; expected "
                f"{self._width}x{self._height}, {self._fps:.3f} FPS)"
            )

        self._cap = cap
        if not validate_format:
            self._fps = fps
            self._width = width
            self._height = height

    def _advance(self) -> bool:
        self.release()
        next_index = self._playlist_index + 1
        if next_index >= len(self._paths):
            if self._repeat_index + 1 >= self._repeat_count:
                return False
            self._repeat_index += 1
            next_index = 0

        self._playlist_index = next_index
        self._open_current(validate_format=True)
        self._cycle_index += 1
        return True

    def read(self) -> Tuple[bool, Optional[np.ndarray]]:
        while self._cap is not None:
            ret, frame = self._cap.read()
            if ret:
                return True, frame
            if not self._advance():
                break
        return False, None

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
        return self._paths[self._playlist_index]

    @property
    def total_frames(self) -> Optional[int]:
        return None

    @property
    def cycle_index(self) -> int:
        """파일 전환과 playlist 반복을 모두 포함한 0-based 입력 index."""
        return self._cycle_index
