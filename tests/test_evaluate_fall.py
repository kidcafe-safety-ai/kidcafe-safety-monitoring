"""scripts/evaluate_fall.py의 순수 로직(점수 계산·annotation 검증·holdout 가드) 테스트.

실제 cv2/YOLO 파이프라인을 타는 _evaluate_video()는 scripts/ 컨벤션(예:
run_benchmark.py)과 마찬가지로 자동 테스트 대상이 아니다. 여기서는 cv2/YOLO
없이도 검증 가능한 순수 함수만 다룬다.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import evaluate_fall as ef  # noqa: E402


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
        link.symlink_to(real_video)

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
