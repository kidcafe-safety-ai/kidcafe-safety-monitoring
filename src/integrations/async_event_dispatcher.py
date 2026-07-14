"""Event / CurrentStatus / Live Frame 비차단 전송 dispatcher.

main.py의 프레임 루프는 enqueue_event() / update_current_status() /
update_live_frame()을 호출하고 즉시 다음 추론으로 돌아간다. 실제 HTTP 전송은
worker thread에서 수행하므로 API 장애나 네트워크 지연이 Vision AI 추론
루프의 FPS를 직접 깎지 않는다.

worker 구성 (ADR-017):
    Event: FIFO bounded queue 100, overflow 시 oldest-drop, 실패 시 retry 1회
        (최대 2회 시도), 최종 실패는 outputs/api_failed_events.jsonl에 기록.
    CurrentStatus: latest-only, retry 없음.
    Live Frame: 기존 LiveFrameDispatcher에 위임.

Event worker와 CurrentStatus worker는 각각 독립된 EventApiClient(=독립 HTTP
session)를 사용해 서로의 전송 지연이 격리되도록 한다.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import deque
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional

from src.common.types import Event
from src.integrations.event_api_client import EventApiClient
from src.integrations.live_frame_dispatcher import LiveFrameDispatcher

LOGGER = logging.getLogger(__name__)

_DEFAULT_EVENT_QUEUE_MAXSIZE = 100
_DEFAULT_FAILED_EVENTS_PATH = "outputs/api_failed_events.jsonl"
_WAIT_POLL_SEC = 0.5


class AsyncEventDispatcher:
    """Event / CurrentStatus / Live Frame 비차단 전송을 담당하는 dispatcher."""

    def __init__(
        self,
        base_url: str,
        live_frame_dispatcher: Optional[LiveFrameDispatcher] = None,
        event_queue_maxsize: int = _DEFAULT_EVENT_QUEUE_MAXSIZE,
        failed_events_path: str = _DEFAULT_FAILED_EVENTS_PATH,
    ) -> None:
        if event_queue_maxsize < 1:
            raise ValueError("event_queue_maxsize는 1 이상이어야 합니다.")

        # Event worker와 CurrentStatus worker는 서로 독립된 HTTP session을 쓴다.
        self._event_client = EventApiClient(base_url=base_url)
        self._status_client = EventApiClient(base_url=base_url)
        self._live_frame_dispatcher = live_frame_dispatcher
        self._failed_events_path = failed_events_path

        self._event_queue: Deque[Event] = deque(maxlen=event_queue_maxsize)
        self._dropped_events: List[Event] = []
        self._event_lock = threading.Lock()
        self._event_signal = threading.Event()

        self._latest_status: Optional[Dict[str, Any]] = None
        self._status_lock = threading.Lock()
        self._status_signal = threading.Event()

        self._stop_event = threading.Event()
        self._shutdown_deadline: Optional[float] = None

        self._event_thread = threading.Thread(
            target=self._run_event_worker, name="event-worker", daemon=True
        )
        self._status_thread = threading.Thread(
            target=self._run_status_worker, name="status-worker", daemon=True
        )
        self._event_thread.start()
        self._status_thread.start()

    # ------------------------------------------------------------------
    # 공개 API (main.py 프레임 루프에서 호출, 즉시 반환)
    # ------------------------------------------------------------------

    def enqueue_event(self, event: Event) -> None:
        """Event를 FIFO queue에 등록한다. queue가 가득 차면 가장 오래된 항목을 버린다."""
        with self._event_lock:
            if len(self._event_queue) >= (self._event_queue.maxlen or 0):
                self._dropped_events.append(self._event_queue.popleft())
            self._event_queue.append(event)
        self._event_signal.set()

    def update_current_status(self, status: Dict[str, Any]) -> None:
        """최신 CurrentStatus로 교체한다 (latest-only)."""
        with self._status_lock:
            self._latest_status = status
        self._status_signal.set()

    def update_live_frame(
        self,
        frame: Any,
        source: str,
        frame_number: int,
        captured_at: str,
    ) -> None:
        """Live Frame을 기존 LiveFrameDispatcher에 위임한다."""
        if self._live_frame_dispatcher is not None:
            self._live_frame_dispatcher.update_frame(
                frame,
                source=source,
                frame_number=frame_number,
                captured_at=captured_at,
            )

    # ------------------------------------------------------------------
    # Event worker
    # ------------------------------------------------------------------

    def _run_event_worker(self) -> None:
        try:
            while not self._stop_event.is_set():
                triggered = self._event_signal.wait(timeout=_WAIT_POLL_SEC)
                if not triggered:
                    continue
                self._drain_event_queue()
            # close()가 설정한 공통 deadline까지만 마지막으로 flush를 시도한다.
            self._drain_event_queue()
        finally:
            # 이 client는 이 thread에서만 사용하므로, 다른 thread(close())가
            # 아직 전송 중인 session을 닫는 race 없이 여기서 안전하게 닫는다.
            self._event_client.close()

    def _drain_event_queue(self) -> None:
        # 드롭 기록은 매 반복마다 확인한다. 현재 이벤트를 보내는 동안
        # overflow가 발생하면, 다음 wake까지 기다리지 않고 같은 drain
        # 주기 안에서 바로 기록하기 위함이다.
        while True:
            for dropped in self._pop_dropped_events():
                self._record_failure(dropped, reason="queue_overflow", attempts=0)
            if self._deadline_passed():
                return
            event = self._pop_event()
            if event is None:
                return
            self._send_event_with_retry(event)

    def _pop_event(self) -> Optional[Event]:
        with self._event_lock:
            if not self._event_queue:
                self._event_signal.clear()
                return None
            return self._event_queue.popleft()

    def _pop_dropped_events(self) -> List[Event]:
        with self._event_lock:
            dropped, self._dropped_events = self._dropped_events, []
        return dropped

    def _send_event_with_retry(self, event: Event) -> None:
        """최초 시도 + retry 1회로 최대 2회 시도한다. 둘 다 실패하면 JSONL에 기록한다.

        EventApiClient는 requests.RequestException을 흡수하고 False를 반환하지만,
        그 외 예상치 못한 예외(버그 등)가 나더라도 실패한 시도로 취급해 동일한
        retry·기록 경로를 타도록 한다. 그래야 예외 종류에 따라 Event가 기록도
        retry도 없이 조용히 유실되는 상황을 방지할 수 있다.
        """
        if self._try_send_event(event):
            return
        if self._deadline_passed():
            self._record_failure(event, reason="request_failed", attempts=1)
            return
        if self._try_send_event(event):
            return
        self._record_failure(event, reason="request_failed", attempts=2)

    def _try_send_event(self, event: Event) -> bool:
        try:
            return self._event_client.send_event(event)
        except Exception:  # noqa: BLE001
            # worker thread를 종료시키지 않기 위한 방어선. 실패한 시도로 취급해
            # 호출자(_send_event_with_retry)가 retry·기록을 정상 진행하게 한다.
            LOGGER.exception("Event 전송 중 예상치 못한 오류 발생 (event_id=%s)", event.event_id)
            return False

    # ------------------------------------------------------------------
    # CurrentStatus worker
    # ------------------------------------------------------------------

    def _run_status_worker(self) -> None:
        try:
            while not self._stop_event.is_set():
                triggered = self._status_signal.wait(timeout=_WAIT_POLL_SEC)
                if not triggered:
                    continue
                self._send_latest_status()
            self._send_latest_status()
        finally:
            self._status_client.close()

    def _send_latest_status(self) -> None:
        with self._status_lock:
            status = self._latest_status
            self._latest_status = None
            self._status_signal.clear()

        if status is None:
            return

        try:
            self._status_client.send_current_status(status)
        except Exception:  # noqa: BLE001
            LOGGER.exception("CurrentStatus worker에서 예상치 못한 오류 발생")

    # ------------------------------------------------------------------
    # 실패 기록
    # ------------------------------------------------------------------

    def _record_failure(self, event: Event, reason: str, attempts: int) -> None:
        record = {
            "failed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "reason": reason,
            "attempts": attempts,
            "event": asdict(event),
        }
        try:
            path = Path(self._failed_events_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as file:
                file.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError:
            # 실패 기록 자체가 실패해도 worker와 추론 루프는 계속 진행한다.
            LOGGER.exception("실패 JSONL 기록 실패: %s", self._failed_events_path)

    # ------------------------------------------------------------------
    # 종료
    # ------------------------------------------------------------------

    def _deadline_passed(self) -> bool:
        return self._shutdown_deadline is not None and time.monotonic() >= self._shutdown_deadline

    def close(self, timeout: float = 3.0) -> None:
        """모든 worker를 종료한다. Event/Status/Live Frame 종료 대기의 합이
        timeout(기본 3초)을 넘지 않도록 공통 deadline을 사용한다.

        HTTP client는 각 worker가 자신의 실행 함수 finally에서 직접 닫는다.
        여기서 client.close()를 호출하지 않는 이유는, join()이 timeout으로
        끝난 뒤에도 worker가 여전히 전송 중일 수 있어 다른 thread에서 그
        session을 닫으면 race condition이 생기기 때문이다. deadline을 넘겨
        worker가 아직 살아 있으면 경고만 남기고 반환하며, 해당 worker는
        나중에 자기 작업이 끝나는 대로 자신의 client를 닫는다.
        """
        deadline = time.monotonic() + timeout
        self._shutdown_deadline = deadline
        self._stop_event.set()
        self._event_signal.set()
        self._status_signal.set()

        self._event_thread.join(timeout=max(0.0, deadline - time.monotonic()))
        if self._event_thread.is_alive():
            LOGGER.warning("Event worker가 종료 deadline(%.1f초) 내에 끝나지 않았습니다.", timeout)

        self._status_thread.join(timeout=max(0.0, deadline - time.monotonic()))
        if self._status_thread.is_alive():
            LOGGER.warning(
                "CurrentStatus worker가 종료 deadline(%.1f초) 내에 끝나지 않았습니다.", timeout
            )

        if self._live_frame_dispatcher is not None:
            self._live_frame_dispatcher.close(timeout=max(0.0, deadline - time.monotonic()))
