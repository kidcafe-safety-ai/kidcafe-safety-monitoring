"""scripts/generate_caucafall_annotations.py 테스트.

실제 CAUCAFall 데이터 없이도 실행 가능하도록, 합성 AVI(빈 프레임)와 txt
라벨로 임시 디렉터리 구조를 만들어 검증한다.
"""

from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import generate_caucafall_annotations as gen  # noqa: E402


def _write_avi(path: Path, frame_count: int, fps: float = 10.0) -> None:
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (32, 32))
    for _ in range(frame_count):
        writer.write(np.zeros((32, 32, 3), dtype=np.uint8))
    writer.release()


def _write_txt_labels(folder: Path, classes: list) -> None:
    """classes[i] == "0"/"1"/None(빈 파일)로 프레임별 txt를 만든다. 파일명은

    CAUCAFall 컨벤션(subject_id*100000 + 순번)을 흉내낸다.
    """
    for i, cls in enumerate(classes, start=1):
        txt_path = folder / f"cas1{i:05d}.txt"
        if cls is None:
            txt_path.write_text("")
        else:
            txt_path.write_text(f"{cls} 0.5 0.5 0.2 0.4\n")
    (folder / "classes.txt").write_text("nofall\nfall\n")


def _make_activity_folder(tmp_path: Path, name: str, avi_frames: int, classes: list) -> Path:
    folder = tmp_path / name
    folder.mkdir()
    _write_avi(folder / f"{name.replace(' ', '')}S1.avi", avi_frames)
    _write_txt_labels(folder, classes)
    return folder


class TestProcessActivityFolder:
    def test_fall_video_finds_transition_index(self, tmp_path):
        # frame 0,1,2 = nofall(0), frame 3,4 = fall(1) -> fall_start_frame == 3
        folder = _make_activity_folder(
            tmp_path, "Fall backwards", avi_frames=5, classes=["0", "0", "0", "1", "1"]
        )

        draft = gen.process_activity_folder(folder, subject_num=1, split_root=tmp_path)

        assert draft.label == "fall"
        assert draft.fall_start_frame == 3
        assert draft.review_status == "pending"
        assert draft.video_id == "S1_fall_backwards"

    def test_no_fall_video_has_no_fall_start_frame(self, tmp_path):
        folder = _make_activity_folder(
            tmp_path, "Walk", avi_frames=4, classes=["0", "0", "0", "0"]
        )

        draft = gen.process_activity_folder(folder, subject_num=1, split_root=tmp_path)

        assert draft.label == "no_fall"
        assert draft.fall_start_frame is None

    def test_excess_txt_beyond_avi_frame_count_is_dropped_from_the_end(self, tmp_path):
        """txt가 AVI 실제 프레임 수보다 많으면 뒤에서부터 제외하고 경고를 남긴다."""
        # AVI는 4프레임인데 txt는 5개(CAUCAFall에서 흔한 +1 패턴 재현)
        folder = _make_activity_folder(
            tmp_path, "Fall left", avi_frames=4, classes=["0", "0", "1", "1", "1"]
        )

        draft = gen.process_activity_folder(folder, subject_num=1, split_root=tmp_path)

        assert draft.warning is not None
        assert "4개" in draft.warning or "많음" in draft.warning
        # 뒤에서 1개(5번째 txt)만 제외되므로 판정 자체는 그대로(frame 2에서 전환)
        assert draft.fall_start_frame == 2

    def test_video_path_is_relative_to_split_root(self, tmp_path):
        subject_dir = tmp_path / "Subject.1"
        subject_dir.mkdir()
        folder = _make_activity_folder(
            subject_dir, "Walk", avi_frames=2, classes=["0", "0"]
        )

        draft = gen.process_activity_folder(folder, subject_num=1, split_root=tmp_path)

        assert draft.video_path == "Subject.1/Walk/WalkS1.avi"

    def test_rejects_folder_without_avi(self, tmp_path):
        folder = tmp_path / "Walk"
        folder.mkdir()
        _write_txt_labels(folder, ["0", "0"])

        with pytest.raises(ValueError, match="AVI"):
            gen.process_activity_folder(folder, subject_num=1, split_root=tmp_path)

    def test_rejects_folder_without_txt(self, tmp_path):
        folder = tmp_path / "Walk"
        folder.mkdir()
        _write_avi(folder / "WalkS1.avi", 2)

        with pytest.raises(ValueError, match="txt"):
            gen.process_activity_folder(folder, subject_num=1, split_root=tmp_path)


class TestFilenameNumberIsNotUsedAsFrameIndex:
    def test_sort_order_used_instead_of_numeric_suffix(self, tmp_path):
        """txt 파일명 숫자는 subject_id*100000 + 순번이라, 정렬 순서(0-base)를

        써야지 숫자를 직접 프레임 번호로 쓰면 안 된다.
        """
        folder = tmp_path / "Fall right"
        folder.mkdir()
        _write_avi(folder / "FallRightS2.avi", 3)
        # 파일명 숫자가 200001~200003이지만 실제 프레임 번호는 0,1,2여야 한다.
        (folder / "cds200001.txt").write_text("0 0.5 0.5 0.2 0.4\n")
        (folder / "cds200002.txt").write_text("0 0.5 0.5 0.2 0.4\n")
        (folder / "cds200003.txt").write_text("1 0.5 0.5 0.2 0.4\n")
        (folder / "classes.txt").write_text("nofall\nfall\n")

        draft = gen.process_activity_folder(folder, subject_num=2, split_root=tmp_path)

        assert draft.fall_start_frame == 2  # 파일명 숫자(200003)가 아니라 정렬 순서(index 2)


class TestHoldoutGuard:
    def test_rejects_dataset_dir_pointing_into_holdout(self, tmp_path):
        holdout_dir = tmp_path / "holdout"
        holdout_dir.mkdir()

        with pytest.raises(SystemExit):
            gen.guard_dataset_dir(holdout_dir)

    def test_allows_normal_dataset_dir(self, tmp_path):
        dataset_dir = tmp_path / "caucafall_v5"
        dataset_dir.mkdir()
        gen.guard_dataset_dir(dataset_dir)  # 예외 없이 통과해야 한다

    def test_development_and_validation_paths_are_not_holdout(self, tmp_path):
        assert gen._contains_holdout_segment((tmp_path / "development").resolve()) is False
        assert gen._contains_holdout_segment((tmp_path / "validation").resolve()) is False

    def test_split_subjects_never_include_9_or_10(self):
        all_subjects = set(gen._SPLIT_SUBJECTS["development"]) | set(
            gen._SPLIT_SUBJECTS["validation"]
        )
        assert 9 not in all_subjects
        assert 10 not in all_subjects


class TestGenerateSplit:
    def test_generates_one_draft_per_activity_folder(self, tmp_path):
        dataset_dir = tmp_path / "caucafall_v5"
        subject_dir = dataset_dir / "development" / "Subject.1"
        subject_dir.mkdir(parents=True)
        _make_activity_folder(subject_dir, "Walk", avi_frames=2, classes=["0", "0"])
        _make_activity_folder(
            subject_dir, "Fall backwards", avi_frames=3, classes=["0", "1", "1"]
        )

        drafts = gen.generate_split(dataset_dir, "development")

        assert len(drafts) == 2
        labels = {d.video_id: d.label for d in drafts}
        assert labels["S1_walk"] == "no_fall"
        assert labels["S1_fall_backwards"] == "fall"

    def test_missing_subject_directory_is_skipped_not_fatal(self, tmp_path, capsys):
        dataset_dir = tmp_path / "caucafall_v5"
        (dataset_dir / "development").mkdir(parents=True)
        # Subject.1~6 중 아무 것도 실제로 존재하지 않음

        drafts = gen.generate_split(dataset_dir, "development")

        assert drafts == []


def _draft(**overrides) -> "gen._AnnotationDraft":
    defaults = dict(
        video_id="S1_walk",
        label="no_fall",
        video_path="Subject.1/Walk/WalkS1.avi",
        fall_start_frame=None,
        review_status="pending",
        warning=None,
        txt_count=10,
        avi_frame_count=10,
    )
    defaults.update(overrides)
    return gen._AnnotationDraft(**defaults)


class TestWriteCsv:
    def test_writes_expected_columns_and_empty_optional_fields(self, tmp_path):
        drafts = [
            _draft(
                video_id="S1_fall_backwards",
                label="fall",
                video_path="Subject.1/Fall backwards/FallBackwardsS1.avi",
                fall_start_frame=58,
                txt_count=126,
                avi_frame_count=125,
                warning="txt 126개가 AVI 실제 프레임 수(125)보다 1개 많음 -> 뒤에서 1개 제외",
            ),
            _draft(video_id="S1_walk"),
        ]
        output_path = tmp_path / "development_annotations.csv"

        gen.write_csv(drafts, output_path)

        content = output_path.read_text(encoding="utf-8")
        assert content.splitlines()[0] == ",".join(gen._REQUIRED_COLUMNS)
        expected_fall_row = (
            "S1_fall_backwards,fall,Subject.1/Fall backwards/FallBackwardsS1.avi,58,,,pending"
        )
        assert expected_fall_row in content
        assert "S1_walk,no_fall,Subject.1/Walk/WalkS1.avi,,,,pending" in content


class TestGuardExistingOutput:
    def test_raises_when_output_exists_without_force(self, tmp_path):
        output_path = tmp_path / "development_annotations.csv"
        output_path.write_text("existing content, e.g. reviewed=true 결과 포함")

        with pytest.raises(SystemExit):
            gen.guard_existing_output(output_path, force=False)

        # 실패해도 기존 파일은 그대로여야 한다.
        assert output_path.read_text() == "existing content, e.g. reviewed=true 결과 포함"

    def test_allows_overwrite_with_force(self, tmp_path):
        output_path = tmp_path / "development_annotations.csv"
        output_path.write_text("old")
        gen.guard_existing_output(output_path, force=True)  # 예외 없이 통과

    def test_allows_when_output_does_not_exist_yet(self, tmp_path):
        output_path = tmp_path / "development_annotations.csv"
        gen.guard_existing_output(output_path, force=False)  # 예외 없이 통과


class TestVerifyExpectedCounts:
    def test_passes_when_counts_match(self):
        drafts = [_draft(label="fall")] * 30 + [_draft(label="no_fall")] * 30
        gen.verify_expected_counts(drafts, "development")  # 예외 없이 통과

    def test_raises_when_total_count_is_short(self):
        drafts = [_draft(label="fall")] * 29 + [_draft(label="no_fall")] * 30
        with pytest.raises(SystemExit, match="예상 수량"):
            gen.verify_expected_counts(drafts, "development")

    def test_raises_when_validation_counts_wrong(self):
        drafts = [_draft(label="fall")] * 9 + [_draft(label="no_fall")] * 10
        with pytest.raises(SystemExit, match="예상 수량"):
            gen.verify_expected_counts(drafts, "validation")


class TestWriteGenerationReport:
    def test_only_includes_videos_with_warnings(self, tmp_path):
        drafts = [
            _draft(video_id="clean", warning=None, txt_count=10, avi_frame_count=10),
            _draft(
                video_id="mismatched",
                warning="txt 12개가 AVI 실제 프레임 수(10)보다 2개 많음 -> 뒤에서 2개 제외",
                txt_count=12,
                avi_frame_count=10,
            ),
        ]
        output_path = tmp_path / "development_generation_report.csv"

        gen.write_generation_report(drafts, output_path)

        content = output_path.read_text(encoding="utf-8")
        assert "clean" not in content
        assert "mismatched,12,10,2" in content
