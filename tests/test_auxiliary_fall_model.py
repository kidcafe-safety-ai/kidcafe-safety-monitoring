"""src/safety/auxiliary_fall_model.py 테스트.

변환 로직(_parse_detections)은 실제 모델 없이 단위 테스트한다. 로드·클래스
계약 검증·warm-up은 로컬에 있는 실제 모델 파일로 통합 테스트한다 — 기존
ByteTracker/PoseTracker 테스트와 같은 방식(tests/test_tracking.py 참고)이며,
fine-tuned fall_detector_v1.pt는 outputs/(gitignore)에 있어 팀원 전체가
항상 갖고 있지 않으므로 없으면 skip한다. 클래스 계약 위반 테스트는 이미
레포에 있는 사람 탐지 모델(yolo26n.pt, names가 fall/nofall이 아님)로
검증한다.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from src.safety.auxiliary_fall_model import (
    AuxiliaryFallModel,
    FallDetection,
    ModelContractError,
    _parse_detections,
)

_FINE_TUNED_MODEL_PATH = "outputs/fall_training/models/fall_detector_v1.pt"
_WRONG_CONTRACT_MODEL_PATH = "yolo26n.pt"

_has_fine_tuned_model = Path(_FINE_TUNED_MODEL_PATH).is_file()
_has_wrong_contract_model = Path(_WRONG_CONTRACT_MODEL_PATH).is_file()


class TestParseDetections:
    """실제 모델 없이 검증 가능한 순수 변환 로직."""

    def test_class_1_maps_to_fall(self):
        detections = _parse_detections(
            xyxy=np.array([[0.0, 0.0, 10.0, 10.0]]),
            cls_ids=np.array([1]),
            confs=np.array([0.9]),
        )

        assert detections == [
            FallDetection(bbox=[0.0, 0.0, 10.0, 10.0], label="fall", confidence=0.9)
        ]

    def test_class_0_maps_to_nofall(self):
        detections = _parse_detections(
            xyxy=np.array([[0.0, 0.0, 10.0, 10.0]]),
            cls_ids=np.array([0]),
            confs=np.array([0.7]),
        )

        assert detections[0].label == "nofall"

    def test_empty_arrays_return_empty_list(self):
        detections = _parse_detections(
            xyxy=np.zeros((0, 4)), cls_ids=np.zeros((0,), dtype=int), confs=np.zeros((0,))
        )

        assert detections == []

    def test_multiple_detections_preserve_order(self):
        detections = _parse_detections(
            xyxy=np.array([[0.0, 0.0, 1.0, 1.0], [2.0, 2.0, 3.0, 3.0]]),
            cls_ids=np.array([1, 0]),
            confs=np.array([0.5, 0.6]),
        )

        assert [d.label for d in detections] == ["fall", "nofall"]

    def test_unknown_class_id_raises_instead_of_defaulting_to_nofall(self):
        """0/1 외의 class_id를 조용히 nofall로 취급하면 안 된다."""
        with pytest.raises(ModelContractError, match="알 수 없는 class_id"):
            _parse_detections(
                xyxy=np.array([[0.0, 0.0, 10.0, 10.0]]),
                cls_ids=np.array([2]),
                confs=np.array([0.9]),
            )


class TestValidateClassContract:
    """실제 모델 파일 없이도 항상 실행되는 순수 계약 검증 테스트 (CI에서 skip 없음)."""

    def test_correct_contract_passes(self):
        AuxiliaryFallModel._validate_class_contract({0: "nofall", 1: "fall"})  # 예외 없어야 함

    def test_wrong_names_raise(self):
        with pytest.raises(ModelContractError, match="클래스 계약"):
            AuxiliaryFallModel._validate_class_contract({0: "person"})

    def test_swapped_order_raises(self):
        with pytest.raises(ModelContractError, match="클래스 계약"):
            AuxiliaryFallModel._validate_class_contract({0: "fall", 1: "nofall"})

    def test_extra_class_raises(self):
        with pytest.raises(ModelContractError, match="클래스 계약"):
            AuxiliaryFallModel._validate_class_contract({0: "nofall", 1: "fall", 2: "extra"})


class TestAuxiliaryFallModelConfValidation:
    def test_conf_below_zero_raises(self):
        with pytest.raises(ValueError, match="conf"):
            AuxiliaryFallModel(model_path="unused.pt", conf=-0.1)

    def test_conf_above_one_raises(self):
        with pytest.raises(ValueError, match="conf"):
            AuxiliaryFallModel(model_path="unused.pt", conf=1.1)

    def test_conf_boundary_values_are_valid(self):
        AuxiliaryFallModel(model_path="unused.pt", conf=0.0, enabled=False)
        AuxiliaryFallModel(model_path="unused.pt", conf=1.0, enabled=False)


class TestAuxiliaryFallModelDisabled:
    def test_disabled_model_never_touches_model_path(self):
        """enabled=False면 존재하지 않는 경로여도 오류 없이 빈 결과를 반환해야 한다."""
        model = AuxiliaryFallModel(model_path="/no/such/path.pt", enabled=False)

        result = model.infer(np.zeros((32, 32, 3), dtype=np.uint8))

        assert result == []
        assert model._model is None

    def test_init_does_not_load_model_even_when_enabled(self):
        """지연 로딩: __init__ 시점에는 파일 존재 여부와 무관하게 로드하지 않는다."""
        model = AuxiliaryFallModel(model_path="/no/such/path.pt", enabled=True)

        assert model._model is None  # infer()를 호출하지 않았으므로 아직 로드 안 됨


class TestAuxiliaryFallModelMissingFile:
    def test_missing_model_file_raises_clear_error(self):
        model = AuxiliaryFallModel(model_path="/no/such/path.pt", enabled=True)

        with pytest.raises(FileNotFoundError, match="찾을 수 없습니다"):
            model.infer(np.zeros((32, 32, 3), dtype=np.uint8))


@pytest.mark.skipif(not _has_wrong_contract_model, reason="yolo26n.pt가 로컬에 없음")
class TestAuxiliaryFallModelWrongContract:
    def test_rejects_model_with_wrong_class_names(self):
        """person detector(yolo26n.pt)는 names가 {0: 'person', ...}이라 계약 위반이어야 한다."""
        model = AuxiliaryFallModel(model_path=_WRONG_CONTRACT_MODEL_PATH, enabled=True)

        with pytest.raises(ModelContractError, match="클래스 계약"):
            model.infer(np.zeros((32, 32, 3), dtype=np.uint8))


@pytest.mark.skipif(not _has_fine_tuned_model, reason="fine-tuned 모델 파일이 로컬에 없음")
class TestAuxiliaryFallModelRealModel:
    def test_loads_and_validates_class_contract(self):
        model = AuxiliaryFallModel(model_path=_FINE_TUNED_MODEL_PATH, enabled=True)

        model.infer(np.zeros((64, 64, 3), dtype=np.uint8))  # 예외 없이 로드·추론돼야 함

        assert model._model is not None

    def test_infer_returns_fall_detection_list(self):
        model = AuxiliaryFallModel(model_path=_FINE_TUNED_MODEL_PATH, enabled=True)

        result = model.infer(np.zeros((64, 64, 3), dtype=np.uint8))

        assert isinstance(result, list)
        for detection in result:
            assert isinstance(detection, FallDetection)
            assert detection.label in ("fall", "nofall")

    def test_model_loaded_only_once_across_multiple_infer_calls(self):
        model = AuxiliaryFallModel(model_path=_FINE_TUNED_MODEL_PATH, enabled=True)
        frame = np.zeros((64, 64, 3), dtype=np.uint8)

        model.infer(frame)
        loaded_model = model._model
        model.infer(frame)

        assert model._model is loaded_model  # 재로딩되지 않음
