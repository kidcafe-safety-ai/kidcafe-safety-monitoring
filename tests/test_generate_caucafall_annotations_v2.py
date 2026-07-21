"""scripts/generate_caucafall_annotations_v2.py 테스트.

test_generate_caucafall_annotations.py와 같은 합성 AVI/txt 헬퍼를 재사용해,
v1 generate_split()이 만든 draft로부터 v2 CSV(dataset_fall_label_frame 컬럼
추가, fall_start_frame/impact_frame/lying_start_frame은 비운 채 pending)가
올바르게 만들어지는지 검증한다.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import generate_caucafall_annotations_v2 as gen_v2  # noqa: E402

from test_generate_caucafall_annotations import _make_activity_folder  # noqa: E402

_TEST_SPLIT_SUBJECTS = {"development": [1, 2, 3, 4, 5, 6], "validation": [7, 8]}


def _draft(**overrides):
    import generate_caucafall_annotations as gen

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


class TestWriteV2Csv:
    def test_fall_row_seeds_dataset_fall_label_frame_and_leaves_others_empty(self, tmp_path):
        drafts = [
            _draft(
                video_id="S1_fall_backwards",
                label="fall",
                video_path="Subject.1/Fall backwards/FallBackwardsS1.avi",
                fall_start_frame=58,
            ),
        ]
        output_path = tmp_path / "development_annotations_v2.csv"

        gen_v2.write_v2_csv(drafts, output_path, needs_review_ids=set())

        with open(output_path, newline="", encoding="utf-8") as file:
            rows = list(csv.DictReader(file))

        assert rows[0]["dataset_fall_label_frame"] == "58"
        assert rows[0]["fall_start_frame"] == ""
        assert rows[0]["impact_frame"] == ""
        assert rows[0]["lying_start_frame"] == ""
        assert rows[0]["review_status"] == "pending"

    def test_no_fall_row_has_empty_dataset_fall_label_frame(self, tmp_path):
        drafts = [_draft(video_id="S1_walk", label="no_fall")]
        output_path = tmp_path / "development_annotations_v2.csv"

        gen_v2.write_v2_csv(drafts, output_path, needs_review_ids=set())

        with open(output_path, newline="", encoding="utf-8") as file:
            rows = list(csv.DictReader(file))

        assert rows[0]["dataset_fall_label_frame"] == ""
        assert rows[0]["review_status"] == "pending"

    def test_seeded_needs_review_id_is_carried_over(self, tmp_path):
        drafts = [
            _draft(video_id="S6_fall_backwards", label="fall", fall_start_frame=91),
            _draft(video_id="S1_fall_backwards", label="fall", fall_start_frame=58),
        ]
        output_path = tmp_path / "development_annotations_v2.csv"

        gen_v2.write_v2_csv(
            drafts, output_path, needs_review_ids={"S6_fall_backwards"}
        )

        with open(output_path, newline="", encoding="utf-8") as file:
            rows = {row["video_id"]: row for row in csv.DictReader(file)}

        assert rows["S6_fall_backwards"]["review_status"] == "needs_review"
        assert rows["S1_fall_backwards"]["review_status"] == "pending"

    def test_header_matches_required_columns(self, tmp_path):
        output_path = tmp_path / "development_annotations_v2.csv"
        gen_v2.write_v2_csv([_draft()], output_path, needs_review_ids=set())

        header = output_path.read_text(encoding="utf-8").splitlines()[0]
        assert header == ",".join(gen_v2._REQUIRED_COLUMNS)


class TestLoadNeedsReviewIds:
    def test_reads_only_needs_review_rows(self, tmp_path):
        csv_path = tmp_path / "development_annotations.csv"
        csv_path.write_text(
            "video_id,label,video_path,fall_start_frame,impact_frame,"
            "lying_start_frame,review_status\n"
            "S6_fall_backwards,fall,x.avi,91,,,needs_review\n"
            "S1_fall_backwards,fall,y.avi,58,,,reviewed\n"
            "S1_walk,no_fall,z.avi,,,,reviewed\n"
        )

        ids = gen_v2.load_needs_review_ids(str(csv_path))

        assert ids == {"S6_fall_backwards"}

    def test_missing_required_column_raises(self, tmp_path):
        csv_path = tmp_path / "bad.csv"
        csv_path.write_text("video_id,label\nS1_walk,no_fall\n")

        with pytest.raises(ValueError, match="video_id|review_status"):
            gen_v2.load_needs_review_ids(str(csv_path))

    def test_empty_video_id_with_needs_review_raises(self, tmp_path):
        csv_path = tmp_path / "bad.csv"
        csv_path.write_text(
            "video_id,label,video_path,fall_start_frame,impact_frame,"
            "lying_start_frame,review_status\n"
            ",fall,x.avi,91,,,needs_review\n"
        )

        with pytest.raises(ValueError, match="video_id"):
            gen_v2.load_needs_review_ids(str(csv_path))


class TestLoadNeedsReviewIdsFromAll:
    def test_unions_multiple_seed_files(self, tmp_path):
        dev_csv = tmp_path / "development_annotations.csv"
        dev_csv.write_text(
            "video_id,label,video_path,fall_start_frame,impact_frame,"
            "lying_start_frame,review_status\n"
            "S6_fall_backwards,fall,x.avi,91,,,needs_review\n"
        )
        val_csv = tmp_path / "validation_annotations.csv"
        val_csv.write_text(
            "video_id,label,video_path,fall_start_frame,impact_frame,"
            "lying_start_frame,review_status\n"
            "S8_fall_right,fall,y.avi,59,,,needs_review\n"
        )

        ids = gen_v2.load_needs_review_ids_from_all([str(dev_csv), str(val_csv)])

        assert ids == {"S6_fall_backwards", "S8_fall_right"}


class TestGenerateEndToEnd:
    def test_generates_v2_csv_from_real_split(self, tmp_path):
        dataset_dir = tmp_path / "caucafall_v5"
        subject_dir = dataset_dir / "development" / "Subject.1"
        subject_dir.mkdir(parents=True)
        _make_activity_folder(subject_dir, "Walk", avi_frames=2, classes=["0", "0"])
        _make_activity_folder(
            subject_dir, "Fall backwards", avi_frames=3, classes=["0", "1", "1"]
        )

        import generate_caucafall_annotations as gen

        drafts = gen.generate_split(dataset_dir, "development", _TEST_SPLIT_SUBJECTS)
        output_path = tmp_path / "development_annotations_v2.csv"
        gen_v2.write_v2_csv(drafts, output_path, needs_review_ids=set())

        with open(output_path, newline="", encoding="utf-8") as file:
            rows = {row["video_id"]: row for row in csv.DictReader(file)}

        assert rows["S1_fall_backwards"]["dataset_fall_label_frame"] == "1"
        assert rows["S1_walk"]["dataset_fall_label_frame"] == ""


class TestMainGuardsBothOutputsBeforeWritingEither:
    def test_existing_validation_output_blocks_before_development_is_written(
        self, tmp_path, monkeypatch
    ):
        """development는 아직 없고 validation만 이미 있으면, development도 전혀

        쓰이지 않아야 한다 (development를 먼저 쓴 뒤 validation에서 실패하면
        development만 덮어써진 절반 생성 상태로 남는 문제를 막는다).
        """
        output_dir = tmp_path / "annotations"
        output_dir.mkdir()
        (output_dir / "validation_annotations_v2.csv").write_text("existing")

        monkeypatch.setattr(
            sys,
            "argv",
            [
                "generate_caucafall_annotations_v2.py",
                "--dataset-dir",
                str(tmp_path / "does_not_need_to_exist"),
                "--output-dir",
                str(output_dir),
            ],
        )

        with pytest.raises(SystemExit):
            gen_v2.main()

        assert not (output_dir / "development_annotations_v2.csv").exists()
        assert (output_dir / "validation_annotations_v2.csv").read_text() == "existing"
