"""Live Frame latest-only worker.

main.py의 프레임 루프는 `update_frame()`으로 최신 frame만 넘기고 즉시
다음 추론으로 돌아간다. 실제 `PUT /live/frame` 전송(JPEG 인코딩 + HTTP 요청,
connect timeout 0.5초 + read timeout 1.0초)은 별도 daemon thread에서 수행하므로
API 장애나 네트워크 지연이 Vision AI 추론 루프의 FPS를 직접 깎지 않는다.

latest-only 정책: worker가 아직 이전 frame을 처리 중일 때 새 frame이
들어오면 이전 frame은 버리고 최신 frame으로 덮어쓴다 (큐잉하지 않음).

계약: docs/decisions.md ADR-017 (Event / CurrentStatus / Live Frame worker 분리).
Event FIFO queue와 CurrentStatus latest-only 전송은 AsyncEventDispatcher가
담당하며, 이 모듈은 그중 Live Frame worker만 담당한다
(AsyncEventDispatcher는 이 클래스를 생성자로 주입받아 위임하는 구조).
"""

from __future__ import annotations

import logging
import threading
from typing import Optional, Tuple

import numpy as np

from src.integrations.live_frame_client import LiveFrameClient

LOGGER = logging.getLogger(__name__)

_FrameItem = Tuple[np.ndarray, str, int, str]


class LiveFrameDispatcher:
    """Live Frame을 latest-only로 비차단 전송하는 worker."""

    def __init__(self, client: LiveFrameClient) -> None:
        self._client = client
        self._lock = threading.Lock()
        self._latest: Optional[_FrameItem] = None
        self._new_frame_event = threading.Event()
        self._stop_event = threading.Event()
        self._thread = threading.Thread(
            target=self._run, name="live-frame-worker", daemon=True
        )
        self._thread.start()

    def update_frame(
        self,
        frame: np.ndarray,
        source: str,
        frame_number: int,
        captured_at: str,
    ) -> None:
        """최신 frame을 등록한다 (main loop에서 호출, 즉시 반환).

        frame은 main loop가 이후 다른 용도로 재사용할 수 있으므로 복사해 저장한다.
        """
        with self._lock:
            self._latest = (frame.copy(), source, frame_number, captured_at)
        self._new_frame_event.set()

    def _run(self) -> None:
        try:
            while not self._stop_event.is_set():
                triggered = self._new_frame_event.wait(timeout=0.5)
                if not triggered:
                    continue
                self._send_pending()

            # close()가 stop_event를 설정하는 시점과 update_frame()이 마지막
            # frame을 등록하는 시점이 겹치면 while 조건 체크에서 바로 빠져나와
            # 마지막 frame이 유실될 수 있다. 종료 직전 한 번 더 flush해 방지한다.
            self._send_pending()
        finally:
            # 이 client는 이 thread에서만 사용하므로, close()가 join() timeout
            # 후에도 아직 전송 중인 session을 닫는 race 없이 여기서 닫는다.
            self._client.close()

    def _send_pending(self) -> None:
        with self._lock:
            item = self._latest
            self._latest = None
            self._new_frame_event.clear()

        if item is None:
            return

        frame, source, frame_number, captured_at = item
        try:
            self._client.send_frame(
                frame,
                source=source,
                frame_number=frame_number,
                captured_at=captured_at,
            )
        except Exception:  # noqa: BLE001
            # LiveFrameClient가 내부에서 이미 예외를 흡수하지만,
            # worker thread를 종료시키지 않기 위한 방어선.
            LOGGER.exception("Live Frame worker에서 예상치 못한 오류 발생")

    def close(self, timeout: float = 3.0) -> None:
        """worker thread 종료를 기다린다. HTTP session은 worker thread 자신이 닫는다.

        deadline을 넘겨 worker가 아직 살아 있으면 경고만 남기고 반환한다
        (다른 thread에서 강제로 session을 닫는 race를 피하기 위함).
        """
        self._stop_event.set()
        self._new_frame_event.set()
        self._thread.join(timeout=timeout)
        if self._thread.is_alive():
            LOGGER.warning("Live Frame worker가 종료 deadline(%.1f초) 내에 끝나지 않았습니다.", timeout)
