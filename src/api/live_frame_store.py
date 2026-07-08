"""In-memory latest-frame store for the Live View API."""

from __future__ import annotations

from dataclasses import dataclass
import threading
import time
from typing import Optional


DEFAULT_STALE_AFTER_SEC = 3.0


@dataclass(frozen=True)
class LiveFrame:
    jpeg_bytes: bytes
    source: str
    frame_number: int
    captured_at: str
    received_monotonic_at: float


class LiveFrameStore:
    """Thread-safe latest-only JPEG frame store.

    Live frames are intentionally process-local. They are not written to DB or
    disk, and they disappear when the FastAPI process restarts.
    """

    def __init__(self, stale_after_sec: float = DEFAULT_STALE_AFTER_SEC) -> None:
        self._stale_after_sec = stale_after_sec
        self._lock = threading.Lock()
        self._latest: Optional[LiveFrame] = None

    def put_frame(
        self,
        jpeg_bytes: bytes,
        source: str,
        frame_number: int,
        captured_at: str,
    ) -> None:
        frame = LiveFrame(
            jpeg_bytes=bytes(jpeg_bytes),
            source=source,
            frame_number=frame_number,
            captured_at=captured_at,
            received_monotonic_at=time.monotonic(),
        )
        with self._lock:
            self._latest = frame

    def get_frame(self) -> Optional[LiveFrame]:
        with self._lock:
            frame = self._latest

        if frame is None:
            return None

        if time.monotonic() - frame.received_monotonic_at >= self._stale_after_sec:
            return None

        return frame

    def clear(self) -> None:
        with self._lock:
            self._latest = None


live_frame_store = LiveFrameStore()
