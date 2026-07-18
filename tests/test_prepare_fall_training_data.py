"""scripts/prepare_fall_training_data.py 테스트.

실제 CAUCAFall 데이터 없이도 검증 가능하도록, PNG+txt 쌍을 가진 임시
Subject.N/활동 디렉터리 구조를 만들어 확인한다.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import prepare_fall_training_data as prep  # noqa: E402


def _write_png(path: Path) -> None:
    if cv2 is not None:
        cv2.imwrite(str(path), np.zeros((16, 16, 3), dtype=np.uint8))
    else:  # pragma: no cover
        path.write_bytes(b"\x89PNG\r\n\x1a\n")


def _write_activity(
    root: Path, subject_num: int, activity_name: str, classes: list, filename_prefix: str
) -> None:
    activity_dir = root / f"Subject.{subject_num}" / activity_name
    activity_dir.mkdir(parents=True, exist_ok=True)
    for i, cls in enumerate(classes, start=1):
        stem = f"{filename_prefix}{i:05d}"
        _write_png(activity_dir / f"{stem}.png")
        (activity_dir / f"{stem}.txt").write_text(f"{cls} 0.5 0.5 0.2 0.4\n")
    (activity_dir / "classes.txt").write_text("nofall\nfall\n")


def _make_dataset(root: Path) -> None:
    _write_activity(root, 1, "Walk", ["0"] * 3, "cams1")
    _write_activity(root, 1, "Fall forward", ["0", "0", "1", "1"], "cfs1-")
    _write_activity(root, 2, "Walk", ["0"] * 2, "cams2")
    _write_activity(root, 6, "Walk", ["0"] * 2, "cams6")


class TestGuards:
    def test_holdout_blocked_without_flag(self):
        with pytest.raises(prep.ConfigError, match="holdout"):
            prep.guard_holdout([1, 2], [9], allow_holdout=False)

    def test_holdout_allowed_with_flag(self):
        prep.guard_holdout([1, 2], [9], allow_holdout=True)  # 예외 없이 통과해야 함

    def test_overlap_between_train_and_val_rejected(self):
        with pytest.raises(prep.ConfigError, match="양쪽"):
            prep.guard_overlap([1, 2, 3], [3, 4])

    def test_no_overlap_passes(self):
        prep.guard_overlap([1, 2, 3], [4, 5])  # 예외 없이 통과해야 함


class TestParseSubjectList:
    def test_parses_comma_separated(self):
        assert prep._parse_subject_list("1,2, 3") == [1, 2, 3]

    def test_empty_raises(self):
        with pytest.raises(prep.ConfigError):
            prep._parse_subject_list("")

    def test_non_numeric_raises(self):
        with pytest.raises(prep.ConfigError):
            prep._parse_subject_list("1,a,3")


class TestCollectFramePairs:
    def test_collects_all_activities_for_subject(self, tmp_path):
        _make_dataset(tmp_path)

        result = prep.collect_frame_pairs(tmp_path, subject_num=1)

        assert len(result.pairs) == 7  # Walk 3 + Fall forward 4
        assert result.total_input_images == 7
        assert all(p.subject_num == 1 for p in result.pairs)
        assert result.recovered == []
        assert result.skipped_missing_label == []

    def test_dest_stem_is_unique_across_activities(self, tmp_path):
        """서로 다른 활동 폴더의 원본 파일명이 충돌해도 dest_stem은 유일해야 한다."""
        _write_activity(tmp_path, 1, "Walk", ["0"], "cams1")
        _write_activity(tmp_path, 1, "Hop", ["0"], "cams1")  # 같은 접두사로 충돌 유도

        result = prep.collect_frame_pairs(tmp_path, subject_num=1)

        stems = [p.dest_stem for p in result.pairs]
        assert len(stems) == len(set(stems))

    def test_missing_subject_dir_raises(self, tmp_path):
        with pytest.raises(prep.ConfigError, match="Subject.99"):
            prep.collect_frame_pairs(tmp_path, subject_num=99)

    def test_missing_label_raises_by_default(self, tmp_path):
        activity_dir = tmp_path / "Subject.1" / "Walk"
        activity_dir.mkdir(parents=True)
        _write_png(activity_dir / "cams100001.png")
        # txt 라벨을 의도적으로 만들지 않음

        with pytest.raises(prep.ConfigError, match="라벨"):
            prep.collect_frame_pairs(tmp_path, subject_num=1, missing_label_policy="error")

    def test_missing_label_skipped_with_skip_policy(self, tmp_path):
        activity_dir = tmp_path / "Subject.1" / "Walk"
        activity_dir.mkdir(parents=True)
        missing_png = activity_dir / "cams100001.png"
        _write_png(missing_png)
        (activity_dir / "classes.txt").write_text("nofall\nfall\n")

        result = prep.collect_frame_pairs(tmp_path, subject_num=1, missing_label_policy="skip")

        assert result.pairs == []
        assert result.skipped_missing_label == [missing_png]
        assert result.total_input_images == 1

    def test_copia_suffix_is_recovered(self, tmp_path):
        """cas200091 - copia.png처럼 접미사가 붙은 PNG는 접미사 없는 txt로 복구돼야 한다."""
        activity_dir = tmp_path / "Subject.2" / "Fall backwards"
        activity_dir.mkdir(parents=True)
        png_path = activity_dir / "cas200091 - copia.png"
        _write_png(png_path)
        (activity_dir / "cas200091.txt").write_text("1 0.5 0.5 0.2 0.4\n")
        (activity_dir / "classes.txt").write_text("nofall\nfall\n")

        result = prep.collect_frame_pairs(tmp_path, subject_num=2)

        assert len(result.pairs) == 1
        assert result.pairs[0].recovered is True
        assert result.pairs[0].label_path.name == "cas200091.txt"
        assert len(result.recovered) == 1

    def test_normal_and_copia_file_sharing_one_label_raises(self, tmp_path):
        """정상 파일(cas200091.png)과 copia 파일이 동시에 있으면 같은 라벨을 공유해 오류여야 한다."""
        activity_dir = tmp_path / "Subject.2" / "Fall backwards"
        activity_dir.mkdir(parents=True)
        _write_png(activity_dir / "cas200091.png")
        _write_png(activity_dir / "cas200091 - copia.png")
        (activity_dir / "cas200091.txt").write_text("1 0.5 0.5 0.2 0.4\n")
        (activity_dir / "classes.txt").write_text("nofall\nfall\n")

        with pytest.raises(prep.ConfigError, match="두 이미지"):
            prep.collect_frame_pairs(tmp_path, subject_num=2)

    def test_numeric_only_match_is_not_recovered(self, tmp_path):
        """접미사가 없는 순수 숫자 불일치는 복구 대상이 아니라 라벨 누락으로 처리돼야 한다."""
        activity_dir = tmp_path / "Subject.1" / "Walk"
        activity_dir.mkdir(parents=True)
        _write_png(activity_dir / "cams100001.png")
        # 의도적으로 이름이 다른 엉뚱한 txt만 존재 (숫자 기반 추측 매칭 금지 검증)
        (activity_dir / "cams100002.txt").write_text("0 0.5 0.5 0.2 0.4\n")
        (activity_dir / "classes.txt").write_text("nofall\nfall\n")

        with pytest.raises(prep.ConfigError, match="라벨"):
            prep.collect_frame_pairs(tmp_path, subject_num=1, missing_label_policy="error")

    def test_multiple_recovery_candidates_raises(self, tmp_path):
        activity_dir = tmp_path / "Subject.2" / "Fall backwards"
        activity_dir.mkdir(parents=True)
        _write_png(activity_dir / "cas200091 - copia.png")
        # 접미사 제거 후 동일하게 정규화되는 후보가 2개 존재하도록 유도
        (activity_dir / "cas200091.txt").write_text("1 0.5 0.5 0.2 0.4\n")
        (activity_dir / "cas200091 -  copia.txt").write_text("1 0.5 0.5 0.2 0.4\n")
        (activity_dir / "classes.txt").write_text("nofall\nfall\n")

        with pytest.raises(prep.ConfigError, match="여러 개"):
            prep.collect_frame_pairs(tmp_path, subject_num=2)


class TestWriteSplit:
    def test_copies_images_and_labels_with_class_counts(self, tmp_path):
        _make_dataset(tmp_path)
        result = prep.collect_frame_pairs(tmp_path, subject_num=1)
        dest = tmp_path / "out"

        counts = prep.write_split(result.pairs, dest, "train", force=False)

        # Walk: nofall 3, Fall forward: nofall 2 + fall 2
        assert counts == {"nofall": 5, "fall": 2}
        images = sorted((dest / "images" / "train").glob("*.png"))
        labels = sorted((dest / "labels" / "train").glob("*.txt"))
        assert len(images) == 7
        assert len(labels) == 7

    def test_refuses_to_overwrite_without_force(self, tmp_path):
        _make_dataset(tmp_path)
        result = prep.collect_frame_pairs(tmp_path, subject_num=1)
        dest = tmp_path / "out"
        prep.write_split(result.pairs, dest, "train", force=False)

        with pytest.raises(prep.ConfigError, match="force"):
            prep.write_split(result.pairs, dest, "train", force=False)

    def test_force_allows_overwrite(self, tmp_path):
        _make_dataset(tmp_path)
        result = prep.collect_frame_pairs(tmp_path, subject_num=1)
        dest = tmp_path / "out"
        prep.write_split(result.pairs, dest, "train", force=False)

        prep.write_split(result.pairs, dest, "train", force=True)  # 예외 없이 통과해야 함

    def test_force_clears_stale_files_from_previous_run(self, tmp_path):
        """이전 실행보다 프레임 수가 줄어도 예전 파일이 남아 있으면 안 된다."""
        _make_dataset(tmp_path)
        result = prep.collect_frame_pairs(tmp_path, subject_num=1)
        dest = tmp_path / "out"
        prep.write_split(result.pairs, dest, "train", force=False)
        assert len(list((dest / "images" / "train").glob("*.png"))) == 7

        # 프레임 수가 줄어든 상태로 재실행 (Subject 2만 사용, 2프레임)
        smaller_result = prep.collect_frame_pairs(tmp_path, subject_num=2)
        prep.write_split(smaller_result.pairs, dest, "train", force=True)

        images = list((dest / "images" / "train").glob("*.png"))
        labels = list((dest / "labels" / "train").glob("*.txt"))
        assert len(images) == 2
        assert len(labels) == 2


class TestMain:
    def test_writes_dataset_manifest_with_recovery_and_skip_info(
        self, tmp_path, capsys, monkeypatch
    ):
        root = tmp_path / "source"
        _write_activity(root, 1, "Walk", ["0", "0"], "cams1")
        # copia 복구 케이스
        activity_dir = root / "Subject.1" / "Fall backwards"
        activity_dir.mkdir(parents=True)
        _write_png(activity_dir / "cas100091 - copia.png")
        (activity_dir / "cas100091.txt").write_text("1 0.5 0.5 0.2 0.4\n")
        (activity_dir / "classes.txt").write_text("nofall\nfall\n")
        # 라벨 누락(skip) 케이스 + 정상 프레임 1개 (val 분할이 비지 않도록)
        missing_dir = root / "Subject.6" / "Kneel"
        missing_dir.mkdir(parents=True)
        _write_png(missing_dir / "ars600001.png")
        _write_png(missing_dir / "ars600002.png")
        (missing_dir / "ars600002.txt").write_text("0 0.5 0.5 0.2 0.4\n")
        (missing_dir / "classes.txt").write_text("nofall\nfall\n")

        dest = tmp_path / "out"
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "prepare_fall_training_data.py",
                "--source-root",
                str(root),
                "--dest",
                str(dest),
                "--train-subjects",
                "1",
                "--val-subjects",
                "6",
                "--missing-label-policy",
                "skip",
            ],
        )

        prep.main()

        manifest_path = dest / "dataset_manifest.json"
        assert manifest_path.is_file()
        import json

        manifest = json.loads(manifest_path.read_text())
        assert manifest["train_subjects"] == [1]
        assert manifest["val_subjects"] == [6]
        assert manifest["missing_label_policy"] == "skip"
        assert len(manifest["splits"]["train"]["recovered_copia"]) == 1
        assert len(manifest["splits"]["val"]["skipped_missing_label"]) == 1
        assert manifest["splits"]["train"]["matched_frames"] == 3  # Walk 2 + copia 복구 1
        assert manifest["splits"]["val"]["matched_frames"] == 1

        captured = capsys.readouterr()
        assert "복구" in captured.out
        assert "제외" in captured.out
