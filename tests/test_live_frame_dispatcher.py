"""LiveFrameDispatcher 단위 테스트."""

from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock

import numpy as np
import pytest

from src.integrations.live_frame_dispatcher import LiveFrameDispatcher


def _make_frame(fill: int = 0) -> np.ndarray:
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    frame[:] = fill
    return frame


@pytest.fixture()
def mock_client():
    client = MagicMock()
    client.send_frame.return_value = True
    return client


class TestLiveFrameDispatcher:
    def test_update_frame_returns_immediately(self, mock_client):
        """worker가 느려도 update_frame 호출 자체는 즉시 반환해야 한다 (비차단)."""
        send_started = threading.Event()
        release_send = threading.Event()

        def slow_send_frame(*args, **kwargs):
            send_started.set()
            release_send.wait(timeout=2.0)
            return True

        mock_client.send_frame.side_effect = slow_send_frame
        dispatcher = LiveFrameDispatcher(client=mock_client)

        try:
            start = time.monotonic()
            dispatcher.update_frame(
                _make_frame(), source="webcam:0", frame_number=1, captured_at="t1"
            )
            elapsed = time.monotonic() - start

            assert elapsed < 0.1
            assert send_started.wait(timeout=1.0)
        finally:
            release_send.set()
            dispatcher.close()

    def test_worker_sends_registered_frame(self, mock_client):
        dispatcher = LiveFrameDispatcher(client=mock_client)
        try:
            dispatcher.update_frame(
                _make_frame(),
                source="webcam:0",
                frame_number=42,
                captured_at="2026-07-08T12:00:00Z",
            )
            for _ in range(50):
                if mock_client.send_frame.called:
                    break
                time.sleep(0.02)
        finally:
            dispatcher.close()

        mock_client.send_frame.assert_called_once()
        _, kwargs = mock_client.send_frame.call_args
        assert kwargs["source"] == "webcam:0"
        assert kwargs["frame_number"] == 42
        assert kwargs["captured_at"] == "2026-07-08T12:00:00Z"

    def test_latest_only_drops_intermediate_frames(self, mock_client):
        """worker가 처리 중일 때 여러 번 update하면 마지막 frame만 전송돼야 한다."""
        send_started = threading.Event()
        release_send = threading.Event()
        sent_frame_numbers = []

        def slow_send_frame(frame, source, frame_number, captured_at):
            sent_frame_numbers.append(frame_number)
            send_started.set()
            release_send.wait(timeout=2.0)
            return True

        mock_client.send_frame.side_effect = slow_send_frame
        dispatcher = LiveFrameDispatcher(client=mock_client)

        try:
            dispatcher.update_frame(
                _make_frame(), source="webcam:0", frame_number=1, captured_at="t1"
            )
            assert send_started.wait(timeout=1.0)  # worker가 frame 1을 처리 중

            # worker가 frame 1을 처리하는 동안 여러 frame이 들어옴
            for i in range(2, 6):
                dispatcher.update_frame(
                    _make_frame(), source="webcam:0", frame_number=i, captured_at=f"t{i}"
                )

            release_send.set()  # frame 1 전송 완료 → 다음 frame 처리 허용

            for _ in range(50):
                if len(sent_frame_numbers) >= 2:
                    break
                time.sleep(0.02)
        finally:
            release_send.set()
            dispatcher.close()

        # frame 1 전송 후, 큐잉된 2~5는 버려지고 최신(5)만 전송돼야 한다.
        assert sent_frame_numbers[0] == 1
        assert sent_frame_numbers[-1] == 5
        assert len(sent_frame_numbers) == 2

    def test_update_frame_copies_frame(self, mock_client):
        """update_frame 이후 원본 frame을 mutate해도 전송되는 frame은 영향받지 않아야 한다."""
        dispatcher = LiveFrameDispatcher(client=mock_client)
        original = _make_frame(fill=10)

        try:
            dispatcher.update_frame(
                original, source="webcam:0", frame_number=1, captured_at="t1"
            )
            original[:] = 200  # main loop가 다음 프레임에서 재사용/변경했다고 가정

            for _ in range(50):
                if mock_client.send_frame.called:
                    break
                time.sleep(0.02)
        finally:
            dispatcher.close()

        sent_frame = mock_client.send_frame.call_args[0][0]
        assert (sent_frame == 10).all()

    def test_close_flushes_last_registered_frame(self, mock_client):
        """update_frame() 직후 바로 close()해도 마지막 frame은 전송돼야 한다.

        worker가 아직 while-loop 조건 체크로 돌아가지 못한 좁은 시점에
        stop_event가 설정되면 마지막 frame이 유실될 수 있는 race를 방지한다.
        """
        dispatcher = LiveFrameDispatcher(client=mock_client)

        dispatcher.update_frame(
            _make_frame(), source="webcam:0", frame_number=99, captured_at="last"
        )
        dispatcher.close()

        mock_client.send_frame.assert_called_once()
        _, kwargs = mock_client.send_frame.call_args
        assert kwargs["frame_number"] == 99

    def test_close_stops_worker_and_closes_client(self, mock_client):
        dispatcher = LiveFrameDispatcher(client=mock_client)
        dispatcher.close()

        assert not dispatcher._thread.is_alive()
        mock_client.close.assert_called_once()

    def test_close_does_not_close_client_while_worker_still_sending(self, mock_client):
        """join()이 timeout으로 끝나도 close()가 직접 client를 닫으면 안 된다.

        worker가 아직 send_frame() 안에 있는 상태에서 다른 thread가 그
        session을 닫는 race를 방지하기 위함이다. client는 worker 자신이
        작업을 마친 뒤 스스로 닫아야 한다.
        """
        send_started = threading.Event()
        release_send = threading.Event()

        def hang_send(*args, **kwargs):
            send_started.set()
            release_send.wait(timeout=2.0)
            return True

        mock_client.send_frame.side_effect = hang_send
        dispatcher = LiveFrameDispatcher(client=mock_client)

        dispatcher.update_frame(
            _make_frame(), source="webcam:0", frame_number=1, captured_at="t1"
        )
        assert send_started.wait(timeout=1.0)

        dispatcher.close(timeout=0.2)  # worker가 아직 hang_send 안 → join timeout

        mock_client.close.assert_not_called()
        assert dispatcher._thread.is_alive()

        release_send.set()
        # worker가 자기 작업을 마치면 스스로 client를 닫는다.
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and not mock_client.close.called:
            time.sleep(0.02)
        mock_client.close.assert_called_once()

    def test_worker_survives_send_frame_exception(self, mock_client):
        mock_client.send_frame.side_effect = RuntimeError("boom")
        dispatcher = LiveFrameDispatcher(client=mock_client)

        try:
            dispatcher.update_frame(
                _make_frame(), source="webcam:0", frame_number=1, captured_at="t1"
            )
            for _ in range(50):
                if mock_client.send_frame.called:
                    break
                time.sleep(0.02)

            assert dispatcher._thread.is_alive()

            # 예외 이후에도 다음 frame을 계속 처리할 수 있어야 한다.
            mock_client.send_frame.side_effect = None
            mock_client.send_frame.return_value = True
            dispatcher.update_frame(
                _make_frame(), source="webcam:0", frame_number=2, captured_at="t2"
            )
            for _ in range(50):
                if mock_client.send_frame.call_count >= 2:
                    break
                time.sleep(0.02)

            assert mock_client.send_frame.call_count == 2
        finally:
            dispatcher.close()
