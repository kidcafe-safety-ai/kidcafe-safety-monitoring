"""Phase 4 직접 촬영 E1 frame 생성 테스트."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from src.common.types import Track

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import fall_signal_cache as signal_cache  # noqa: E402
import materialize_phase4_recorded_e1_frames as materializer  # noqa: E402


def _track(track_id: int = 1) -> Track:
    return Track(
        track_id=track_id,
        bbox=[10.0, 20.0, 50.0, 80.0],
        foot_point=[30.0, 80.0],
        confidence=0.9,
    )


def _frames(count: int = 10) -> list[signal_cache.CachedFrame]:
    return [
        signal_cache.CachedFrame(
            frame_number=index,
            timestamp=f"00:00:00.{index * 100:03d}",
            tracks=[_track()],
            raw_detections=[],
        )
        for index in range(count)
    ]


def _manifest(
    video_id: str = "P4_S01_A01_fall_side_01_cam01",
    actor_ids: str = "A01",
    split_role: str = "diagnostic",
) -> dict:
    return {
        "video_id": video_id,
        "primary_actor_id": "A01",
        "actor_ids": actor_ids,
        "scenario_type": "fall_side",
        "label": "fall",
        "fps": "10.0",
        "frame_count": "10",
        "split_role": split_role,
    }


def test_selects_pre_fall_nofall_and_post_onset_fall_frames():
    selected, skipped = materializer.select_video_frames(
        _manifest(),
        {"fall_start_frame": "4", "lying_start_frame": "6"},
        _frames(),
        sample_fps=5.0,
        pre_fall_nofall_sec=0.2,
        post_lying_fall_sec=0.1,
    )

    assert skipped == 0
    assert [(item.frame_number, item.class_id) for item in selected] == [
        (2, 0),
        (3, 0),
        (4, 1),
        (6, 1),
        (7, 1),
    ]


def test_selects_only_a01_single_actor_diagnostic():
    rows = [
        _manifest(),
        _manifest("P4_S01_A01_contact_fall_01_cam01", "A01|A02"),
        {
            **_manifest("P4_S01_A02_fall_side_01_cam01"),
            "primary_actor_id": "A02",
            "actor_ids": "A02",
        },
        _manifest("P4_S01_A01_fall_side_02_cam01", split_role="test"),
    ]

    selected, excluded = materializer.select_training_manifests(rows, ("A01",))

    assert [row["video_id"] for row in selected] == [
        "P4_S01_A01_fall_side_01_cam01"
    ]
    assert excluded == ["P4_S01_A01_contact_fall_01_cam01"]


def test_yolo_label_clips_bbox_to_image():
    label = materializer._yolo_label(1, [-10.0, 10.0, 110.0, 90.0], 100, 100)

    assert label == "1 0.50000000 0.50000000 1.00000000 0.80000000\n"


def test_rejects_training_actor_other_than_a01():
    with pytest.raises(materializer.RecordedE1FrameError, match="A01"):
        materializer._parse_actors("A02")
