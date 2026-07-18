"""YOLO + Ultralytics built-in ByteTrack 통합.

Detection과 Tracking을 model.track()으로 한 번에 처리한다.
별도의 detector 모듈을 두지 않은 이유는 docs/decisions.md ADR-001 참조.
"""

import logging

import numpy as np
import torch
from ultralytics import YOLO

from src.common.types import Track, TrackingResult

LOGGER = logging.getLogger(__name__)


def _auto_device() -> str:
    """사용 가능한 최적 device를 반환한다.

    Apple Silicon MPS → CUDA → CPU 순으로 선택한다.
    """
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


class ByteTracker:
    """YOLO + ByteTrack(내장) 통합 추적기."""

    PERSON_CLASS_ID = 0  # COCO의 person 클래스

    def __init__(
        self,
        model_path: str = "yolo26n.pt",
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
        LOGGER.info("ByteTracker 초기화: model=%s  device=%s", model_path, self._device)
        self._warmup()

    def update(
        self,
        frame: np.ndarray,
        frame_number: int,
        video_source: str,
    ) -> TrackingResult:
        """한 프레임에서 사람 탐지 + ID 추적.

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
            device=self._device,
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

    def reset(self) -> None:
        """이전 영상의 ByteTrack 상태(track ID, motion history)를 초기화한다.

        update()는 매번 persist=True로 호출해 프레임 간 ID를 유지하는데, 이 상태는
        ultralytics가 self.model.predictor에 내부적으로 보관한다. 같은 ByteTracker
        인스턴스를 여러 영상에 재사용하면(모델 재로딩 비용을 아끼기 위해) 이전 영상의
        track ID/추적 이력이 다음 영상 첫 프레임까지 이어져 섞일 수 있다.

        predictor 자체를 None으로 비우면(과거 구현) 다음 update()에서 predictor가
        새로 생성되면서 tracking postprocess callback이 매번 추가로 등록된다
        (model.callbacks["on_predict_postprocess_end"]가 계속 누적됨) — 이러면
        영상을 거듭할수록 callback이 중복 실행되어 추적 결과가 오염된다. 따라서
        predictor는 그대로 두고, 그 안의 BYTETracker 상태만 초기화한다.
        """
        predictor = self.model.predictor
        if predictor is None:
            return

        for tracker in getattr(predictor, "trackers", []):
            tracker.reset()

        if hasattr(predictor, "vid_path"):
            predictor.vid_path = [None] * len(predictor.vid_path)

    def _warmup(self) -> None:
        """MPS/CUDA JIT 컴파일을 초기화 시점에 완료한다.

        첫 실제 프레임에서 수 초 지연이 발생하는 문제를 방지한다.
        """
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
