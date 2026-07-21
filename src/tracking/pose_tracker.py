"""YOLO pose 모델 + Ultralytics 내장 ByteTrack 통합.

ByteTracker(yolo26n.pt, detection 전용)와 구조는 같지만, yolo26n-pose.pt를
써서 bbox·track_id와 함께 COCO 17 keypoint를 같은 model.track() 호출에서
얻는다. 독립된 두 번째 추적기를 따로 돌려 ID를 다시 매칭하는 대신(다인원
상황에서 두 추적기의 ID가 서로 어긋날 수 있음), pose 모델 자체가 검출+추적을
겸하므로 bbox와 keypoint가 항상 같은 track_id로 정확히 대응한다.

Phase 3 낙상 pose 보완(FALL_SUSPECT 방향별 미검출 보완)을 위해 도입했다.
Development와 Subject 7~8 진단 전체가 이 tracker로 동결됐으므로,
`--fall-detection-enabled` 사용 시 src/main.py도 ByteTracker 대신 이
tracker를 사용한다 — FallDetector의 pose confirm 경로가 실제 운영에서도
keypoints를 받도록 하기 위함이다. Zone/기존 이벤트 로직은 Track.keypoints를
쓰지 않으므로 영향이 없다. 자세한 튜닝 근거는 docs/fall_evaluation.md 참고.
"""

import logging

import numpy as np
from ultralytics import YOLO

from src.common.types import Track, TrackingResult
from src.tracking.bytetrack_wrapper import _auto_device

LOGGER = logging.getLogger(__name__)


class PoseTracker:
    """YOLO pose 모델 + ByteTrack(내장) 통합 추적기. bbox와 17 keypoint를 함께 반환한다."""

    PERSON_CLASS_ID = 0  # COCO의 person 클래스

    def __init__(
        self,
        model_path: str = "yolo26n-pose.pt",
        conf: float = 0.5,
        tracker_config: str = "bytetrack.yaml",
        fps: float = 30.0,
        device: str = "auto",
    ):
        self._device = _auto_device() if device == "auto" else device
        self.model = YOLO(model_path)
        self.conf = conf
        self.tracker_config = tracker_config
        self.fps = fps
        LOGGER.info("PoseTracker 초기화: model=%s  device=%s", model_path, self._device)
        self._warmup()

    def update(
        self,
        frame: np.ndarray,
        frame_number: int,
        video_source: str,
    ) -> TrackingResult:
        """한 프레임에서 사람 탐지 + ID 추적 + pose keypoint 추출.

        Args:
            frame: BGR 이미지 (H, W, 3)
            frame_number: 현재 프레임 번호
            video_source: 영상 파일 경로

        Returns:
            TrackingResult: track_id가 부여된 추적 결과. 각 Track.keypoints에
                COCO 17 keypoint [[x, y], ...]가 채워진다 (검출 실패 시 None).
        """
        results = self.model.track(
            frame,
            conf=self.conf,
            classes=[self.PERSON_CLASS_ID],
            tracker=self.tracker_config,
            persist=True,  # 프레임 간 ID 유지
            verbose=False,
            device=self._device,
        )

        if len(results) == 0:
            return self._empty_result(frame_number, video_source)

        result = results[0]
        boxes = result.boxes
        if boxes is None or boxes.id is None:
            # 첫 프레임 등 ID 미부여 상태
            return self._empty_result(frame_number, video_source)

        xyxy = boxes.xyxy.cpu().numpy()  # (N, 4)
        ids = boxes.id.cpu().numpy().astype(int)  # (N,)
        confs = boxes.conf.cpu().numpy()  # (N,)

        keypoints_xy = None
        keypoints_conf = None
        if result.keypoints is not None:
            keypoints_xy = result.keypoints.xy.cpu().numpy()  # (N, 17, 2)
            if result.keypoints.conf is not None:
                keypoints_conf = result.keypoints.conf.cpu().numpy()  # (N, 17)

        tracks = []
        for i, ((x1, y1, x2, y2), tid, conf) in enumerate(zip(xyxy, ids, confs)):
            if tid < 0:  # 이론상 없지만 방어적으로 skip
                continue

            foot_x = (x1 + x2) / 2.0
            foot_y = y2

            kpts = keypoints_xy[i].tolist() if keypoints_xy is not None else None
            kpts_conf = keypoints_conf[i].tolist() if keypoints_conf is not None else None

            track = Track(
                track_id=int(tid),
                bbox=[float(x1), float(y1), float(x2), float(y2)],
                foot_point=[float(foot_x), float(foot_y)],
                confidence=float(conf),
                keypoints=kpts,
                keypoints_conf=kpts_conf,
            )
            tracks.append(track)

        return TrackingResult(
            frame_number=frame_number,
            timestamp=self._video_timestamp(frame_number),
            video_source=video_source,
            tracks=tracks,
        )

    def reset(self) -> None:
        """이전 영상의 ByteTrack 상태를 초기화한다 (ByteTracker.reset()과 동일한 이유).

        predictor를 None으로 비우면 model.callbacks의 tracking postprocess
        callback이 매번 추가로 등록되어 영상을 거듭할수록 중복 실행되므로,
        predictor는 유지하고 내부 BYTETracker 상태만 초기화한다.
        """
        predictor = self.model.predictor
        if predictor is None:
            return

        for tracker in getattr(predictor, "trackers", []):
            tracker.reset()

        if hasattr(predictor, "vid_path"):
            predictor.vid_path = [None] * len(predictor.vid_path)

    def _warmup(self) -> None:
        """MPS/CUDA JIT 컴파일을 초기화 시점에 완료한다."""
        LOGGER.info("모델 warm-up 중...")
        dummy = np.zeros((640, 640, 3), dtype=np.uint8)
        self.model.predict(dummy, verbose=False, device=self._device)
        LOGGER.info("모델 warm-up 완료")

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
