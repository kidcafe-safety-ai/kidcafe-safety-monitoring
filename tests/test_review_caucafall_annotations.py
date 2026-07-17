"""scripts/review_caucafall_annotations.py 테스트.

ReviewSession(상태 관리 로직)만 검증한다. run_interactive()의 실제
cv2.imshow/waitKey 루프는 디스플레이가 있는 환경에서 직접 실행해 확인해야
한다.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import review_caucafall_annotations as rev  # noqa: E402

_COLUMNS = [
    "video_id",
    "label",
    "video_path",
    "fall_start_frame",
    "impact_frame",
    "lying_start_frame",
    "review_status",
]


_TEST_VIDEO_FRAMES = {}


class _FakeVideoCapture:
    """CI 코덱에 의존하지 않고 ReviewSession의 순차 디코딩 경로를 검증한다."""

    def __init__(self, path: str) -> None:
        self._frames = _TEST_VIDEO_FRAMES.get(str(Path(path).resolve()))
        self._next_frame_index = 0
        self._released = False

    def isOpened(self) -> bool:
        return self._frames is not None and not self._released

    def read(self):
        if not self.isOpened() or self._next_frame_index >= len(self._frames):
            return False, None
        frame = self._frames[self._next_frame_index].copy()
        self._next_frame_index += 1
        return True, frame

    def release(self) -> None:
        self._released = True


@pytest.fixture(autouse=True)
def _fake_video_capture(monkeypatch):
    """OpenCV/FFmpeg 설치 상태와 무관하게 테스트 영상을 읽도록 고정한다."""
    _TEST_VIDEO_FRAMES.clear()
    monkeypatch.setattr(rev.cv2, "VideoCapture", _FakeVideoCapture)


def _write_avi(path: Path, frame_count: int) -> None:
    """테스트용 AVI 경로와 메모리 프레임을 함께 준비한다.

    실제 AVI 인코딩은 macOS와 GitHub Actions Ubuntu의 코덱 지원 차이로
    테스트를 불안정하게 만든다. 운영 GUI의 실제 AVI 재생은 수동 E2E로 확인하고,
    여기서는 ReviewSession의 프레임 탐색과 상태 관리만 검증한다.
    """
    path.write_bytes(b"test-video")
    _TEST_VIDEO_FRAMES[str(path.resolve())] = [
        np.full((32, 32, 3), frame_index, dtype=np.uint8)
        for frame_index in range(frame_count)
    ]


def _write_frame_labels_and_images(folder: Path, classes: list) -> None:
    for i, cls in enumerate(classes, start=1):
        name = f"cas1{i:05d}"
        (folder / f"{name}.txt").write_text(f"{cls} 0.5 0.5 0.2 0.4\n")
        cv2.imwrite(str(folder / f"{name}.png"), np.full((32, 32, 3), i % 255, dtype=np.uint8))
    (folder / "classes.txt").write_text("nofall\nfall\n")


def _make_activity_folder(
    root: Path, subject_dir_name: str, activity: str, avi_frames, classes
) -> Path:
    folder = root / subject_dir_name / activity
    folder.mkdir(parents=True)
    video_stem = "".join(part.capitalize() for part in activity.split())
    _write_avi(folder / f"{video_stem}.avi", avi_frames)
    _write_frame_labels_and_images(folder, classes)
    return folder


def _write_annotations_csv(path: Path, rows: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _fall_row(**overrides) -> dict:
    defaults = {
        "video_id": "S1_fall_backwards",
        "label": "fall",
        "video_path": "Subject.1/Fall backwards/FallBackwards.avi",
        "fall_start_frame": "3",
        "impact_frame": "",
        "lying_start_frame": "",
        "review_status": "pending",
    }
    defaults.update(overrides)
    return defaults


class TestReviewSessionLoadAndBasics:
    def test_loads_rows_from_csv(self, tmp_path):
        _make_activity_folder(
            tmp_path / "videos", "Subject.1", "Fall backwards", 5, ["0", "0", "0", "1", "1"]
        )
        csv_path = tmp_path / "annotations.csv"
        _write_annotations_csv(csv_path, [_fall_row()])

        session = rev.ReviewSession(csv_path, tmp_path / "videos")

        assert session.current.video_id == "S1_fall_backwards"
        assert session.current.fall_start_frame == 3

    def test_raises_on_empty_csv(self, tmp_path):
        csv_path = tmp_path / "annotations.csv"
        _write_annotations_csv(csv_path, [])

        with pytest.raises(ValueError):
            rev.ReviewSession(csv_path, tmp_path / "videos")


class TestFrameNavigationAndClamping:
    def test_default_start_frame_applies_margin_before_candidate(self, tmp_path):
        _make_activity_folder(
            tmp_path / "videos",
            "Subject.1",
            "Fall backwards",
            30,
            ["0"] * 20 + ["1"] * 10,
        )
        csv_path = tmp_path / "annotations.csv"
        _write_annotations_csv(csv_path, [_fall_row(fall_start_frame="20")])
        session = rev.ReviewSession(csv_path, tmp_path / "videos", margin=15)

        assert session.default_start_frame() == 5  # 20 - 15

    def test_default_start_frame_clamped_to_zero_when_margin_exceeds_candidate(self, tmp_path):
        _make_activity_folder(
            tmp_path / "videos", "Subject.1", "Fall backwards", 10, ["0"] * 5 + ["1"] * 5
        )
        csv_path = tmp_path / "annotations.csv"
        _write_annotations_csv(csv_path, [_fall_row(fall_start_frame="3")])
        session = rev.ReviewSession(csv_path, tmp_path / "videos", margin=15)

        assert session.default_start_frame() == 0

    def test_clamp_frame_never_exceeds_last_frame(self, tmp_path):
        _make_activity_folder(
            tmp_path / "videos", "Subject.1", "Fall backwards", 5, ["0", "0", "0", "1", "1"]
        )
        csv_path = tmp_path / "annotations.csv"
        _write_annotations_csv(csv_path, [_fall_row()])
        session = rev.ReviewSession(csv_path, tmp_path / "videos")

        assert session.clamp_frame(999) == 4  # frame_count(5) - 1
        assert session.clamp_frame(-5) == 0

    def test_set_frame_fields_are_clamped(self, tmp_path):
        _make_activity_folder(
            tmp_path / "videos", "Subject.1", "Fall backwards", 5, ["0", "0", "0", "1", "1"]
        )
        csv_path = tmp_path / "annotations.csv"
        _write_annotations_csv(csv_path, [_fall_row()])
        session = rev.ReviewSession(csv_path, tmp_path / "videos")

        session.set_fall_start_frame(999)
        session.set_impact_frame(-1)
        session.set_lying_start_frame(2)

        assert session.current.fall_start_frame == 4
        assert session.current.impact_frame == 0
        assert session.current.lying_start_frame == 2


class TestFrameLabelMapping:
    def test_frame_class_at_matches_txt_content(self, tmp_path):
        _make_activity_folder(
            tmp_path / "videos",
            "Subject.1",
            "Fall backwards",
            5,
            ["0", "0", "0", "1", "1"],
        )
        csv_path = tmp_path / "annotations.csv"
        _write_annotations_csv(csv_path, [_fall_row()])
        session = rev.ReviewSession(csv_path, tmp_path / "videos")

        assert session.frame_class_at(0) == "0"
        assert session.frame_class_at(3) == "1"
        assert session.frame_class_at(4) == "1"

    def test_frame_class_at_respects_avi_frame_count_trim(self, tmp_path):
        """txt가 AVI보다 많으면(흔한 +1 패턴) 초과분은 매핑에서 제외되어야 한다."""
        _make_activity_folder(
            tmp_path / "videos",
            "Subject.1",
            "Fall backwards",
            4,  # AVI는 4프레임
            ["0", "0", "1", "1", "1"],  # txt는 5개 (뒤에서 1개 제외되어야 함)
        )
        csv_path = tmp_path / "annotations.csv"
        _write_annotations_csv(csv_path, [_fall_row()])
        session = rev.ReviewSession(csv_path, tmp_path / "videos")

        assert session.frame_count() == 4
        assert session.frame_class_at(3) == "1"
        assert session.frame_class_at(4) is None  # 범위 밖(제외된 5번째 txt)

    def test_png_frame_at_returns_none_out_of_range(self, tmp_path):
        _make_activity_folder(
            tmp_path / "videos", "Subject.1", "Fall backwards", 3, ["0", "0", "1"]
        )
        csv_path = tmp_path / "annotations.csv"
        _write_annotations_csv(csv_path, [_fall_row()])
        session = rev.ReviewSession(csv_path, tmp_path / "videos")

        assert session.png_frame_at(0) is not None
        assert session.png_frame_at(999) is None


class TestAviFrameAt:
    def test_sequential_forward_decoding(self, tmp_path):
        _make_activity_folder(
            tmp_path / "videos", "Subject.1", "Fall backwards", 5, ["0", "0", "0", "1", "1"]
        )
        csv_path = tmp_path / "annotations.csv"
        _write_annotations_csv(csv_path, [_fall_row()])
        session = rev.ReviewSession(csv_path, tmp_path / "videos")

        assert session.avi_frame_at(0) is not None
        assert session.avi_frame_at(2) is not None
        assert session.avi_frame_at(4) is not None

    def test_backward_seek_reopens_and_redecodes(self, tmp_path):
        """뒤로 이동해도(예: 4 -> 1) 프레임을 정상적으로 다시 읽어야 한다.

        임의 seek(CAP_PROP_POS_FRAMES) 대신 처음부터 순차 디코딩으로 구현했으므로,
        뒤로 갔다가 다시 앞으로 가도 동일 프레임을 안정적으로 반환해야 한다.
        """
        _make_activity_folder(
            tmp_path / "videos", "Subject.1", "Fall backwards", 5, ["0", "0", "0", "1", "1"]
        )
        csv_path = tmp_path / "annotations.csv"
        _write_annotations_csv(csv_path, [_fall_row()])
        session = rev.ReviewSession(csv_path, tmp_path / "videos")

        session.avi_frame_at(4)
        frame_at_1_after_backward = session.avi_frame_at(1)
        assert frame_at_1_after_backward is not None
        assert frame_at_1_after_backward.shape == (32, 32, 3)

    def test_out_of_range_returns_none(self, tmp_path):
        _make_activity_folder(
            tmp_path / "videos", "Subject.1", "Fall backwards", 3, ["0", "0", "1"]
        )
        csv_path = tmp_path / "annotations.csv"
        _write_annotations_csv(csv_path, [_fall_row()])
        session = rev.ReviewSession(csv_path, tmp_path / "videos")

        assert session.avi_frame_at(999) is None

    def test_requesting_same_frame_twice_returns_image_both_times(self, tmp_path):
        """이동 없이 R/U만 눌러 같은 프레임을 다시 요청해도(디코딩 루프가 안

        돌아도) None이 아니라 마지막으로 디코딩한 프레임을 반환해야 한다.
        """
        _make_activity_folder(
            tmp_path / "videos", "Subject.1", "Fall backwards", 5, ["0", "0", "0", "1", "1"]
        )
        csv_path = tmp_path / "annotations.csv"
        _write_annotations_csv(csv_path, [_fall_row()])
        session = rev.ReviewSession(csv_path, tmp_path / "videos")

        first = session.avi_frame_at(2)
        second = session.avi_frame_at(2)

        assert first is not None
        assert second is not None
        assert first.shape == second.shape == (32, 32, 3)


class TestReviewStatusTransitions:
    def test_mark_reviewed_and_needs_review(self, tmp_path):
        _make_activity_folder(
            tmp_path / "videos", "Subject.1", "Fall backwards", 3, ["0", "0", "1"]
        )
        csv_path = tmp_path / "annotations.csv"
        _write_annotations_csv(csv_path, [_fall_row()])
        session = rev.ReviewSession(csv_path, tmp_path / "videos")

        session.mark_reviewed()
        assert session.current.review_status == "reviewed"

        session.mark_needs_review()
        assert session.current.review_status == "needs_review"

    def test_mark_reviewed_rejects_out_of_order_frames(self, tmp_path):
        _make_activity_folder(
            tmp_path / "videos", "Subject.1", "Fall backwards", 10, ["0"] * 5 + ["1"] * 5
        )
        csv_path = tmp_path / "annotations.csv"
        _write_annotations_csv(csv_path, [_fall_row(fall_start_frame="7")])
        session = rev.ReviewSession(csv_path, tmp_path / "videos")

        session.set_impact_frame(6)  # fall_start_frame(7)보다 앞이라 순서 위반
        session.set_lying_start_frame(5)

        with pytest.raises(ValueError, match="impact_frame"):
            session.mark_reviewed()
        assert session.current.review_status == "pending"  # 검증 실패 시 상태 변경 안 됨

    def test_mark_reviewed_allows_partial_values(self, tmp_path):
        """impact_frame/lying_start_frame이 비어 있으면 순서 검증에서 그냥 건너뛴다."""
        _make_activity_folder(
            tmp_path / "videos", "Subject.1", "Fall backwards", 3, ["0", "0", "1"]
        )
        csv_path = tmp_path / "annotations.csv"
        _write_annotations_csv(csv_path, [_fall_row()])
        session = rev.ReviewSession(csv_path, tmp_path / "videos")

        session.mark_reviewed()  # impact/lying 없이도 통과해야 함
        assert session.current.review_status == "reviewed"


class TestAutoReviewNoFall:
    def test_marks_clean_no_fall_rows_as_reviewed(self, tmp_path):
        _make_activity_folder(
            tmp_path / "videos", "Subject.1", "Fall backwards", 3, ["0", "0", "1"]
        )
        _make_activity_folder(tmp_path / "videos", "Subject.1", "Walk", 4, ["0"] * 4)
        _make_activity_folder(tmp_path / "videos", "Subject.1", "Hop", 4, ["0"] * 4)
        csv_path = tmp_path / "annotations.csv"
        _write_annotations_csv(
            csv_path,
            [
                _fall_row(video_id="v1", video_path="Subject.1/Fall backwards/FallBackwards.avi"),
                _fall_row(
                    video_id="v2",
                    label="no_fall",
                    video_path="Subject.1/Walk/Walk.avi",
                    fall_start_frame="",
                ),
                _fall_row(
                    video_id="v3",
                    label="no_fall",
                    video_path="Subject.1/Hop/Hop.avi",
                    fall_start_frame="",
                ),
            ],
        )
        session = rev.ReviewSession(csv_path, tmp_path / "videos")

        flagged = session.auto_review_no_fall()

        assert flagged == []
        by_id = {row.video_id: row for row in session.all_rows}
        assert by_id["v2"].review_status == "reviewed"
        assert by_id["v3"].review_status == "reviewed"
        assert by_id["v1"].review_status == "pending"  # fall 행은 건드리지 않음

    def test_flags_no_fall_row_containing_class_1_instead_of_marking_reviewed(self, tmp_path):
        """정상적으로는 없어야 하지만, class=1이 섞여 있으면 자동으로 reviewed 처리하면 안 된다."""
        _make_activity_folder(
            tmp_path / "videos", "Subject.1", "Walk", 4, ["0", "0", "1", "0"]
        )
        csv_path = tmp_path / "annotations.csv"
        _write_annotations_csv(
            csv_path,
            [
                _fall_row(
                    video_id="v1",
                    label="no_fall",
                    video_path="Subject.1/Walk/Walk.avi",
                    fall_start_frame="",
                )
            ],
        )
        session = rev.ReviewSession(csv_path, tmp_path / "videos")

        flagged = session.auto_review_no_fall()

        assert flagged == ["v1"]
        assert session.all_rows[0].review_status == "needs_review"

    def test_blocks_approval_when_avi_has_zero_frames(self, tmp_path):
        """all([])==True인 파이썬 특성 때문에, AVI를 못 읽어 frame_count=0이면

        classes도 빈 리스트가 되어 예전 구현은 잘못 reviewed 처리했다.
        """
        folder = tmp_path / "videos" / "Subject.1" / "Walk"
        folder.mkdir(parents=True)
        _write_avi(folder / "Walk.avi", frame_count=0)  # 프레임 0개
        _write_frame_labels_and_images(folder, ["0", "0", "0"])  # txt는 있어도 AVI가 비어 있음
        csv_path = tmp_path / "annotations.csv"
        _write_annotations_csv(
            csv_path,
            [
                _fall_row(
                    video_id="v1",
                    label="no_fall",
                    video_path="Subject.1/Walk/Walk.avi",
                    fall_start_frame="",
                )
            ],
        )
        session = rev.ReviewSession(csv_path, tmp_path / "videos")

        flagged = session.auto_review_no_fall()

        assert flagged == ["v1"]
        assert session.all_rows[0].review_status == "needs_review"

    def test_blocks_approval_when_txt_count_is_fewer_than_avi_frames(self, tmp_path):
        folder = tmp_path / "videos" / "Subject.1" / "Walk"
        folder.mkdir(parents=True)
        _write_avi(folder / "Walk.avi", frame_count=5)
        _write_frame_labels_and_images(folder, ["0", "0", "0"])  # txt 3개 < AVI 5프레임
        csv_path = tmp_path / "annotations.csv"
        _write_annotations_csv(
            csv_path,
            [
                _fall_row(
                    video_id="v1",
                    label="no_fall",
                    video_path="Subject.1/Walk/Walk.avi",
                    fall_start_frame="",
                )
            ],
        )
        session = rev.ReviewSession(csv_path, tmp_path / "videos")

        flagged = session.auto_review_no_fall()

        assert flagged == ["v1"]
        assert session.all_rows[0].review_status == "needs_review"

    def test_does_not_overwrite_existing_needs_review(self, tmp_path):
        """이미 사람이(또는 이전 실행이) needs_review로 표시한 행은, 프레임 자체는

        깨끗해도 자동으로 reviewed로 되돌리면 안 된다.
        """
        _make_activity_folder(tmp_path / "videos", "Subject.1", "Walk", 3, ["0", "0", "0"])
        csv_path = tmp_path / "annotations.csv"
        _write_annotations_csv(
            csv_path,
            [
                _fall_row(
                    video_id="v1",
                    label="no_fall",
                    video_path="Subject.1/Walk/Walk.avi",
                    fall_start_frame="",
                    review_status="needs_review",
                )
            ],
        )
        session = rev.ReviewSession(csv_path, tmp_path / "videos")

        flagged = session.auto_review_no_fall()

        assert flagged == ["v1"]
        assert session.all_rows[0].review_status == "needs_review"

    def test_blocks_approval_when_no_fall_row_has_leftover_fall_frame_fields(self, tmp_path):
        """no_fall 행에 fall_start_frame 등이 남아 있으면(데이터 이상) 승인하지 않는다."""
        _make_activity_folder(tmp_path / "videos", "Subject.1", "Walk", 3, ["0", "0", "0"])
        csv_path = tmp_path / "annotations.csv"
        _write_annotations_csv(
            csv_path,
            [
                _fall_row(
                    video_id="v1",
                    label="no_fall",
                    video_path="Subject.1/Walk/Walk.avi",
                    fall_start_frame="1",  # no_fall인데 남아있음 (이상 상태)
                )
            ],
        )
        session = rev.ReviewSession(csv_path, tmp_path / "videos")

        flagged = session.auto_review_no_fall()

        assert flagged == ["v1"]
        assert session.all_rows[0].review_status == "needs_review"

    def test_save_after_auto_review_persists_all_rows(self, tmp_path):
        _make_activity_folder(tmp_path / "videos", "Subject.1", "Walk", 3, ["0", "0", "0"])
        csv_path = tmp_path / "annotations.csv"
        _write_annotations_csv(
            csv_path,
            [
                _fall_row(
                    video_id="v1",
                    label="no_fall",
                    video_path="Subject.1/Walk/Walk.avi",
                    fall_start_frame="",
                )
            ],
        )
        session = rev.ReviewSession(csv_path, tmp_path / "videos")

        session.auto_review_no_fall()
        session.save()

        reloaded = rev.load_annotations(str(csv_path), include_unreviewed=True)
        assert reloaded[0].review_status == "reviewed"


class TestVideoNavigation:
    def test_next_and_prev_video_move_index(self, tmp_path):
        _make_activity_folder(
            tmp_path / "videos", "Subject.1", "Fall backwards", 3, ["0", "0", "1"]
        )
        _make_activity_folder(tmp_path / "videos", "Subject.1", "Walk", 3, ["0", "0", "0"])
        csv_path = tmp_path / "annotations.csv"
        _write_annotations_csv(
            csv_path,
            [
                _fall_row(video_id="v1", video_path="Subject.1/Fall backwards/FallBackwards.avi"),
                _fall_row(
                    video_id="v2",
                    label="no_fall",
                    video_path="Subject.1/Walk/Walk.avi",
                    fall_start_frame="",
                ),
            ],
        )
        session = rev.ReviewSession(csv_path, tmp_path / "videos")

        assert session.current.video_id == "v1"
        assert session.go_next_video() is True
        assert session.current.video_id == "v2"
        assert session.go_next_video() is False  # 마지막 영상에서는 더 못 감

        assert session.go_prev_video() is True
        assert session.current.video_id == "v1"
        assert session.go_prev_video() is False  # 첫 영상에서는 더 못 감


class TestSafeSave:
    def test_save_writes_columns_in_fixed_order(self, tmp_path):
        """evaluate_fall._REQUIRED_COLUMNS는 컬럼 존재 확인용 set이라 순서가

        보장되지 않는다. CSV 헤더는 항상 evaluate_fall.py 계약과 동일한
        고정 순서여야 한다.
        """
        _make_activity_folder(
            tmp_path / "videos", "Subject.1", "Fall backwards", 5, ["0", "0", "0", "1", "1"]
        )
        csv_path = tmp_path / "annotations.csv"
        _write_annotations_csv(csv_path, [_fall_row()])
        session = rev.ReviewSession(csv_path, tmp_path / "videos")

        session.save()

        assert csv_path.read_text().splitlines()[0] == (
            "video_id,label,video_path,fall_start_frame,"
            "impact_frame,lying_start_frame,review_status"
        )

    def test_save_uses_temp_file_then_replaces_original(self, tmp_path):
        _make_activity_folder(
            tmp_path / "videos", "Subject.1", "Fall backwards", 5, ["0", "0", "0", "1", "1"]
        )
        csv_path = tmp_path / "annotations.csv"
        _write_annotations_csv(csv_path, [_fall_row()])
        session = rev.ReviewSession(csv_path, tmp_path / "videos")

        session.set_fall_start_frame(2)
        session.mark_reviewed()
        session.save()

        tmp_file = csv_path.with_suffix(".csv.tmp")
        assert not tmp_file.exists()  # 저장 후에는 임시 파일이 남아있으면 안 됨

        reloaded = rev.load_annotations(str(csv_path), include_unreviewed=True)
        assert reloaded[0].fall_start_frame == 2
        assert reloaded[0].review_status == "reviewed"

    def test_save_rejects_invalid_review_status_without_touching_original(self, tmp_path):
        _make_activity_folder(
            tmp_path / "videos", "Subject.1", "Fall backwards", 3, ["0", "0", "1"]
        )
        csv_path = tmp_path / "annotations.csv"
        _write_annotations_csv(csv_path, [_fall_row()])
        original_content = csv_path.read_text()
        session = rev.ReviewSession(csv_path, tmp_path / "videos")
        session.current.review_status = "not_a_real_status"

        with pytest.raises(ValueError):
            session.save()

        assert csv_path.read_text() == original_content  # 원본 훼손되지 않음
        assert not csv_path.with_suffix(".csv.tmp").exists()

    def test_reload_preserves_completed_reviews_after_partial_session(self, tmp_path):
        """중간에 세션이 끝나도 이미 저장된 reviewed 행은 보존돼야 한다."""
        _make_activity_folder(
            tmp_path / "videos", "Subject.1", "Fall backwards", 3, ["0", "0", "1"]
        )
        _make_activity_folder(tmp_path / "videos", "Subject.1", "Walk", 3, ["0", "0", "0"])
        csv_path = tmp_path / "annotations.csv"
        _write_annotations_csv(
            csv_path,
            [
                _fall_row(video_id="v1", video_path="Subject.1/Fall backwards/FallBackwards.avi"),
                _fall_row(
                    video_id="v2",
                    label="no_fall",
                    video_path="Subject.1/Walk/Walk.avi",
                    fall_start_frame="",
                    review_status="reviewed",
                ),
            ],
        )

        session = rev.ReviewSession(csv_path, tmp_path / "videos")
        session.mark_reviewed()  # v1만 검수
        session.save()

        reloaded = rev.load_annotations(str(csv_path), include_unreviewed=True)
        assert reloaded[0].review_status == "reviewed"
        assert reloaded[1].review_status == "reviewed"  # 기존 v2도 그대로 유지


class TestOriginalFilesUntouched:
    def test_avi_and_txt_are_not_modified_by_review(self, tmp_path):
        folder = _make_activity_folder(
            tmp_path / "videos", "Subject.1", "Fall backwards", 3, ["0", "0", "1"]
        )
        avi_path = next(folder.glob("*.avi"))
        txt_path = sorted(folder.glob("*.txt"))[0]
        avi_before = avi_path.read_bytes()
        txt_before = txt_path.read_text()

        csv_path = tmp_path / "annotations.csv"
        _write_annotations_csv(csv_path, [_fall_row()])
        session = rev.ReviewSession(csv_path, tmp_path / "videos")
        session.set_fall_start_frame(1)
        session.set_impact_frame(2)
        session.mark_reviewed()
        session.save()

        assert avi_path.read_bytes() == avi_before
        assert txt_path.read_text() == txt_before


class TestHoldoutGuard:
    def test_rejects_videos_dir_pointing_into_holdout(self, tmp_path):
        holdout_dir = tmp_path / "holdout"
        holdout_dir.mkdir()

        with pytest.raises(SystemExit):
            rev.guard_holdout(holdout_dir)

    def test_allows_normal_videos_dir(self, tmp_path):
        development_dir = tmp_path / "development"
        development_dir.mkdir()
        rev.guard_holdout(development_dir)  # 예외 없이 통과


class TestGuardVideoPath:
    def test_rejects_holdout_segment_in_video_path(self, tmp_path):
        videos_dir = tmp_path / "development"
        holdout_video = tmp_path / "holdout" / "v1.avi"

        with pytest.raises(SystemExit):
            rev.guard_video_path(holdout_video, videos_dir)

    def test_rejects_path_outside_videos_dir(self, tmp_path):
        """videos_dir 자체나 CSV의 video_path에 holdout이 없어도, videos_dir 밖을

        가리키면(예: 상대경로 탈출) 차단해야 한다.
        """
        videos_dir = tmp_path / "development"
        videos_dir.mkdir()
        outside_path = tmp_path / "elsewhere" / "v1.avi"

        with pytest.raises(SystemExit):
            rev.guard_video_path(outside_path, videos_dir)

    def test_allows_path_inside_videos_dir(self, tmp_path):
        videos_dir = tmp_path / "development"
        videos_dir.mkdir()
        inside_path = (videos_dir / "Subject.1" / "Walk" / "Walk.avi").resolve()

        rev.guard_video_path(inside_path, videos_dir)  # 예외 없이 통과

    def test_review_session_init_blocks_holdout_video_path_even_if_videos_dir_is_clean(
        self, tmp_path
    ):
        """--videos-dir 자체는 holdout이 아니어도, annotation 행이 holdout 절대경로를

        가리키면 ReviewSession 생성 시점에 막아야 한다 (evaluate_fall.py의
        symlink/절대경로 우회 방지와 동일한 원칙).
        """
        development_dir = tmp_path / "development"
        development_dir.mkdir()
        holdout_video = tmp_path / "holdout" / "v1.avi"

        csv_path = tmp_path / "annotations.csv"
        _write_annotations_csv(csv_path, [_fall_row(video_path=str(holdout_video))])

        with pytest.raises(SystemExit):
            rev.ReviewSession(csv_path, development_dir)


class TestFiltering:
    def test_label_filter_only_includes_matching_rows(self, tmp_path):
        _make_activity_folder(
            tmp_path / "videos", "Subject.1", "Fall backwards", 3, ["0", "0", "1"]
        )
        _make_activity_folder(tmp_path / "videos", "Subject.1", "Walk", 3, ["0", "0", "0"])
        csv_path = tmp_path / "annotations.csv"
        _write_annotations_csv(
            csv_path,
            [
                _fall_row(video_id="v1", video_path="Subject.1/Fall backwards/FallBackwards.avi"),
                _fall_row(
                    video_id="v2",
                    label="no_fall",
                    video_path="Subject.1/Walk/Walk.avi",
                    fall_start_frame="",
                ),
            ],
        )

        session = rev.ReviewSession(csv_path, tmp_path / "videos", label="fall")

        assert len(session.rows) == 1
        assert session.current.video_id == "v1"

    def test_save_with_label_filter_does_not_delete_excluded_rows(self, tmp_path):
        """--label로 필터링된 세션에서 save()해도 필터에서 제외된 행이 CSV에서

        사라지면 안 된다 (실제로 60행 -> 30행으로 줄어드는 데이터 손실 버그가
        있었다).
        """
        _make_activity_folder(
            tmp_path / "videos", "Subject.1", "Fall backwards", 3, ["0", "0", "1"]
        )
        _make_activity_folder(tmp_path / "videos", "Subject.1", "Walk", 3, ["0", "0", "0"])
        _make_activity_folder(tmp_path / "videos", "Subject.1", "Hop", 3, ["0", "0", "0"])
        csv_path = tmp_path / "annotations.csv"
        _write_annotations_csv(
            csv_path,
            [
                _fall_row(video_id="v1", video_path="Subject.1/Fall backwards/FallBackwards.avi"),
                _fall_row(
                    video_id="v2",
                    label="no_fall",
                    video_path="Subject.1/Walk/Walk.avi",
                    fall_start_frame="",
                ),
                _fall_row(
                    video_id="v3",
                    label="no_fall",
                    video_path="Subject.1/Hop/Hop.avi",
                    fall_start_frame="",
                ),
            ],
        )

        session = rev.ReviewSession(csv_path, tmp_path / "videos", label="fall")
        assert len(session.rows) == 1
        session.mark_reviewed()
        session.save()

        reloaded = rev.load_annotations(str(csv_path), include_unreviewed=True)
        assert len(reloaded) == 3  # no_fall 2개가 사라지면 안 된다
        by_id = {row.video_id: row for row in reloaded}
        assert by_id["v1"].review_status == "reviewed"
        assert by_id["v2"].review_status == "pending"  # 검수 대상이 아니었으니 그대로
        assert by_id["v3"].review_status == "pending"

    def test_video_id_jumps_to_matching_row(self, tmp_path):
        _make_activity_folder(
            tmp_path / "videos", "Subject.1", "Fall backwards", 3, ["0", "0", "1"]
        )
        _make_activity_folder(tmp_path / "videos", "Subject.1", "Walk", 3, ["0", "0", "0"])
        csv_path = tmp_path / "annotations.csv"
        _write_annotations_csv(
            csv_path,
            [
                _fall_row(video_id="v1", video_path="Subject.1/Fall backwards/FallBackwards.avi"),
                _fall_row(
                    video_id="v2",
                    label="no_fall",
                    video_path="Subject.1/Walk/Walk.avi",
                    fall_start_frame="",
                ),
            ],
        )

        session = rev.ReviewSession(csv_path, tmp_path / "videos", video_id="v2")

        assert session.current.video_id == "v2"

    def test_unknown_video_id_raises(self, tmp_path):
        _make_activity_folder(
            tmp_path / "videos", "Subject.1", "Fall backwards", 3, ["0", "0", "1"]
        )
        csv_path = tmp_path / "annotations.csv"
        _write_annotations_csv(csv_path, [_fall_row()])

        with pytest.raises(ValueError):
            rev.ReviewSession(csv_path, tmp_path / "videos", video_id="does_not_exist")
