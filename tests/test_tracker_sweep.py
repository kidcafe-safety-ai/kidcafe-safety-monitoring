"""scripts/tracker_sweep.py 테스트.

실제 cache_fall_signals.py/evaluate_fall_from_cache.py 서브프로세스는 돌리지
않는다 — tracker_sweep._run()을 몽키패치해서 명령 구성과 결과 집계·오류
처리만 검증한다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import tracker_sweep as ts  # noqa: E402


def _write_dev_annotations_csv(path: Path, video_ids) -> None:
    path.write_text(
        "video_id,label,video_path,fall_start_frame,impact_frame,lying_start_frame,"
        "review_status\n"
        + "".join(f"{vid},no_fall,{vid}.avi,,,,reviewed\n" for vid in video_ids)
    )


class TestSubjectNumber:
    def test_parses_leading_digits(self):
        assert ts._subject_number("S7_fall_backwards") == 7
        assert ts._subject_number("S10_walk") == 10

    def test_none_when_no_leading_s(self):
        assert ts._subject_number("walk_S7") is None

    def test_none_when_no_digits_after_s(self):
        assert ts._subject_number("Something") is None


class TestGuardDevelopmentOnly:
    def test_rejects_non_development_split(self, tmp_path):
        csv_path = tmp_path / "annotations.csv"
        _write_dev_annotations_csv(csv_path, ["S1_walk"])

        with pytest.raises(SystemExit, match="Development에서만"):
            ts.guard_development_only("validation", str(csv_path))

    def test_rejects_validation_subjects_even_if_split_claims_development(self, tmp_path):
        """--split=development라고 우겨도 실제 video_id가 Subject 7~8이면 막아야 한다."""
        csv_path = tmp_path / "annotations.csv"
        _write_dev_annotations_csv(csv_path, ["S1_walk", "S7_fall_backwards"])

        with pytest.raises(SystemExit, match="Development.*Subject 1~6"):
            ts.guard_development_only("development", str(csv_path))

    def test_allows_genuine_development_subjects(self, tmp_path):
        csv_path = tmp_path / "annotations.csv"
        _write_dev_annotations_csv(csv_path, ["S1_walk", "S6_fall_backwards"])

        ts.guard_development_only("development", str(csv_path))  # 예외 없이 통과


class TestRunOneConfStaleResultHandling:
    def _base_summary(self, evaluation_valid=True, skipped_with_error=0):
        return {
            "evaluation_valid": evaluation_valid,
            "skipped_with_error": skipped_with_error,
            "recall": 1.0,
            "timely_recall": 1.0,
            "false_alarm_per_min": 0.0,
            "videos": [
                {
                    "video_id": "S1_fall_backwards",
                    "label": "fall",
                    "error": None,
                    "track_coverage": 0.9,
                    "id_switch_count": 1,
                },
                {
                    "video_id": "S1_walk",
                    "label": "no_fall",
                    "error": None,
                    "track_coverage": 1.0,
                    "id_switch_count": 0,
                },
            ],
        }

    def _args(self, tmp_path, annotations, cache_base_dir):
        return argparse_namespace(
            annotations=str(annotations),
            videos_dir=str(tmp_path / "videos"),
            split="development",
            tracker="pose",
            model=None,
            device="auto",
            fall_model_path=None,
            fall_model_conf=0.5,
            fall_model_device="auto",
            fall_model_iou_threshold=0.3,
            config="configs/fall_detection.json",
            early_tolerance_sec=0.2,
            timely_window_sec=2.0,
            cache_base_dir=str(cache_base_dir),
            output=str(tmp_path / "summary.json"),
            include_unreviewed=False,
            force=False,
        )

    def test_stale_eval_output_is_not_reused_when_new_run_fails_to_write(
        self, tmp_path, monkeypatch
    ):
        """cache 단계는 성공하지만 eval 서브프로세스가 파일을 못 남기고 죽으면,

        직전 실행의 eval_summary.json이 새 결과인 것처럼 재사용되면 안 된다.
        """
        annotations = tmp_path / "annotations.csv"
        _write_dev_annotations_csv(annotations, ["S1_walk"])
        cache_base_dir = tmp_path / "cache"
        conf = 0.5
        cache_dir = ts._cache_dir_for(cache_base_dir, conf)
        cache_dir.mkdir(parents=True)
        # 이전(다른) 실행이 남긴 stale 결과.
        (cache_dir / "eval_summary.json").write_text(
            json.dumps(self._base_summary(evaluation_valid=True))
        )

        call_log = []

        def _fake_run(cmd):
            call_log.append(cmd)
            if "cache_fall_signals.py" in cmd[1]:
                return 0  # 캐싱은 성공
            return 1  # eval은 실패하고 파일을 안 씀(이번 실행에서)

        monkeypatch.setattr(ts, "_run", _fake_run)

        result = ts.run_one_conf(conf, self._args(tmp_path, annotations, cache_base_dir))

        assert "error" in result
        assert not (cache_dir / "eval_summary.json").exists()  # stale 파일도 지워짐

    def test_evaluation_invalid_is_reported_as_error_not_a_normal_row(
        self, tmp_path, monkeypatch
    ):
        annotations = tmp_path / "annotations.csv"
        _write_dev_annotations_csv(annotations, ["S1_walk"])
        cache_base_dir = tmp_path / "cache"
        conf = 0.5
        cache_dir = ts._cache_dir_for(cache_base_dir, conf)
        cache_dir.mkdir(parents=True)

        def _fake_run(cmd):
            if "evaluate_fall_from_cache.py" in cmd[1]:
                (cache_dir / "eval_summary.json").write_text(
                    json.dumps(self._base_summary(evaluation_valid=False, skipped_with_error=1))
                )
            return 0

        monkeypatch.setattr(ts, "_run", _fake_run)

        result = ts.run_one_conf(conf, self._args(tmp_path, annotations, cache_base_dir))

        assert "error" in result
        assert "evaluation_valid=False" in result["error"]

    def test_fps_is_none_when_some_videos_were_skipped_not_freshly_cached(
        self, tmp_path, monkeypatch
    ):
        annotations = tmp_path / "annotations.csv"
        _write_dev_annotations_csv(annotations, ["S1_walk"])
        cache_base_dir = tmp_path / "cache"
        conf = 0.5
        cache_dir = ts._cache_dir_for(cache_base_dir, conf)
        cache_dir.mkdir(parents=True)

        def _fake_run(cmd):
            if "cache_fall_signals.py" in cmd[1]:
                # 실제 cache_fall_signals.py처럼, 이번 실행에서 새로 캐싱한
                # 영상 기준으로 timing_report.json을 쓴다(일부는 건너뜀).
                (cache_dir / "timing_report.json").write_text(
                    json.dumps({"fps_avg": 12.3, "skipped_count": 1, "videos_timed": 1})
                )
            if "evaluate_fall_from_cache.py" in cmd[1]:
                (cache_dir / "eval_summary.json").write_text(
                    json.dumps(self._base_summary(evaluation_valid=True))
                )
            return 0

        monkeypatch.setattr(ts, "_run", _fake_run)

        result = ts.run_one_conf(conf, self._args(tmp_path, annotations, cache_base_dir))

        assert result["fps_avg"] is None

    def test_fps_reported_when_all_videos_freshly_cached(self, tmp_path, monkeypatch):
        annotations = tmp_path / "annotations.csv"
        _write_dev_annotations_csv(annotations, ["S1_walk"])
        cache_base_dir = tmp_path / "cache"
        conf = 0.5
        cache_dir = ts._cache_dir_for(cache_base_dir, conf)
        cache_dir.mkdir(parents=True)

        def _fake_run(cmd):
            if "cache_fall_signals.py" in cmd[1]:
                (cache_dir / "timing_report.json").write_text(
                    json.dumps({"fps_avg": 12.3, "skipped_count": 0, "videos_timed": 1})
                )
            if "evaluate_fall_from_cache.py" in cmd[1]:
                (cache_dir / "eval_summary.json").write_text(
                    json.dumps(self._base_summary(evaluation_valid=True))
                )
            return 0

        monkeypatch.setattr(ts, "_run", _fake_run)

        result = ts.run_one_conf(conf, self._args(tmp_path, annotations, cache_base_dir))

        assert result["fps_avg"] == pytest.approx(12.3)

    def test_stale_timing_report_is_not_reused_when_cache_step_writes_nothing_new(
        self, tmp_path, monkeypatch
    ):
        """직전(다른) 실행이 남긴 skipped_count=0짜리 timing_report.json이 있는데,

        이번 캐싱 단계가 전부 건너뛰어(--force 없이 이미 캐시가 있어서) 새
        timing_report.json을 안 쓰면 지난 FPS가 이번 결과인 것처럼 보고되면
        안 된다.
        """
        annotations = tmp_path / "annotations.csv"
        _write_dev_annotations_csv(annotations, ["S1_walk"])
        cache_base_dir = tmp_path / "cache"
        conf = 0.5
        cache_dir = ts._cache_dir_for(cache_base_dir, conf)
        cache_dir.mkdir(parents=True)
        # 지난 실행이 남긴 stale timing report — skipped_count=0이라 겉보기엔
        # "믿을 만한" 값처럼 보인다.
        (cache_dir / "timing_report.json").write_text(
            json.dumps({"fps_avg": 999.0, "skipped_count": 0, "videos_timed": 1})
        )

        def _fake_run(cmd):
            # cache_fall_signals.py 단계: 이번 실행은 아무 영상도 새로
            # 캐싱하지 않는다(전부 이미 존재) -> timing_report.json을 안 씀.
            if "evaluate_fall_from_cache.py" in cmd[1]:
                (cache_dir / "eval_summary.json").write_text(
                    json.dumps(self._base_summary(evaluation_valid=True))
                )
            return 0

        monkeypatch.setattr(ts, "_run", _fake_run)

        result = ts.run_one_conf(conf, self._args(tmp_path, annotations, cache_base_dir))

        assert result["fps_avg"] is None
        assert not (cache_dir / "timing_report.json").exists()

    def test_aggregates_track_coverage_and_id_switch_correctly(self, tmp_path, monkeypatch):
        annotations = tmp_path / "annotations.csv"
        _write_dev_annotations_csv(annotations, ["S1_walk"])
        cache_base_dir = tmp_path / "cache"
        conf = 0.5
        cache_dir = ts._cache_dir_for(cache_base_dir, conf)
        cache_dir.mkdir(parents=True)

        def _fake_run(cmd):
            if "evaluate_fall_from_cache.py" in cmd[1]:
                (cache_dir / "eval_summary.json").write_text(
                    json.dumps(self._base_summary(evaluation_valid=True))
                )
            return 0

        monkeypatch.setattr(ts, "_run", _fake_run)

        result = ts.run_one_conf(conf, self._args(tmp_path, annotations, cache_base_dir))

        assert result["avg_fall_track_coverage"] == pytest.approx(0.9)
        assert result["avg_fall_id_switch_count"] == pytest.approx(1.0)
        assert result["avg_no_fall_id_switch_count"] == pytest.approx(0.0)


class TestMainExitsNonZeroOnFailure:
    def test_main_raises_when_any_conf_failed(self, tmp_path, monkeypatch):
        annotations = tmp_path / "annotations.csv"
        _write_dev_annotations_csv(annotations, ["S1_walk"])
        cache_base_dir = tmp_path / "cache"

        monkeypatch.setattr(
            ts, "run_one_conf", lambda conf, args: {"conf": conf, "error": "시뮬레이션 실패"}
        )
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "tracker_sweep.py",
                "--annotations", str(annotations),
                "--videos-dir", str(tmp_path / "videos"),
                "--split", "development",
                "--conf-values", "0.5",
                "--cache-base-dir", str(cache_base_dir),
                "--output", str(tmp_path / "summary.json"),
            ],
        )

        with pytest.raises(SystemExit, match="실패/무효"):
            ts.main()


def argparse_namespace(**kwargs):
    import argparse

    return argparse.Namespace(**kwargs)
