"""YOLOv8 + Ultralytics built-in ByteTrack 통합.

Detection과 Tracking을 model.track()으로 한 번에 처리한다.
별도의 detector 모듈을 두지 않은 이유는 docs/decisions.md ADR-001 참조.
"""

import numpy as np
from ultralytics import YOLO

from src.common.types import Track, TrackingResult


class ByteTracker:
    """YOLO + ByteTrack(내장) 통합 추적기."""

    PERSON_CLASS_ID = 0  # COCO의 person 클래스

    def __init__(
        self,
        model_path: str = "yolov8n.pt",
        conf: float = 0.5,
        tracker_config: str = "bytetrack.yaml",
        fps: float = 30.0,
    ):
        self.model = YOLO(model_path)
        self.conf = conf
        self.tracker_config = tracker_config
        self.fps = fps

    def update(
        self,
        frame: np.ndarray,
        frame_number: int,
        video_source: str,
    ) -> TrackingResult:
        """
        한 프레임에서 사람 탐지 + ID 추적.

        Args:
            frame: BGR 이미지 (H, W, 3)
            frame_number: 현재 프레임 번호
            video_source: 영상 파일 경로

        Returns:
            TrackingResult: track_id가 부여된 추적 결과
                (아직 ID가 부여되지 않은 box는 결과에서 제외)
        """
        results = self.model.track(
            frame,
            conf=self.conf,
            classes=[self.PERSON_CLASS_ID],
            tracker=self.tracker_config,
            persist=True,  # 프레임 간 ID 유지
            verbose=False,
        )

        tracks = []
        if len(results) == 0:
            return self._empty_result(frame_number, video_source)

        boxes = results[0].boxes
        if boxes is None or boxes.id is None:
            # 첫 프레임 등 ID 미부여 상태
            return self._empty_result(frame_number, video_source)

        # 텐서 → numpy
        xyxy = boxes.xyxy.cpu().numpy()  # (N, 4)
        ids = boxes.id.cpu().numpy().astype(int)  # (N,)
        confs = boxes.conf.cpu().numpy()  # (N,)

        for (x1, y1, x2, y2), tid, conf in zip(xyxy, ids, confs):
            # tid가 0 미만이면 (이론상 없지만 방어적으로) skip
            if tid < 0:
                continue

            foot_x = (x1 + x2) / 2.0
            foot_y = y2

            track = Track(
                track_id=int(tid),
                bbox=[float(x1), float(y1), float(x2), float(y2)],
                foot_point=[float(foot_x), float(foot_y)],
                confidence=float(conf),
            )
            tracks.append(track)

        return TrackingResult(
            frame_number=frame_number,
            timestamp=self._video_timestamp(frame_number),
            video_source=video_source,
            tracks=tracks,
        )

    def _empty_result(self, frame_number: int, video_source: str) -> TrackingResult:
        return TrackingResult(
            frame_number=frame_number,
            timestamp=self._video_timestamp(frame_number),
            video_source=video_source,
            tracks=[],
        )

    def _video_timestamp(self, frame_number: int) -> str:
        total_seconds = frame_number / self.fps
        hours = int(total_seconds // 3600)
        minutes = int((total_seconds % 3600) // 60)
        seconds = total_seconds % 60
        return f"{hours:02d}:{minutes:02d}:{seconds:06.3f}"
