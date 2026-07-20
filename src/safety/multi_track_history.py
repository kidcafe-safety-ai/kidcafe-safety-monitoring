"""Track별 최근 시계열 이력 관리.

낙상 판정은 한 프레임의 스냅샷이 아니라 최근 몇 초간 bbox·foot_point가
어떻게 변했는지를 봐야 하므로, (video_source, track_id)별로 최근
history_window_sec 초간의 샘플을 저장한다.

시간은 frame 수가 아니라 frame_number / fps 초 단위로 다룬다. FPS가
달라도 동일한 물리적 시간 기준(예: "0.5초 이상 지속")을 유지하기 위함이며,
docs/decisions.md ADR-005의 timestamp 규칙과 같은 원칙이다.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict, List, Tuple

from src.common.types import TrackingResult

_DEFAULT_HISTORY_WINDOW_SEC = 2.0
_DEFAULT_TRACK_GRACE_SEC = 0.5

TrackKey = Tuple[str, int]  # (video_source, track_id)


@dataclass(frozen=True)
class TrackSample:
    """한 시점의 Track 상태 스냅샷 (immutable, main loop가 이후 Track을 재사용해도 영향 없음)."""

    frame_number: int
    time_sec: float
    bbox: Tuple[float, float, float, float]
    foot_point: Tuple[float, float]
    confidence: float


class MultiTrackHistory:
    """(video_source, track_id)별 최근 history_window_sec 초 이력을 관리한다."""

    def __init__(
        self,
        fps: float,
        history_window_sec: float = _DEFAULT_HISTORY_WINDOW_SEC,
        track_grace_sec: float = _DEFAULT_TRACK_GRACE_SEC,
    ) -> None:
        if fps <= 0:
            raise ValueError("fps는 0보다 커야 합니다.")
        self.fps = fps
        self.history_window_sec = history_window_sec
        self.track_grace_sec = track_grace_sec

        self._history: Dict[TrackKey, Deque[TrackSample]] = {}
        self._last_seen_sec: Dict[TrackKey, float] = {}

    def update(self, tracking_result: TrackingResult) -> None:
        """한 프레임의 TrackingResult를 반영한다.

        현재 프레임에 나타난 Track은 샘플을 추가하고, 나타나지 않은
        기존 Track은 grace period(track_grace_sec)가 지났을 때만 제거한다.
        """
        time_sec = tracking_result.frame_number / self.fps
        video_source = tracking_result.video_source
        seen_keys = set()

        for track in tracking_result.tracks:
            key = (video_source, track.track_id)
            seen_keys.add(key)
            sample = TrackSample(
                frame_number=tracking_result.frame_number,
                time_sec=time_sec,
                bbox=tuple(track.bbox),
                foot_point=tuple(track.foot_point),
                confidence=track.confidence,
            )
            history = self._history.setdefault(key, deque())
            history.append(sample)
            self._trim_window(history, time_sec)
            self._last_seen_sec[key] = time_sec

        self._evict_expired(video_source, seen_keys, time_sec)

    def _trim_window(self, history: Deque[TrackSample], now_sec: float) -> None:
        while history and (now_sec - history[0].time_sec) > self.history_window_sec:
            history.popleft()

    def _evict_expired(self, video_source: str, seen_keys: set, now_sec: float) -> None:
        expired = [
            key
            for key, last_seen in self._last_seen_sec.items()
            if key[0] == video_source
            and key not in seen_keys
            and (now_sec - last_seen) > self.track_grace_sec
        ]
        for key in expired:
            self._history.pop(key, None)
            self._last_seen_sec.pop(key, None)

    def get_history(self, video_source: str, track_id: int) -> List[TrackSample]:
        """오래된 순서(과거 → 최신)로 정렬된 샘플 목록을 반환한다."""
        return list(self._history.get((video_source, track_id), ()))

    def active_keys(self) -> List[TrackKey]:
        """현재 이력이 남아 있는 (video_source, track_id) 목록 (grace period 내 소실 Track 포함)."""
        return list(self._history.keys())

    def track_age_sec(self, video_source: str, track_id: int) -> float:
        """이력상 가장 오래된 샘플부터 최신 샘플까지의 경과 시간(초)."""
        history = self._history.get((video_source, track_id))
        if not history or len(history) < 2:
            return 0.0
        return history[-1].time_sec - history[0].time_sec
