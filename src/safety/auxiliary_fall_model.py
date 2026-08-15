"""fine-tuned fall/nofall 2-class object detector(fall_detector_v1.pt) 래퍼.

기존 ByteTracker/PoseTracker와 달리 자체 추적을 하지 않는다 — 이 모델은 매
프레임 독립적으로 bbox+class+confidence만 낸다. Track ID는 항상 이미 있는
ByteTrack Track에서 온다(IoU 매칭은 이 모듈이 아니라 후속 IoU 매칭 단계의
책임). 이 클래스는 Event나 Track 상태를 직접 만들지 않는다 — 그건
FallDetector 상태머신의 책임이다.

지연 로딩: __init__은 모델을 로드하지 않는다. `enabled=False`면 `infer()`가
항상 빈 리스트를 반환하고 모델 파일에 접근조차 하지 않는다 — 보조 모델이
없는 함수 API 경로에서 무거운 모델 로딩 비용을 아예 지불하지 않기 위함이다.
CLI에서는 `--fall-detection-disabled`로 낙상 경로 전체를 끌 수 있다.
`enabled=True`면 첫 `infer()` 호출에서 파일 존재·클래스 계약을 검증하고 로드 후
warm-up한다.

클래스 계약: 모델의 `names`가 정확히 `{0: "nofall", 1: "fall"}`이어야
한다. 다르면(순서가 바뀌었거나 클래스 이름이 다르면) 조용히 진행하지 않고
즉시 오류를 낸다 — 잘못된 클래스 매핑으로 fall/nofall이 뒤바뀐 채 추론되는
것이 가장 위험한 실패 모드이기 때문이다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import List

import numpy as np

from src.tracking.bytetrack_wrapper import _auto_device

LOGGER = logging.getLogger(__name__)

# {class_id: label}. class_id가 이 목록에 없으면(모델이 이 두 클래스 외의
# 것을 낸다는 뜻) 조용히 nofall로 취급하지 않고 오류를 낸다 (아래
# _parse_detections 참고).
_CLASS_LABELS = {0: "nofall", 1: "fall"}
_EXPECTED_CLASS_NAMES = {0: "nofall", 1: "fall"}


@dataclass(frozen=True)
class FallDetection:
    """한 프레임에서 보조 모델이 낸 detection 하나. Track ID는 아직 없다."""

    bbox: List[float]  # [x1, y1, x2, y2] pixel 좌표
    label: str  # "fall" 또는 "nofall"
    confidence: float


class ModelContractError(ValueError):
    """모델 파일이 기대하는 클래스 계약과 다를 때 (사용자가 조치해야 하는 문제)."""


def _parse_detections(
    xyxy: np.ndarray, cls_ids: np.ndarray, confs: np.ndarray
) -> List[FallDetection]:
    """이미 텐서에서 numpy로 변환된 배열로부터 FallDetection 목록을 만든다.

    ultralytics 추론 호출과 분리된 순수 함수로 둬서, 실제 모델 없이도
    변환 로직(라벨 매핑 등)을 단위 테스트할 수 있게 한다.

    class_id가 0/1이 아니면(모델 클래스 계약이 이미 로드 시점에 검증됐는데도
    이런 값이 나온다면 그 자체로 심각한 이상이다) 조용히 nofall로 취급하지
    않고 ModelContractError를 낸다.
    """
    detections = []
    for (x1, y1, x2, y2), cls_id, conf in zip(xyxy, cls_ids, confs):
        label = _CLASS_LABELS.get(int(cls_id))
        if label is None:
            raise ModelContractError(
                f"알 수 없는 class_id={int(cls_id)}가 감지됐습니다 "
                f"(허용값: {sorted(_CLASS_LABELS)})"
            )
        detections.append(
            FallDetection(
                bbox=[float(x1), float(y1), float(x2), float(y2)],
                label=label,
                confidence=float(conf),
            )
        )
    return detections


class AuxiliaryFallModel:
    """fine-tuned fall/nofall detector의 지연 로딩 래퍼."""

    def __init__(
        self,
        model_path: str,
        conf: float = 0.5,
        device: str = "auto",
        enabled: bool = True,
    ):
        if not (0.0 <= conf <= 1.0):
            raise ValueError(f"conf는 0.0~1.0 사이여야 합니다: {conf}")
        self.model_path = model_path
        self.conf = conf
        self.enabled = enabled
        self._device = _auto_device() if device == "auto" else device
        self._model = None  # 지연 로딩: __init__에서는 로드하지 않는다.

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return

        path = Path(self.model_path)
        if not path.is_file():
            raise FileNotFoundError(f"fall 모델 파일을 찾을 수 없습니다: {path}")

        from ultralytics import YOLO

        model = YOLO(str(path))
        self._validate_class_contract(model.names)
        self._warmup(model)
        self._model = model
        LOGGER.info(
            "AuxiliaryFallModel 로드: model=%s device=%s", self.model_path, self._device
        )

    @staticmethod
    def _validate_class_contract(names: dict) -> None:
        actual = {int(k): v for k, v in dict(names).items()}
        if actual != _EXPECTED_CLASS_NAMES:
            raise ModelContractError(
                f"모델 클래스 계약이 다릅니다 (기대값: {_EXPECTED_CLASS_NAMES}, 실제: {actual})"
            )

    def _warmup(self, model) -> None:
        dummy = np.zeros((64, 64, 3), dtype=np.uint8)
        model.predict(dummy, conf=self.conf, device=self._device, verbose=False)

    def infer(self, frame: np.ndarray) -> List[FallDetection]:
        """한 프레임에서 fall/nofall detection 목록을 반환한다.

        `enabled=False`면 모델 파일에 접근하지 않고 항상 빈 리스트를 반환한다.
        """
        if not self.enabled:
            return []

        self._ensure_loaded()

        results = self._model.predict(
            frame, conf=self.conf, device=self._device, verbose=False
        )
        if not results:
            return []

        boxes = results[0].boxes
        if boxes is None or len(boxes) == 0:
            return []

        xyxy = boxes.xyxy.cpu().numpy()
        cls_ids = boxes.cls.cpu().numpy().astype(int)
        confs = boxes.conf.cpu().numpy()
        return _parse_detections(xyxy, cls_ids, confs)
