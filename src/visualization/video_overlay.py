"""결과 영상 mp4 저장.

원본 영상에 bbox + zone polygon + 이벤트 알림 배너를 오버레이하여
outputs/result.mp4로 저장한다.

C의 모니터링 페이지에서 사용된다.
"""

from collections import deque
from pathlib import Path
from typing import Deque, List, Tuple

import cv2
import numpy as np

from src.common.types import Event, Track, Zone


# 색상 (BGR, OpenCV 기준)
COLOR_BBOX_NORMAL = (0, 255, 0)         # 초록
COLOR_ZONE = (0, 0, 255)                # 빨강 (zone 경계)
COLOR_ENTER = (7, 193, 255)             # 노랑 (#FFC107 → BGR)
COLOR_DWELL = (54, 67, 244)             # 빨강 (#F44336 → BGR)
COLOR_EXIT = (158, 158, 158)            # 회색 (#9E9E9E → BGR)
COLOR_BANNER_BG = (40, 40, 40)
COLOR_BANNER_TEXT = (255, 255, 255)


def get_event_color(event_type: str) -> Tuple[int, int, int]:
    """이벤트 종류별 색상 매핑."""
    return {
        "ENTER": COLOR_ENTER,
        "DWELL": COLOR_DWELL,
        "EXIT": COLOR_EXIT,
    }.get(event_type, COLOR_BBOX_NORMAL)


class VideoOverlayWriter:
    """원본 프레임에 시각화 오버레이를 입혀 mp4로 저장."""

    BANNER_HISTORY = 5  # 배너에 표시할 최근 이벤트 개수

    def __init__(
        self,
        output_path: str,
        frame_width: int,
        frame_height: int,
        fps: float,
    ):
        self.output_path = Path(output_path)
        self.output_path.parent.mkdir(parents=True, exist_ok=True)

        # mp4v 코덱 사용 (macOS/Linux 호환)
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        self.writer = cv2.VideoWriter(
            str(self.output_path),
            fourcc,
            fps,
            (frame_width, frame_height),
        )
        if not self.writer.isOpened():
            raise RuntimeError(f"Cannot open VideoWriter for {output_path}")

        self.fw = frame_width
        self.fh = frame_height
        self.recent_events: Deque[Event] = deque(maxlen=self.BANNER_HISTORY)

    def write_frame(
        self,
        frame: np.ndarray,
        tracks: List[Track],
        zones: List[Zone],
        events: List[Event],
    ):
        """한 프레임에 오버레이 그리고 저장."""
        overlay = frame.copy()

        # 1. Zone polygon 그리기
        self._draw_zones(overlay, zones)

        # 2. Track bbox + ID
        self._draw_tracks(overlay, tracks, events)

        # 3. 이벤트 알림 배너
        for ev in events:
            self.recent_events.appendleft(ev)
        self._draw_banner(overlay)

        self.writer.write(overlay)

    def _draw_zones(self, frame: np.ndarray, zones: List[Zone]):
        for z in zones:
            if z.type != "polygon":
                continue
            pts = np.array(
                [[int(x * self.fw), int(y * self.fh)] for x, y in z.points],
                dtype=np.int32,
            )
            cv2.polylines(frame, [pts], isClosed=True, color=COLOR_ZONE, thickness=2)
            # 이름 표시
            top_left = pts.min(axis=0)
            cv2.putText(
                frame,
                z.name,
                (top_left[0], max(top_left[1] - 5, 15)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                COLOR_ZONE,
                1,
            )

    def _draw_tracks(
        self,
        frame: np.ndarray,
        tracks: List[Track],
        events: List[Event],
    ):
        # 이번 프레임에 이벤트 발생한 track_id → 이벤트 종류
        event_by_track = {ev.track_id: ev.event_type for ev in events}

        for t in tracks:
            x1, y1, x2, y2 = map(int, t.bbox)
            # 이벤트 발생 track은 이벤트 색상, 아니면 초록
            color = (
                get_event_color(event_by_track[t.track_id])
                if t.track_id in event_by_track
                else COLOR_BBOX_NORMAL
            )
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            cv2.putText(
                frame,
                f"ID {t.track_id}",
                (x1, max(y1 - 10, 15)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                color,
                2,
            )
            # foot_point 표시 (작은 원)
            fx, fy = map(int, t.foot_point)
            cv2.circle(frame, (fx, fy), 4, color, -1)

    def _draw_banner(self, frame: np.ndarray):
        """상단에 최근 이벤트 알림 배너."""
        if not self.recent_events:
            return

        banner_h = 30 * min(len(self.recent_events), self.BANNER_HISTORY) + 10
        cv2.rectangle(frame, (0, 0), (self.fw, banner_h), COLOR_BANNER_BG, -1)

        for i, ev in enumerate(self.recent_events):
            text = f"[{ev.timestamp[:8]}] {ev.event_type} | ID {ev.track_id} | {ev.zone_id}"
            color = get_event_color(ev.event_type)
            y = 25 + i * 30
            cv2.putText(
                frame,
                text,
                (10, y),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                color,
                1,
            )

    def close(self):
        if self.writer:
            self.writer.release()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()