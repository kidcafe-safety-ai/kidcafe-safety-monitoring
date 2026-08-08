"""scripts/evaluate_fall.py의 순수 로직(점수 계산·annotation 검증·holdout 가드) 테스트.

실제 cv2/YOLO 파이프라인을 타는 _evaluate_video()는 scripts/ 컨벤션(예:
run_benchmark.py)과 마찬가지로 자동 테스트 대상이 아니다. 여기서는 cv2/YOLO
없이도 검증 가능한 순수 함수만 다룬다.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.common.types import Track, TrackingResult
from src.safety.fall_detector import FallDetectorConfig

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import evaluate_fall as ef  # noqa: E402


def test_live_protocol_metadata_uses_resolved_devices_and_file_hashes(
    tmp_path, monkeypatch
):
    tracker_model = tmp_path / "pose.pt"
    fall_model = tmp_path / "fall.pt"
    config = tmp_path / "fall.json"
    tracker_model.write_bytes(b"pose")
    fall_model.write_bytes(b"fall")
    config.write_text("{}", encoding="utf-8")
    args = SimpleNamespace(
        tracker="pose",
        conf=0.5,
        fall_model_path=str(fall_model),
        config=str(config),
        device="auto",
        fall_model_device="auto",
    )
    tracker = SimpleNamespace(_device="mps", tracker_config="bytetrack.yaml")
    auxiliary_model = SimpleNamespace(_device="mps")
    monkeypatch.setattr(
        ef.evaluation_protocol,
        "_git_state",
        lambda: ("1" * 40, False),
    )

    payload = ef._build_live_protocol_metadata(
        args,
        ef.evaluation_protocol.CAUCAFALL_ANNOTATION_VERSION,
        tracker,
        str(tracker_model),
        auxiliary_model,
    )

    assert payload["model_sha256"] == ef.evaluation_protocol.sha256_file(fall_model)
    assert payload["tracker_config"]["model_sha256"] == (
        ef.evaluation_protocol.sha256_file(tracker_model)
    )
    assert payload["device"] == {
        "tracker": "mps",
        "auxiliary_model": "mps",
        "evaluation": "live",
    }


def _row(**overrides) -> ef._AnnotationRow:
    defaults = dict(
        video_id="v1",
        label="fall",
        video_path="v1.avi",
        fall_start_frame=10,
        impact_frame=12,
        lying_start_frame=14,
        review_status="reviewed",
    )
    defaults.update(overrides)
    return ef._AnnotationRow(**defaults)


class TestScoreFallVideo:
    def test_no_events_is_not_detected(self):
        detected, latency, early, qualifying = ef.score_fall_video([], 10, 12, fps=10.0)
        assert detected is False
        assert latency is None
        assert early == 0
        assert qualifying == 0

    def test_event_before_fall_start_is_not_a_true_positive(self):
        """낙상 시작 전 오탐은 detected=True로 인정되면 안 되고, early_false_alarms로 잡혀야 한다."""
        detected, latency, early, qualifying = ef.score_fall_video(
            [2], fall_start_frame=10, impact_frame=12, fps=10.0
        )
        assert detected is False
        assert latency is None
        assert early == 1
        assert qualifying == 0

    def test_event_after_fall_start_is_detected(self):
        detected, latency, early, qualifying = ef.score_fall_video(
            [15], fall_start_frame=10, impact_frame=12, fps=10.0
        )
        assert detected is True
        assert early == 0
        assert qualifying == 1
        # (15 - 12) / 10.0 = 0.3초
        assert latency == pytest.approx(0.3)

    def test_latency_uses_fall_start_frame_when_impact_missing(self):
        detected, latency, early, qualifying = ef.score_fall_video(
            [15], fall_start_frame=10, impact_frame=None, fps=10.0
        )
        assert detected is True
        # (15 - 10) / 10.0 = 0.5초
        assert latency == pytest.approx(0.5)

    def test_negative_latency_is_not_clamped_to_zero(self):
        """impact_frame보다 먼저(더 빠르게) 감지한 경우 음수 지연을 그대로 반환해야 한다."""
        detected, latency, early, qualifying = ef.score_fall_video(
            [11], fall_start_frame=10, impact_frame=14, fps=10.0
        )
        assert detected is True
        assert latency == pytest.approx((11 - 14) / 10.0)
        assert latency < 0

    def test_mixed_early_and_qualifying_events(self):
        detected, latency, early, qualifying = ef.score_fall_video(
            [2, 5, 15, 20], fall_start_frame=10, impact_frame=12, fps=10.0
        )
        assert detected is True
        assert early == 2  # frame 2, 5
        assert qualifying == 2  # frame 15, 20
        assert latency == pytest.approx((15 - 12) / 10.0)  # 첫 유효 Event(15) 기준

    def test_single_qualifying_event_is_not_multi_event(self):
        """이른 오탐 1개 + 정상 확정 1개는 '중복 확정'이 아니라 qualifying_event_count=1이어야 한다."""
        detected, latency, early, qualifying = ef.score_fall_video(
            [2, 15], fall_start_frame=10, impact_frame=12, fps=10.0
        )
        assert detected is True
        assert early == 1
        assert qualifying == 1

    def test_event_within_tolerance_before_fall_start_is_a_true_positive(self):
        """S2_fall_sitting처럼 fall_start_frame보다 살짝 이른 Event는 tolerance 내면 true positive."""
        detected, latency, early, qualifying = ef.score_fall_video(
            [8], fall_start_frame=10, impact_frame=12, fps=20.0, early_tolerance_sec=0.2
        )
        # tolerance_frames = round(0.2 * 20) = 4 -> effective_start_frame = 6
        assert detected is True
        assert early == 0
        assert qualifying == 1
        assert latency == pytest.approx((8 - 12) / 20.0)

    def test_event_before_tolerance_window_is_still_an_early_false_alarm(self):
        detected, latency, early, qualifying = ef.score_fall_video(
            [4], fall_start_frame=10, impact_frame=12, fps=20.0, early_tolerance_sec=0.2
        )
        # effective_start_frame = 6, frame 4 < 6 -> 여전히 이른 오탐
        assert detected is False
        assert early == 1
        assert qualifying == 0

    def test_zero_tolerance_matches_default_behavior(self):
        detected, latency, early, qualifying = ef.score_fall_video(
            [8], fall_start_frame=10, impact_frame=12, fps=20.0, early_tolerance_sec=0.0
        )
        assert detected is False
        assert early == 1
        assert qualifying == 0


class TestScoreFallVideoTimely:
    """V2 주 지표는 [onset-tolerance, onset+timely_window_sec] 구간만 TP로 센다."""

    def test_no_events_is_not_timely_detected(self):
        result = ef.score_fall_video_timely([], fall_start_frame=10, impact_frame=12, fps=10.0)
        assert result.timely_detected is False
        assert result.onset_latency_sec is None
        assert result.late_detection is False
        assert result.duplicate_event is False

    def test_event_within_window_is_timely_detected(self):
        # window = [10, 10 + 2*10] = [10, 30]
        result = ef.score_fall_video_timely(
            [15], fall_start_frame=10, impact_frame=12, fps=10.0, timely_window_sec=2.0
        )
        assert result.timely_detected is True
        assert result.onset_latency_sec == pytest.approx(0.5)  # (15-10)/10
        assert result.lead_to_impact_sec == pytest.approx((12 - 15) / 10.0)
        assert result.late_detection is False
        assert result.duplicate_event is False

    def test_event_after_window_is_late_detection_not_timely(self):
        """기존 score_fall_video()라면 detected=True였을 늦은 Event가, 여기서는

        timely_detected=False + late_detection=True로 별도 기록돼야 한다.
        """
        result = ef.score_fall_video_timely(
            [35], fall_start_frame=10, impact_frame=12, fps=10.0, timely_window_sec=2.0
        )
        assert result.timely_detected is False
        assert result.late_detection is True
        assert result.onset_latency_sec is None

    def test_event_before_tolerance_is_early_false_alarm_not_timely(self):
        result = ef.score_fall_video_timely(
            [2], fall_start_frame=10, impact_frame=12, fps=10.0, early_tolerance_sec=0.0
        )
        assert result.timely_detected is False
        assert result.early_false_alarms == 1
        assert result.late_detection is False  # 이른 오탐은 late가 아니다

    def test_two_events_within_window_is_duplicate(self):
        result = ef.score_fall_video_timely(
            [12, 18], fall_start_frame=10, impact_frame=12, fps=10.0, timely_window_sec=2.0
        )
        assert result.timely_detected is True
        assert result.duplicate_event is True
        assert result.timely_event_count == 2
        assert result.onset_latency_sec == pytest.approx((12 - 10) / 10.0)  # 첫 Event 기준

    def test_timely_event_plus_later_reconfirm_is_still_duplicate(self):
        """구간 안 1개 + 구간 밖 늦은 재확정 1개도 "낙상 1회당 Event 1회" 위반이므로

        duplicate_event=True여야 한다.
        late_detection은 timely_detected가 이미 True라 False로 유지된다.
        """
        result = ef.score_fall_video_timely(
            [12, 40], fall_start_frame=10, impact_frame=12, fps=10.0, timely_window_sec=2.0
        )
        assert result.timely_detected is True
        assert result.duplicate_event is True
        assert result.late_detection is False  # 이미 timely_detected라 late가 아니다

    def test_only_late_event_is_late_detection_not_duplicate(self):
        """구간 밖 늦은 Event 1개뿐이면 duplicate가 아니라 late_detection만 True다."""
        result = ef.score_fall_video_timely(
            [35], fall_start_frame=10, impact_frame=12, fps=10.0, timely_window_sec=2.0
        )
        assert result.timely_detected is False
        assert result.late_detection is True
        assert result.duplicate_event is False

    def test_two_late_events_are_both_late_detection_and_duplicate(self):
        """timely 구간 안에는 아무것도 없고 구간 밖에 늦은 Event가 2개면,

        late_detection=True(감지는 결국 늦게라도 함)이면서 동시에
        duplicate_event=True(낙상 1회당 Event 1회 위반)여야 한다.
        """
        result = ef.score_fall_video_timely(
            [35, 45], fall_start_frame=10, impact_frame=12, fps=10.0, timely_window_sec=2.0
        )
        assert result.timely_detected is False
        assert result.late_detection is True
        assert result.duplicate_event is True

    def test_lead_to_impact_none_when_impact_frame_missing(self):
        result = ef.score_fall_video_timely(
            [15], fall_start_frame=10, impact_frame=None, fps=10.0
        )
        assert result.timely_detected is True
        assert result.lead_to_impact_sec is None

    def test_window_bounds_are_exposed(self):
        result = ef.score_fall_video_timely(
            [15], fall_start_frame=10, impact_frame=12, fps=10.0,
            early_tolerance_sec=0.2, timely_window_sec=2.0,
        )
        # tolerance_frames = round(0.2*10) = 2, window_frames = round(2.0*10) = 20
        assert result.window_start_frame == 8
        assert result.window_end_frame == 30

    def test_rejects_non_positive_timely_window_sec(self):
        with pytest.raises(ValueError, match="timely_window_sec"):
            ef.score_fall_video_timely(
                [15], fall_start_frame=10, impact_frame=12, fps=10.0, timely_window_sec=0.0
            )

    def test_rejects_negative_early_tolerance_sec(self):
        with pytest.raises(ValueError, match="early_tolerance_sec"):
            ef.score_fall_video_timely(
                [15], fall_start_frame=10, impact_frame=12, fps=10.0, early_tolerance_sec=-0.1
            )

    def test_rejects_non_positive_fps(self):
        with pytest.raises(ValueError, match="fps"):
            ef.score_fall_video_timely([15], fall_start_frame=10, impact_frame=12, fps=0.0)


class TestSummarizeWindowDiagnostics:
    def _track(self, track_id, with_pose=False, keypoints_conf=None):
        from src.common.types import Track

        if with_pose and keypoints_conf is None:
            keypoints_conf = [0.9] * 17
        return Track(
            track_id=track_id,
            bbox=[0.0, 0.0, 10.0, 10.0],
            foot_point=[5.0, 10.0],
            confidence=0.9,
            keypoints=[[5.0, 1.0]] * 17 if with_pose else None,
            keypoints_conf=keypoints_conf,
        )

    def test_frames_outside_window_are_ignored(self):
        tracks_by_frame = [(0, [self._track(1)]), (100, [])]
        result = ef.summarize_window_diagnostics(
            tracks_by_frame, window_start_frame=5, window_end_frame=10
        )
        assert result["track_coverage"] is None
        assert result["no_track_frame_count"] is None

    def test_full_coverage_no_track_loss(self):
        tracks_by_frame = [(f, [self._track(1)]) for f in range(5, 11)]
        result = ef.summarize_window_diagnostics(
            tracks_by_frame, window_start_frame=5, window_end_frame=10
        )
        assert result["track_coverage"] == pytest.approx(1.0)
        assert result["no_track_frame_count"] == 0
        assert result["id_switch_count"] == 0

    def test_missing_tracks_reduce_coverage(self):
        tracks_by_frame = [(f, [self._track(1)] if f != 7 else []) for f in range(5, 11)]
        result = ef.summarize_window_diagnostics(
            tracks_by_frame, window_start_frame=5, window_end_frame=10
        )
        # 6프레임 중 1프레임(frame 7) no-track -> coverage = 5/6
        assert result["track_coverage"] == pytest.approx(5 / 6)
        assert result["no_track_frame_count"] == 1

    def test_id_switch_counts_distinct_track_ids_minus_one(self):
        tracks_by_frame = [
            (5, [self._track(1)]),
            (6, [self._track(1)]),
            (7, [self._track(2)]),  # ID switch
            (8, [self._track(2)]),
        ]
        result = ef.summarize_window_diagnostics(
            tracks_by_frame, window_start_frame=5, window_end_frame=8
        )
        assert result["id_switch_count"] == 1

    def test_pose_valid_ratio_counts_frames_with_any_keypoints(self):
        tracks_by_frame = [
            (5, [self._track(1, with_pose=True)]),
            (6, [self._track(1, with_pose=False)]),
        ]
        result = ef.summarize_window_diagnostics(
            tracks_by_frame, window_start_frame=5, window_end_frame=6
        )
        assert result["pose_valid_frame_ratio"] == pytest.approx(0.5)

    def test_low_confidence_hip_keypoints_are_not_pose_valid(self):
        """keypoints 배열 자체는 있어도 엉덩이 confidence가 낮으면 실제

        FallDetector의 pose confirm 경로는 이 프레임을 못 쓴다(pose_features.py
        PoseFeatureExtractor 참고). 배열 존재 여부만으로는 이걸 못 잡는다.
        """
        low_hip_conf = [0.9] * 17
        low_hip_conf[11] = 0.1  # LEFT_HIP
        low_hip_conf[12] = 0.1  # RIGHT_HIP
        tracks_by_frame = [(5, [self._track(1, with_pose=True, keypoints_conf=low_hip_conf)])]

        result = ef.summarize_window_diagnostics(
            tracks_by_frame, window_start_frame=5, window_end_frame=5, pose_min_keypoint_conf=0.3
        )

        assert result["pose_valid_frame_ratio"] == pytest.approx(0.0)

    def test_pose_min_keypoint_conf_threshold_is_configurable(self):
        """pose_min_keypoint_conf를 낮추면(예: 0.05) 같은 keypoint도 유효로 잡혀야 한다."""
        low_hip_conf = [0.9] * 17
        low_hip_conf[11] = 0.1
        low_hip_conf[12] = 0.1
        tracks_by_frame = [(5, [self._track(1, with_pose=True, keypoints_conf=low_hip_conf)])]

        result = ef.summarize_window_diagnostics(
            tracks_by_frame, window_start_frame=5, window_end_frame=5, pose_min_keypoint_conf=0.05
        )

        assert result["pose_valid_frame_ratio"] == pytest.approx(1.0)


class TestSummarizeModelWindowDiagnostics:
    def _evidence(self, label, track_id=1):
        from src.safety.fall_model_matching import FallModelEvidence

        return {
            track_id: FallModelEvidence(track_id=track_id, label=label, confidence=0.9, iou=0.9)
        }

    def test_frames_outside_window_are_ignored(self):
        model_evidence_by_frame = [(0, self._evidence("fall")), (100, self._evidence("fall"))]
        result = ef.summarize_model_window_diagnostics(
            model_evidence_by_frame, window_start_frame=5, window_end_frame=10, fps=10.0
        )
        assert result["model_observed_frame_count"] is None
        assert result["model_fall_observed_ratio"] is None

    def test_model_never_used_returns_all_none(self):
        """구간 안 모든 프레임이 model_evidence=None(보조 모델을 아예 안 씀)이면

        관측/fall 카운트를 0으로 채우지 않고 전부 None이어야 한다 — "모델
        비활성"과 "모델은 켜졌는데 전부 unknown(매칭 실패)"을 구분해야
        한다. 0/0은 후자와 구분되지 않는다.
        """
        model_evidence_by_frame = [(f, None) for f in range(5, 11)]
        result = ef.summarize_model_window_diagnostics(
            model_evidence_by_frame, window_start_frame=5, window_end_frame=10, fps=10.0
        )
        assert result["model_observed_frame_count"] is None
        assert result["model_fall_frame_count"] is None
        assert result["model_fall_observed_ratio"] is None
        assert result["max_consecutive_model_fall_frames"] is None
        assert result["max_consecutive_model_fall_sec"] is None

    def test_model_active_but_all_unknown_returns_zero_not_none(self):
        """모델은 켜져 있지만(model_evidence 딕셔너리가 매 프레임 존재) 전부

        매칭 실패(unknown)면, "모델을 아예 안 씀"과 구분되게 관측/fall은
        0으로, ratio는 분모가 0이라 None으로 남아야 한다.
        """
        model_evidence_by_frame = [(f, self._evidence("unknown")) for f in range(5, 11)]
        result = ef.summarize_model_window_diagnostics(
            model_evidence_by_frame, window_start_frame=5, window_end_frame=10, fps=10.0
        )
        assert result["model_observed_frame_count"] == 0
        assert result["model_fall_frame_count"] == 0
        assert result["model_fall_observed_ratio"] is None
        assert result["max_consecutive_model_fall_frames"] == 0

    def test_all_fall_frames(self):
        model_evidence_by_frame = [(f, self._evidence("fall")) for f in range(5, 11)]
        result = ef.summarize_model_window_diagnostics(
            model_evidence_by_frame, window_start_frame=5, window_end_frame=10, fps=10.0
        )
        assert result["model_observed_frame_count"] == 6
        assert result["model_fall_frame_count"] == 6
        assert result["model_fall_observed_ratio"] == pytest.approx(1.0)
        assert result["max_consecutive_model_fall_frames"] == 6
        assert result["max_consecutive_model_fall_sec"] == pytest.approx(0.6)

    def test_nofall_frames_count_as_observed_not_fall(self):
        model_evidence_by_frame = [(f, self._evidence("nofall")) for f in range(5, 11)]
        result = ef.summarize_model_window_diagnostics(
            model_evidence_by_frame, window_start_frame=5, window_end_frame=10, fps=10.0
        )
        assert result["model_observed_frame_count"] == 6
        assert result["model_fall_frame_count"] == 0
        assert result["model_fall_observed_ratio"] == pytest.approx(0.0)

    def test_unknown_label_frames_are_not_observed(self):
        model_evidence_by_frame = [(f, self._evidence("unknown")) for f in range(5, 11)]
        result = ef.summarize_model_window_diagnostics(
            model_evidence_by_frame, window_start_frame=5, window_end_frame=10, fps=10.0
        )
        assert result["model_observed_frame_count"] == 0
        assert result["model_fall_observed_ratio"] is None

    def test_max_consecutive_fall_run_breaks_on_gap(self):
        """fall,fall,nofall,fall,fall,fall -> 최장 연속은 3(마지막 구간)이어야 한다."""
        labels = ["fall", "fall", "nofall", "fall", "fall", "fall"]
        model_evidence_by_frame = [
            (5 + i, self._evidence(label)) for i, label in enumerate(labels)
        ]
        result = ef.summarize_model_window_diagnostics(
            model_evidence_by_frame, window_start_frame=5, window_end_frame=10, fps=10.0
        )
        assert result["max_consecutive_model_fall_frames"] == 3
        assert result["max_consecutive_model_fall_sec"] == pytest.approx(0.3)
        assert result["model_fall_frame_count"] == 5
        assert result["model_fall_observed_ratio"] == pytest.approx(5 / 6)

    def test_multiple_tracks_any_fall_counts_frame_as_fall(self):
        """한 프레임에 여러 Track이 있고 그중 하나라도 fall이면 그 프레임은 fall이다."""
        model_evidence_by_frame = [
            (5, {1: self._evidence("nofall")[1], 2: self._evidence("fall", track_id=2)[2]}),
        ]
        result = ef.summarize_model_window_diagnostics(
            model_evidence_by_frame, window_start_frame=5, window_end_frame=5, fps=10.0
        )
        assert result["model_fall_frame_count"] == 1


class TestValidateAnnotations:
    def test_valid_rows_pass(self):
        ef.validate_annotations(
            [_row(), _row(video_id="v2", label="no_fall", fall_start_frame=None)]
        )

    def test_rejects_unknown_label(self):
        with pytest.raises(ValueError, match="label"):
            ef.validate_annotations([_row(label="Fall")])

    def test_rejects_negative_frame_values(self):
        with pytest.raises(ValueError, match="fall_start_frame"):
            ef.validate_annotations([_row(fall_start_frame=-1)])

    def test_fall_row_requires_fall_start_frame(self):
        with pytest.raises(ValueError, match="fall_start_frame"):
            ef.validate_annotations([_row(label="fall", fall_start_frame=None)])

    def test_rejects_duplicate_video_id(self):
        with pytest.raises(ValueError, match="중복"):
            ef.validate_annotations([_row(video_id="dup"), _row(video_id="dup", label="no_fall")])

    def test_reports_multiple_errors_at_once(self):
        """행마다 하나씩만 실패시키지 않고, 발견된 문제를 모두 모아 보고해야 한다."""
        bad_rows = [_row(label="typo"), _row(video_id="v2", fall_start_frame=-5)]
        with pytest.raises(ValueError) as exc_info:
            ef.validate_annotations(bad_rows)
        message = str(exc_info.value)
        assert "label" in message
        assert "fall_start_frame" in message

    def test_rejects_out_of_order_frames(self):
        """fall_start_frame <= impact_frame <= lying_start_frame이어야 한다."""
        with pytest.raises(ValueError, match="impact_frame"):
            ef.validate_annotations(
                [_row(fall_start_frame=20, impact_frame=10, lying_start_frame=30)]
            )

    def test_allows_out_of_order_check_to_skip_missing_values(self):
        """impact_frame이 없으면 fall_start_frame과 lying_start_frame만 비교한다."""
        ef.validate_annotations(
            [_row(fall_start_frame=10, impact_frame=None, lying_start_frame=20)]
        )

    def test_pending_fall_row_without_fall_start_frame_rejected_by_default(self):
        """--include-unreviewed로 pending 행까지 채점에 넘겨도, score_fall_video()의

        `None - int` TypeError로 죽기 전에 여기서 명확한 오류로 막아야 한다
        (v2 annotation은 검수 전까지 fall_start_frame이 비어 있을 수 있음).
        """
        with pytest.raises(ValueError, match="fall_start_frame"):
            ef.validate_annotations(
                [_row(label="fall", fall_start_frame=None, review_status="pending")]
            )

    def test_require_fall_start_frame_false_allows_pending_fall_row_without_frame(self):
        """review_caucafall_annotations.py의 자동 저장 전용 경로: 구조만 검증한다."""
        ef.validate_annotations(
            [_row(label="fall", fall_start_frame=None, review_status="pending")],
            require_fall_start_frame=False,
        )

    def test_require_fall_start_frame_false_still_rejects_reviewed_row_without_frame(self):
        """require_fall_start_frame=False는 pending/needs_review 전용 예외이지,

        review_status=reviewed까지 봐주면 안 된다 — CSV를 손으로 고치거나 손상된
        기존 행을 그대로 다시 저장해서 불완전한 reviewed가 남는 걸 막아야 한다.
        """
        with pytest.raises(ValueError, match="fall_start_frame"):
            ef.validate_annotations(
                [_row(label="fall", fall_start_frame=None, review_status="reviewed")],
                require_fall_start_frame=False,
            )


class TestLoadAnnotationsRequiredColumns:
    def test_missing_column_raises(self, tmp_path):
        path = tmp_path / "bad.csv"
        path.write_text("video_id,label,video_path\nv1,fall,v1.avi\n")

        with pytest.raises(ValueError, match="필수 컬럼"):
            ef.load_annotations(str(path), include_unreviewed=True)

    def test_valid_header_loads(self, tmp_path):
        path = tmp_path / "ok.csv"
        with open(path, "w", newline="") as file:
            writer = csv.DictWriter(
                file,
                fieldnames=sorted(ef._REQUIRED_COLUMNS),
            )
            writer.writeheader()
            writer.writerow(
                {
                    "video_id": "v1",
                    "label": "fall",
                    "video_path": "v1.avi",
                    "fall_start_frame": "10",
                    "impact_frame": "12",
                    "lying_start_frame": "14",
                    "review_status": "reviewed",
                }
            )

        rows = ef.load_annotations(str(path), include_unreviewed=False)
        assert len(rows) == 1
        assert rows[0].fall_start_frame == 10


class TestFindExcludedRows:
    def _write_csv(self, path, rows):
        with open(path, "w", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=sorted(ef._REQUIRED_COLUMNS))
            writer.writeheader()
            for row in rows:
                writer.writerow(row)

    def test_reports_non_reviewed_rows(self, tmp_path):
        path = tmp_path / "ann.csv"
        self._write_csv(
            path,
            [
                {
                    "video_id": "v1",
                    "label": "fall",
                    "video_path": "v1.avi",
                    "fall_start_frame": "10",
                    "impact_frame": "",
                    "lying_start_frame": "",
                    "review_status": "reviewed",
                },
                {
                    "video_id": "v2",
                    "label": "fall",
                    "video_path": "v2.avi",
                    "fall_start_frame": "10",
                    "impact_frame": "",
                    "lying_start_frame": "",
                    "review_status": "needs_review",
                },
            ],
        )

        excluded = ef.find_excluded_rows(str(path), include_unreviewed=False)

        assert excluded == [{"video_id": "v2", "review_status": "needs_review"}]

    def test_include_unreviewed_reports_nothing_excluded(self, tmp_path):
        path = tmp_path / "ann.csv"
        self._write_csv(
            path,
            [
                {
                    "video_id": "v2",
                    "label": "fall",
                    "video_path": "v2.avi",
                    "fall_start_frame": "10",
                    "impact_frame": "",
                    "lying_start_frame": "",
                    "review_status": "needs_review",
                },
            ],
        )

        assert ef.find_excluded_rows(str(path), include_unreviewed=True) == []


class TestHoldoutGuard:
    def test_allows_development_split(self, tmp_path):
        ef.guard_holdout(tmp_path / "development", "development", [_row()], allow_holdout=False)

    def test_blocks_split_flag_holdout(self, tmp_path):
        with pytest.raises(SystemExit):
            ef.guard_holdout(tmp_path / "v5", "holdout", [_row()], allow_holdout=False)

    def test_blocks_holdout_in_videos_dir(self, tmp_path):
        holdout_dir = tmp_path / "holdout"
        with pytest.raises(SystemExit):
            ef.guard_holdout(holdout_dir, "", [_row()], allow_holdout=False)

    def test_blocks_holdout_via_absolute_video_path_in_row(self, tmp_path):
        """--videos-dir 자체는 holdout이 아니어도, 개별 행이 holdout 절대경로를 가리키면 막아야 한다."""
        development_dir = tmp_path / "development"
        holdout_video = tmp_path / "holdout" / "v1.avi"
        row = _row(video_path=str(holdout_video))

        with pytest.raises(SystemExit):
            ef.guard_holdout(development_dir, "development", [row], allow_holdout=False)

    def test_blocks_symlink_pointing_into_holdout(self, tmp_path):
        """development/ 안의 symlink가 holdout/ 파일을 가리키면 가드를 우회하면 안 된다.

        resolve_video_path()가 .resolve()로 symlink를 실제 대상까지 따라가지
        않으면, symlink 자체의 경로(development/link.avi)에는 'holdout'이
        전혀 나타나지 않아 _contains_holdout_segment가 통과시켜 버린다.
        """
        development_dir = tmp_path / "development"
        development_dir.mkdir()
        holdout_dir = tmp_path / "holdout"
        holdout_dir.mkdir()
        real_video = holdout_dir / "v1.avi"
        real_video.write_bytes(b"")

        link = development_dir / "link.avi"
        try:
            link.symlink_to(real_video)
        except OSError as exc:
            # Windows에서 Developer Mode/관리자 권한이 없으면 symlink 생성 자체가
            # 거부된다(WinError 1314). 이 환경에서만 가드 로직을 검증할 수 없으므로
            # skip한다 — 그 외 OSError(예: 다른 플랫폼의 예기치 못한 실패)는 실제
            # 버그일 수 있으므로 숨기지 않고 그대로 올린다.
            if getattr(exc, "winerror", None) == 1314:
                pytest.skip(f"symlink 생성 권한이 없어 이 테스트를 건너뜁니다: {exc}")
            raise

        row = _row(video_path="link.avi")

        with pytest.raises(SystemExit):
            ef.guard_holdout(development_dir, "development", [row], allow_holdout=False)

    def test_allow_holdout_flag_bypasses_guard(self, tmp_path):
        holdout_dir = tmp_path / "holdout"
        ef.guard_holdout(holdout_dir, "holdout", [_row()], allow_holdout=True)

    def test_rejects_unrecognized_split_name(self, tmp_path):
        with pytest.raises(SystemExit):
            ef.guard_holdout(
                tmp_path / "development", "not_a_real_split", [_row()], allow_holdout=False
            )

    def test_rejects_unrecognized_split_name_even_with_allow_holdout(self, tmp_path):
        """--allow-holdout이 holdout 검사는 건너뛰어도, 잘못된 split 이름 자체는 걸러야 한다."""
        with pytest.raises(SystemExit):
            ef.guard_holdout(
                tmp_path / "development", "not_a_real_split", [_row()], allow_holdout=True
            )


class TestSummarize:
    def test_recall_and_false_alarm_and_latency(self):
        results = [
            ef._VideoResult(
                video_id="fall_ok", label="fall", event_count=1, detected=True, latency_sec=0.5
            ),
            ef._VideoResult(video_id="fall_missed", label="fall", event_count=0, detected=False),
            ef._VideoResult(
                video_id="adl_1", label="no_fall", event_count=1, duration_sec=60.0
            ),
            ef._VideoResult(
                video_id="adl_2", label="no_fall", event_count=0, duration_sec=60.0
            ),
        ]

        summary = ef._summarize(results)

        assert summary["fall_videos"] == 2
        assert summary["no_fall_videos"] == 2
        assert summary["recall"] == pytest.approx(0.5)
        # 총 2분(120초)에 false alarm 1건 → 분당 0.5건
        assert summary["false_alarm_per_min"] == pytest.approx(0.5)
        assert summary["avg_detection_latency_sec"] == pytest.approx(0.5)

    def test_errored_videos_are_excluded_from_denominators(self):
        results = [
            ef._VideoResult(video_id="v1", label="fall", event_count=0, error="파일 없음"),
        ]
        summary = ef._summarize(results)
        assert summary["fall_videos"] == 0
        assert summary["recall"] is None
        assert summary["skipped_with_error"] == 1

    def test_early_false_alarms_are_reported_separately_from_recall(self):
        results = [
            ef._VideoResult(
                video_id="v1",
                label="fall",
                event_count=2,
                detected=True,
                latency_sec=0.1,
                early_false_alarms=1,
                qualifying_event_count=1,
            ),
        ]
        summary = ef._summarize(results)
        assert summary["early_false_alarms_in_fall_videos"] == 1
        assert summary["recall"] == pytest.approx(1.0)

    def test_early_false_alarm_does_not_count_as_multi_event(self):
        """이른 오탐 1개 + 정상 확정 1개(event_count=2, qualifying=1)는 중복 확정이 아니다."""
        results = [
            ef._VideoResult(
                video_id="v1",
                label="fall",
                event_count=2,
                detected=True,
                latency_sec=0.1,
                early_false_alarms=1,
                qualifying_event_count=1,
            ),
        ]
        summary = ef._summarize(results)
        assert summary["falls_with_multiple_events"] == 0

    def test_real_multi_event_fall_is_still_counted(self):
        results = [
            ef._VideoResult(
                video_id="v1",
                label="fall",
                event_count=2,
                detected=True,
                latency_sec=0.1,
                qualifying_event_count=2,
            ),
        ]
        summary = ef._summarize(results)
        assert summary["falls_with_multiple_events"] == 1

    def test_evaluation_valid_is_true_when_no_errors(self):
        results = [
            ef._VideoResult(
                video_id="v1", label="fall", event_count=1, detected=True, latency_sec=0.1
            ),
        ]
        summary = ef._summarize(results)
        assert summary["evaluation_valid"] is True
        assert summary["recall_meets_target_75pct"] is True

    def test_evaluation_invalid_forces_target_flags_false(self):
        """오류 영상이 있으면 recall 등이 우연히 목표를 만족해도 전부 False로 강제해야 한다."""
        results = [
            ef._VideoResult(
                video_id="ok", label="fall", event_count=1, detected=True, latency_sec=0.1
            ),
            ef._VideoResult(video_id="err1", label="fall", event_count=0, error="파일 없음"),
            ef._VideoResult(video_id="err2", label="fall", event_count=0, error="파일 없음"),
            ef._VideoResult(video_id="err3", label="fall", event_count=0, error="파일 없음"),
        ]
        summary = ef._summarize(results)

        assert summary["recall"] == pytest.approx(1.0)  # 분모 자체는 여전히 1개(성공한 것만)
        assert summary["evaluation_valid"] is False
        assert summary["recall_meets_target_75pct"] is False
        assert summary["false_alarm_meets_target_0.2"] is False
        assert summary["latency_meets_target_2sec"] is False

    def test_evaluation_invalid_forces_timely_recall_target_flag_false(self):
        """오류 영상이 있으면 timely_recall이 우연히 100%여도 목표 달성 플래그는 False여야 한다."""
        results = [
            ef._VideoResult(
                video_id="ok", label="fall", event_count=1, timely_detected=True
            ),
            ef._VideoResult(video_id="err1", label="fall", event_count=0, error="파일 없음"),
        ]
        summary = ef._summarize(results)

        assert summary["timely_recall"] == pytest.approx(1.0)  # 분모 자체는 1개(성공한 것만)
        assert summary["timely_recall_meets_target_75pct"] is False

    def test_timely_recall_counts_only_timely_detected(self):
        results = [
            ef._VideoResult(video_id="v1", label="fall", event_count=1, timely_detected=True),
            ef._VideoResult(video_id="v2", label="fall", event_count=1, timely_detected=False),
        ]
        summary = ef._summarize(results)
        assert summary["timely_recall"] == pytest.approx(0.5)

    def test_timely_recall_meets_target_uses_75pct_threshold(self):
        results = [
            ef._VideoResult(video_id=f"v{i}", label="fall", event_count=1, timely_detected=True)
            for i in range(3)
        ] + [ef._VideoResult(video_id="v4", label="fall", event_count=0, timely_detected=False)]
        summary = ef._summarize(results)
        assert summary["timely_recall"] == pytest.approx(0.75)
        assert summary["timely_recall_meets_target_75pct"] is True

    def test_avg_onset_latency_and_lead_to_impact_ignore_non_timely_videos(self):
        results = [
            ef._VideoResult(
                video_id="v1",
                label="fall",
                event_count=1,
                timely_detected=True,
                onset_latency_sec=0.5,
                lead_to_impact_sec=0.2,
            ),
            ef._VideoResult(
                video_id="v2",
                label="fall",
                event_count=1,
                timely_detected=True,
                onset_latency_sec=1.5,
                lead_to_impact_sec=-0.4,
            ),
            # timely_detected=False인데 late_detection으로 latency 필드가 채워질 리
            # 없지만, 혹시 채워져 있어도 평균에 섞이면 안 된다는 걸 명시적으로 검증한다.
            ef._VideoResult(video_id="v3", label="fall", event_count=1, timely_detected=False),
        ]
        summary = ef._summarize(results)
        assert summary["avg_onset_latency_sec"] == pytest.approx((0.5 + 1.5) / 2)
        assert summary["avg_lead_to_impact_sec"] == pytest.approx((0.2 - 0.4) / 2)

    def test_late_detections_and_duplicate_events_are_counted(self):
        results = [
            ef._VideoResult(
                video_id="v1", label="fall", event_count=1, timely_detected=False,
                late_detection=True,
            ),
            ef._VideoResult(
                video_id="v2", label="fall", event_count=2, timely_detected=True,
                duplicate_event=True,
            ),
            ef._VideoResult(video_id="v3", label="fall", event_count=1, timely_detected=True),
        ]
        summary = ef._summarize(results)
        assert summary["late_detections"] == 1
        assert summary["duplicate_events"] == 1

    def test_timely_recall_is_none_when_no_fall_videos(self):
        results = [ef._VideoResult(video_id="v1", label="no_fall", event_count=0)]
        summary = ef._summarize(results)
        assert summary["timely_recall"] is None
        assert summary["timely_recall_meets_target_75pct"] is False


_STANDING_BBOX = [40.0, 0.0, 60.0, 60.0]  # tests/test_fall_detector.py와 동일
_LYING_BBOX = [10.0, 50.0, 90.0, 70.0]


def _tracking_result(frame_number, bbox, video_source="cam1", track_id=1):
    return TrackingResult(
        frame_number=frame_number,
        timestamp="00:00:00.000",
        video_source=video_source,
        tracks=[
            Track(
                track_id=track_id,
                bbox=list(bbox),
                foot_point=[(bbox[0] + bbox[2]) / 2.0, bbox[3]],
                confidence=0.9,
            )
        ],
    )


def _frame_source(frames):
    """(frame_number, bbox) 목록 -> score_video_from_frame_source()가 받는

    (frame_number, TrackingResult, raw_detections) 튜플 반복자. 보조 모델은
    쓰지 않으므로 raw_detections는 항상 None.
    """
    for frame_number, bbox in frames:
        yield frame_number, _tracking_result(frame_number, bbox), None


class TestScoreVideoEventDiagnostics:
    """score_video_from_frame_source()가 label·timely 구간과 무관하게

    confirm된 모든 Event의 진단(event_diagnostics)을 남기는지 검증한다.
    대표 timely Event 필드만으로는 no_fall 오탐이나 late_detection의
    confirm 경로를 알 수 없다.
    """

    def _fast_config(self):
        return FallDetectorConfig(cooldown_sec=1.0)

    def _standing_then_lying_frames(self, num_standing=5, num_lying=10):
        frames = [(i, _STANDING_BBOX) for i in range(num_standing)]
        frames += [
            (num_standing + i, _LYING_BBOX) for i in range(num_lying)
        ]
        return frames

    def test_no_fall_false_alarm_gets_event_diagnostics(self):
        """no_fall 행: confirm_path/candidate_entry_reason(대표 필드)은 기존과

        같이 계속 None이지만, event_diagnostics에는 실제 오탐의 진단이 남아야
        한다.
        """
        fps = 10.0
        row = _row(label="no_fall", fall_start_frame=None, impact_frame=None)

        result = ef.score_video_from_frame_source(
            row,
            _frame_source(self._standing_then_lying_frames()),
            fps,
            self._fast_config(),
        )

        assert result.event_count >= 1
        assert result.confirm_path is None
        assert result.candidate_entry_reason is None
        assert len(result.event_diagnostics) == result.event_count
        first = result.event_diagnostics[0]
        assert first["frame_number"] == result.event_frames[0]
        assert first["track_id"] == 1  # 중복 Event가 같은 Track인지 다른 Track인지 구분용
        assert first["confirm_path"] is not None
        assert first["candidate_entry_reason"] is not None
        assert 0.0 <= first["event_confidence"] <= 1.0
        assert first["candidate_duration_sec"] is not None
        assert first["max_descent_score"] >= 0.0
        assert first["confirm_aspect_ratio"] > 0.0

    def test_late_detection_gets_event_diagnostics_even_without_timely_match(self):
        """fall 행: timely 구간을 벗어난(late_detection) Event는 대표

        confirm_path/candidate_entry_reason에는 안 잡히지만, event_diagnostics
        에는 여전히 남아야 한다.
        """
        fps = 10.0
        # timely 구간을 [0.0, 0.1]초로 극히 좁혀서, 실제 confirm(약 t=1.0초)이
        # 확실히 그 밖에 오도록 만든다.
        row = _row(label="fall", fall_start_frame=0, impact_frame=None)

        result = ef.score_video_from_frame_source(
            row,
            _frame_source(self._standing_then_lying_frames()),
            fps,
            self._fast_config(),
            early_tolerance_sec=0.0,
            timely_window_sec=0.1,
        )

        assert result.timely_detected is False
        assert result.late_detection is True
        assert result.confirm_path is None  # 대표 필드는 timely 구간 안만 본다
        assert result.candidate_entry_reason is None
        assert len(result.event_diagnostics) == result.event_count
        assert result.event_diagnostics[0]["confirm_path"] is not None
        assert result.event_diagnostics[0]["candidate_entry_reason"] is not None
        assert result.event_diagnostics[0]["candidate_duration_sec"] is not None

    def test_video_result_to_dict_includes_event_diagnostics(self):
        fps = 10.0
        row = _row(label="no_fall", fall_start_frame=None, impact_frame=None)

        result = ef.score_video_from_frame_source(
            row,
            _frame_source(self._standing_then_lying_frames()),
            fps,
            self._fast_config(),
        )

        as_dict = ef.video_result_to_dict(result)
        assert as_dict["event_diagnostics"] == result.event_diagnostics
