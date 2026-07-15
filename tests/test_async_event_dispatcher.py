"""AsyncEventDispatcher 단위 테스트."""

from __future__ import annotations

import json
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from src.common.types import Event
from src.integrations.async_event_dispatcher import AsyncEventDispatcher
from src.integrations.live_frame_dispatcher import LiveFrameDispatcher


def _make_event(frame_number: int = 1, **overrides) -> Event:
    defaults = dict(
        event_type="ENTER",
        track_id=1,
        zone_id="zone_a",
        bbox=[0.0, 0.0, 10.0, 10.0],
        foot_point=[5.0, 10.0],
        frame_number=frame_number,
        video_source="test.mp4",
    )
    defaults.update(overrides)
    return Event.create(**defaults)


def _wait_until(predicate, timeout=2.0, interval=0.02):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


@pytest.fixture()
def dispatcher(tmp_path):
    failed_path = tmp_path / "api_failed_events.jsonl"
    d = AsyncEventDispatcher(
        base_url="http://localhost:8000",
        failed_events_path=str(failed_path),
    )
    yield d, failed_path
    d.close(timeout=2.0)


class TestEventQueueMaxsizeValidation:
    @pytest.mark.parametrize("invalid_maxsize", [0, -1])
    def test_rejects_non_positive_maxsize(self, invalid_maxsize):
        with pytest.raises(ValueError):
            AsyncEventDispatcher(
                base_url="http://localhost:8000",
                event_queue_maxsize=invalid_maxsize,
            )


class TestEnqueueEventReturnsImmediately:
    def test_enqueue_event_does_not_block_on_slow_send(self, dispatcher):
        d, _ = dispatcher
        send_started = threading.Event()
        release_send = threading.Event()

        def slow_send(event):
            send_started.set()
            release_send.wait(timeout=2.0)
            return True

        with patch.object(d._event_client, "send_event", side_effect=slow_send):
            start = time.monotonic()
            d.enqueue_event(_make_event())
            elapsed = time.monotonic() - start

            assert elapsed < 0.1
            assert send_started.wait(timeout=1.0)
        release_send.set()


class TestEventFifoOrder:
    def test_events_are_sent_in_fifo_order(self, dispatcher):
        d, _ = dispatcher
        sent_order = []

        with patch.object(
            d._event_client,
            "send_event",
            side_effect=lambda e: sent_order.append(e.frame_number) or True,
        ):
            for i in range(5):
                d.enqueue_event(_make_event(frame_number=i))
            assert _wait_until(lambda: len(sent_order) == 5)

        assert sent_order == [0, 1, 2, 3, 4]


class TestEventQueueOverflow:
    def test_queue_drops_oldest_when_full(self, dispatcher):
        d, failed_path = dispatcher
        send_started = threading.Event()
        release_send = threading.Event()

        def slow_send(event):
            send_started.set()
            release_send.wait(timeout=2.0)
            return True

        with patch.object(d._event_client, "send_event", side_effect=slow_send):
            d.enqueue_event(_make_event(frame_number=0))
            assert send_started.wait(timeout=1.0)  # worker가 event 0을 처리 중

            for i in range(1, 105):  # maxsize(100) 초과
                d.enqueue_event(_make_event(frame_number=i))

            with d._event_lock:
                remaining = [e.frame_number for e in d._event_queue]
                dropped = [e.frame_number for e in d._dropped_events]

            release_send.set()

        # event 0은 이미 처리 중이라 queue엔 없음. 1~104 중 최신 100개(5~104)만 남고
        # 1~4가 드롭돼야 한다.
        assert len(remaining) == 100
        assert remaining[0] == 5
        assert remaining[-1] == 104
        assert dropped == [1, 2, 3, 4]

    def test_dropped_event_is_recorded_as_queue_overflow(self, dispatcher):
        d, failed_path = dispatcher
        send_started = threading.Event()
        release_send = threading.Event()

        def slow_send(event):
            send_started.set()
            release_send.wait(timeout=2.0)
            return True

        with patch.object(d._event_client, "send_event", side_effect=slow_send):
            d.enqueue_event(_make_event(frame_number=0))
            assert send_started.wait(timeout=1.0)

            # queue maxsize=100. 1~100을 채우고 101을 넣으면 1이 하나 드롭된다.
            for i in range(1, 102):
                d.enqueue_event(_make_event(frame_number=i))

            release_send.set()

            # patch가 걸려 있는 동안(=worker가 mock을 계속 쓰는 동안) 결과를 확인한다.
            # with 블록을 벗어나 patch가 풀리면 worker가 실제 네트워크로 요청을
            # 보내려는 레이스가 생길 수 있다.
            assert _wait_until(
                lambda: failed_path.exists() and failed_path.stat().st_size > 0
            )
            # 나머지 queue가 전부 소진돼 patch가 더 이상 필요 없어질 때까지 대기
            assert _wait_until(lambda: len(d._event_queue) == 0, timeout=2.0)

        lines = [json.loads(line) for line in failed_path.read_text().splitlines()]
        overflow_records = [r for r in lines if r["reason"] == "queue_overflow"]
        assert len(overflow_records) == 1  # frame_number 1이 드롭됨 (maxsize 100)
        assert overflow_records[0]["attempts"] == 0
        assert overflow_records[0]["event"]["frame_number"] == 1


class TestEventRetry:
    def test_event_retries_once_on_failure(self, dispatcher):
        d, _ = dispatcher

        with patch.object(
            d._event_client, "send_event", return_value=False
        ) as mock_send:
            d.enqueue_event(_make_event())
            assert _wait_until(lambda: mock_send.call_count >= 2)
            time.sleep(0.1)

        assert mock_send.call_count == 2

    def test_event_succeeds_on_retry_without_extra_attempt(self, dispatcher):
        d, failed_path = dispatcher

        with patch.object(
            d._event_client, "send_event", side_effect=[False, True]
        ) as mock_send:
            d.enqueue_event(_make_event())
            assert _wait_until(lambda: mock_send.call_count == 2)
            time.sleep(0.1)

        assert mock_send.call_count == 2
        assert not failed_path.exists() or failed_path.stat().st_size == 0

    def test_final_failure_after_retry_is_recorded_with_two_attempts(self, dispatcher):
        d, failed_path = dispatcher

        with patch.object(d._event_client, "send_event", return_value=False):
            d.enqueue_event(_make_event())
            assert _wait_until(
                lambda: failed_path.exists() and failed_path.stat().st_size > 0
            )

        lines = [json.loads(line) for line in failed_path.read_text().splitlines()]
        assert len(lines) == 1
        assert lines[0]["reason"] == "request_failed"
        assert lines[0]["attempts"] == 2

    def test_first_attempt_failure_past_deadline_skips_retry_and_records_one_attempt(
        self, dispatcher
    ):
        """1차 시도가 실패한 시점에 이미 종료 deadline이 지났다면 retry를
        생략하고 attempts=1로 기록해야 한다 (ADR-017).

        deadline은 1차 전송 시도 도중(응답이 오기 전)에 지나도록 만들어,
        이미 queue에서 꺼내져 시도된 Event와 애초에 꺼내지 못한 Event를
        구분하는 실제 경로를 검증한다.
        """
        d, failed_path = dispatcher

        def failing_send(event):
            d._shutdown_deadline = time.monotonic() - 1.0
            return False

        with patch.object(d._event_client, "send_event", side_effect=failing_send) as mock_send:
            d.enqueue_event(_make_event())
            assert _wait_until(
                lambda: failed_path.exists() and failed_path.stat().st_size > 0
            )
            assert mock_send.call_count == 1

        lines = [json.loads(line) for line in failed_path.read_text().splitlines()]
        assert len(lines) == 1
        assert lines[0]["reason"] == "request_failed"
        assert lines[0]["attempts"] == 1


class TestCurrentStatusLatestOnly:
    def test_only_latest_status_is_sent(self, dispatcher):
        d, _ = dispatcher
        send_started = threading.Event()
        release_send = threading.Event()
        sent = []

        def slow_send(status):
            sent.append(status["n"])
            send_started.set()
            release_send.wait(timeout=2.0)
            return True

        with patch.object(d._status_client, "send_current_status", side_effect=slow_send):
            d.update_current_status({"n": 0})
            assert send_started.wait(timeout=1.0)  # worker가 status 0을 처리 중

            for i in range(1, 5):
                d.update_current_status({"n": i})

            release_send.set()
            assert _wait_until(lambda: len(sent) == 2)

        # 0(처리 중이던 것)과 마지막 값(4)만 전송되고 1~3은 건너뛴다.
        assert sent == [0, 4]

    def test_current_status_does_not_retry_on_failure(self, dispatcher):
        d, _ = dispatcher

        with patch.object(
            d._status_client, "send_current_status", return_value=False
        ) as mock_send:
            d.update_current_status({"n": 1})
            time.sleep(0.3)

        assert mock_send.call_count == 1


class TestIndependentHttpSessions:
    def test_event_and_status_use_different_clients(self, dispatcher):
        d, _ = dispatcher
        assert d._event_client is not d._status_client
        assert d._event_client._session is not d._status_client._session


class TestWorkerExceptionIsolation:
    def test_event_worker_survives_unexpected_exception(self, dispatcher):
        d, _ = dispatcher

        with patch.object(
            d._event_client, "send_event", side_effect=RuntimeError("boom")
        ):
            d.enqueue_event(_make_event(frame_number=1))
            time.sleep(0.3)
            assert d._event_thread.is_alive()

        with patch.object(d._event_client, "send_event", return_value=True) as mock_send:
            d.enqueue_event(_make_event(frame_number=2))
            assert _wait_until(lambda: mock_send.call_count == 1)

    def test_status_worker_survives_unexpected_exception(self, dispatcher):
        d, _ = dispatcher

        with patch.object(
            d._status_client, "send_current_status", side_effect=RuntimeError("boom")
        ):
            d.update_current_status({"n": 1})
            time.sleep(0.3)
            assert d._status_thread.is_alive()

    def test_unexpected_exception_is_retried_like_a_failed_attempt(self, dispatcher):
        """RuntimeError 등 예상치 못한 예외도 실패한 시도로 취급해 retry해야 한다."""
        d, _ = dispatcher

        with patch.object(
            d._event_client, "send_event", side_effect=RuntimeError("boom")
        ) as mock_send:
            d.enqueue_event(_make_event())
            assert _wait_until(lambda: mock_send.call_count >= 2)
            time.sleep(0.1)

        assert mock_send.call_count == 2

    def test_unexpected_exception_then_success_records_nothing(self, dispatcher):
        """1차 예외 후 2차(retry)가 성공하면 실패로 기록하지 않는다."""
        d, failed_path = dispatcher

        with patch.object(
            d._event_client,
            "send_event",
            side_effect=[RuntimeError("boom"), True],
        ) as mock_send:
            d.enqueue_event(_make_event())
            assert _wait_until(lambda: mock_send.call_count == 2)
            time.sleep(0.1)

        assert not failed_path.exists() or failed_path.stat().st_size == 0

    def test_unexpected_exception_on_both_attempts_is_recorded(self, dispatcher):
        """1차·2차 모두 예외면 request_failed/attempts=2로 기록해야 한다."""
        d, failed_path = dispatcher

        with patch.object(d._event_client, "send_event", side_effect=RuntimeError("boom")):
            d.enqueue_event(_make_event())
            assert _wait_until(
                lambda: failed_path.exists() and failed_path.stat().st_size > 0
            )

        lines = [json.loads(line) for line in failed_path.read_text().splitlines()]
        assert len(lines) == 1
        assert lines[0]["reason"] == "request_failed"
        assert lines[0]["attempts"] == 2


class TestApiOutageDoesNotPropagate:
    """EventApiClient를 mock하지 않고 실제 연결 실패를 겪게 해,

    파이프라인 호출자(main.py)에게 예외가 전파되지 않고 worker도 계속
    살아있는지 확인한다 (main loop가 API 장애 중에도 지속돼야 한다).
    """

    def test_enqueue_and_update_status_survive_unreachable_api(self, tmp_path):
        d = AsyncEventDispatcher(
            base_url="http://10.255.255.1:8000",  # 논라우팅 주소 → connect timeout으로 실패
            failed_events_path=str(tmp_path / "failed.jsonl"),
        )
        try:
            start = time.monotonic()
            d.enqueue_event(_make_event())
            d.update_current_status({"source": "webcam:0"})
            elapsed = time.monotonic() - start

            # 호출 자체는 네트워크 시도와 무관하게 즉시 반환해야 한다.
            assert elapsed < 0.1

            # worker가 connect timeout(0.5초) + retry까지 실제로 겪을 시간을 준다.
            time.sleep(3.0)

            assert d._event_thread.is_alive()
            assert d._status_thread.is_alive()
        finally:
            d.close(timeout=2.0)


class TestClose:
    def test_close_stops_threads_and_closes_clients(self, tmp_path):
        d = AsyncEventDispatcher(
            base_url="http://localhost:8000",
            failed_events_path=str(tmp_path / "failed.jsonl"),
        )
        event_client_close = MagicMock(wraps=d._event_client.close)
        status_client_close = MagicMock(wraps=d._status_client.close)
        d._event_client.close = event_client_close
        d._status_client.close = status_client_close

        d.close(timeout=2.0)

        assert not d._event_thread.is_alive()
        assert not d._status_thread.is_alive()
        event_client_close.assert_called_once()
        status_client_close.assert_called_once()

    def test_close_flushes_pending_event(self, tmp_path):
        d = AsyncEventDispatcher(
            base_url="http://localhost:8000",
            failed_events_path=str(tmp_path / "failed.jsonl"),
        )
        with patch.object(d._event_client, "send_event", return_value=True) as mock_send:
            d.enqueue_event(_make_event(frame_number=99))
            d.close(timeout=2.0)

        mock_send.assert_called()

    def test_close_respects_overall_deadline_and_does_not_race_on_client_close(self, tmp_path):
        """close()가 deadline 안에서 빨리 반환해야 하고, worker가 아직 전송

        중이면 close() 자신이 그 client를 강제로 닫으면 안 된다(race 방지).
        client는 worker가 자기 작업을 끝낸 뒤 스스로 닫아야 한다.
        """
        d = AsyncEventDispatcher(
            base_url="http://localhost:8000",
            failed_events_path=str(tmp_path / "failed.jsonl"),
        )
        send_started = threading.Event()
        release_send = threading.Event()

        def hang_send(event):
            send_started.set()
            release_send.wait(timeout=2.0)
            return True

        with patch.object(d._event_client, "send_event", side_effect=hang_send), patch.object(
            d._event_client, "close"
        ) as mock_close:
            d.enqueue_event(_make_event())
            assert send_started.wait(timeout=1.0)

            start = time.monotonic()
            d.close(timeout=0.3)
            elapsed = time.monotonic() - start

            assert elapsed < 1.0  # timeout(0.3)에 여유를 더해도 크게 넘지 않아야 함
            # worker가 아직 hang_send 안에 있으므로 close()는 client를 안 닫아야 한다.
            mock_close.assert_not_called()
            assert d._event_thread.is_alive()

            release_send.set()
            # worker가 자기 작업을 마치면 스스로 client를 닫는다.
            assert _wait_until(lambda: mock_close.called, timeout=2.0)


class TestLiveFrameDelegation:
    def test_update_live_frame_delegates_to_live_frame_dispatcher(self):
        mock_live_frame_dispatcher = MagicMock(spec=LiveFrameDispatcher)
        d = AsyncEventDispatcher(
            base_url="http://localhost:8000",
            live_frame_dispatcher=mock_live_frame_dispatcher,
        )
        try:
            d.update_live_frame(
                "frame-data",
                source="webcam:0",
                frame_number=1,
                captured_at="2026-07-14T12:00:00Z",
            )
            mock_live_frame_dispatcher.update_frame.assert_called_once_with(
                "frame-data",
                source="webcam:0",
                frame_number=1,
                captured_at="2026-07-14T12:00:00Z",
            )
        finally:
            d.close(timeout=2.0)

    def test_update_live_frame_is_noop_without_live_frame_dispatcher(self, dispatcher):
        d, _ = dispatcher
        # live_frame_dispatcher가 없으면 예외 없이 조용히 무시한다.
        d.update_live_frame(
            "frame-data", source="webcam:0", frame_number=1, captured_at="t"
        )

    def test_close_closes_live_frame_dispatcher(self):
        mock_live_frame_dispatcher = MagicMock(spec=LiveFrameDispatcher)
        d = AsyncEventDispatcher(
            base_url="http://localhost:8000",
            live_frame_dispatcher=mock_live_frame_dispatcher,
        )
        d.close(timeout=2.0)
        mock_live_frame_dispatcher.close.assert_called_once()
