"""src/safety/fall_model_matching.py 테스트."""

from __future__ import annotations

import pytest

from src.common.types import Track
from src.safety.auxiliary_fall_model import FallDetection
from src.safety.fall_model_matching import (
    FallModelEvidence,
    compute_iou,
    match_detections_to_tracks,
)


def _track(track_id: int, bbox) -> Track:
    return Track(
        track_id=track_id,
        bbox=list(bbox),
        foot_point=[(bbox[0] + bbox[2]) / 2.0, bbox[3]],
        confidence=0.9,
    )


class TestComputeIou:
    def test_identical_boxes_have_iou_one(self):
        assert compute_iou([0, 0, 10, 10], [0, 0, 10, 10]) == 1.0

    def test_non_overlapping_boxes_have_iou_zero(self):
        assert compute_iou([0, 0, 10, 10], [20, 20, 30, 30]) == 0.0

    def test_partial_overlap(self):
        # box A: 0,0-10,10 (area 100); box B: 5,5-15,15 (area 100)
        # intersection: 5,5-10,10 (area 25); union: 100+100-25=175
        iou = compute_iou([0, 0, 10, 10], [5, 5, 15, 15])
        assert abs(iou - (25 / 175)) < 1e-9


class TestMatchDetectionsToTracks:
    def test_single_track_single_detection_matches(self):
        tracks = [_track(1, [0, 0, 10, 10])]
        detections = [FallDetection(bbox=[0, 0, 10, 10], label="fall", confidence=0.9)]

        evidence = match_detections_to_tracks(tracks, detections, iou_threshold=0.3)

        assert evidence == [FallModelEvidence(track_id=1, label="fall", confidence=0.9, iou=1.0)]

    def test_no_detection_overlapping_track_is_unknown(self):
        tracks = [_track(1, [0, 0, 10, 10])]
        detections = [FallDetection(bbox=[100, 100, 110, 110], label="fall", confidence=0.9)]

        evidence = match_detections_to_tracks(tracks, detections, iou_threshold=0.3)

        assert evidence == [
            FallModelEvidence(track_id=1, label="unknown", confidence=None, iou=None)
        ]

    def test_below_threshold_iou_is_unknown_not_nofall(self):
        """겹침이 임계값보다 낮으면 unknown이어야 한다 — nofall로 잘못 취급하면 안 된다."""
        tracks = [_track(1, [0, 0, 10, 10])]
        # 아주 살짝만 겹침 (낮은 IoU)
        detections = [FallDetection(bbox=[9, 9, 20, 20], label="nofall", confidence=0.9)]

        evidence = match_detections_to_tracks(tracks, detections, iou_threshold=0.5)

        assert evidence[0].label == "unknown"

    def test_no_tracks_returns_empty_list(self):
        detections = [FallDetection(bbox=[0, 0, 10, 10], label="fall", confidence=0.9)]

        assert match_detections_to_tracks([], detections, iou_threshold=0.3) == []

    def test_no_detections_all_tracks_unknown(self):
        tracks = [_track(1, [0, 0, 10, 10]), _track(2, [20, 20, 30, 30])]

        evidence = match_detections_to_tracks(tracks, [], iou_threshold=0.3)

        assert [e.label for e in evidence] == ["unknown", "unknown"]

    def test_one_detection_never_matched_to_two_tracks(self):
        """한 detection이 여러 Track에 중복 연결되면 안 된다."""
        tracks = [_track(1, [0, 0, 10, 10]), _track(2, [1, 1, 11, 11])]  # 서로 많이 겹치는 두 Track
        detections = [FallDetection(bbox=[0, 0, 10, 10], label="fall", confidence=0.9)]

        evidence = match_detections_to_tracks(tracks, detections, iou_threshold=0.3)

        matched = [e for e in evidence if e.label != "unknown"]
        assert len(matched) == 1  # 둘 중 하나만 매칭

    def test_higher_iou_wins_when_detection_could_match_multiple_tracks(self):
        tracks = [
            _track(1, [0, 0, 10, 10]),  # detection과 완전히 겹침 (IoU=1.0)
            _track(2, [5, 5, 20, 20]),  # detection과 일부만 겹침
        ]
        detections = [FallDetection(bbox=[0, 0, 10, 10], label="fall", confidence=0.9)]

        evidence = match_detections_to_tracks(tracks, detections, iou_threshold=0.1)

        by_id = {e.track_id: e for e in evidence}
        assert by_id[1].label == "fall"
        assert by_id[2].label == "unknown"

    def test_multiple_tracks_each_matched_to_distinct_detection(self):
        tracks = [_track(1, [0, 0, 10, 10]), _track(2, [100, 100, 110, 110])]
        detections = [
            FallDetection(bbox=[0, 0, 10, 10], label="fall", confidence=0.9),
            FallDetection(bbox=[100, 100, 110, 110], label="nofall", confidence=0.8),
        ]

        evidence = match_detections_to_tracks(tracks, detections, iou_threshold=0.3)

        by_id = {e.track_id: e for e in evidence}
        assert by_id[1].label == "fall"
        assert by_id[2].label == "nofall"

    def test_returns_one_evidence_per_track_same_order(self):
        tracks = [_track(3, [0, 0, 10, 10]), _track(7, [50, 50, 60, 60])]

        evidence = match_detections_to_tracks(tracks, [], iou_threshold=0.3)

        assert [e.track_id for e in evidence] == [3, 7]

    def test_zero_iou_threshold_rejected(self):
        """0을 허용하면 전혀 겹치지 않는 bbox도 매칭 후보가 되므로 막아야 한다."""
        with pytest.raises(ValueError, match="iou_threshold"):
            match_detections_to_tracks([], [], iou_threshold=0.0)

    def test_negative_or_above_one_iou_threshold_rejected(self):
        with pytest.raises(ValueError, match="iou_threshold"):
            match_detections_to_tracks([], [], iou_threshold=-0.1)
        with pytest.raises(ValueError, match="iou_threshold"):
            match_detections_to_tracks([], [], iou_threshold=1.1)

    def test_tie_break_prefers_higher_confidence_detection(self):
        """같은 위치에 fall/nofall detection이 겹쳐 있으면(IoU 동일) confidence가

        높은 쪽이 선택돼야 한다 — 입력 순서에 의존하면 안 된다.
        """
        tracks = [_track(1, [0, 0, 10, 10])]
        # 두 detection이 Track과 정확히 같은 bbox라 IoU가 동일(1.0)
        detections = [
            FallDetection(bbox=[0, 0, 10, 10], label="nofall", confidence=0.4),
            FallDetection(bbox=[0, 0, 10, 10], label="fall", confidence=0.9),
        ]

        evidence = match_detections_to_tracks(tracks, detections, iou_threshold=0.3)

        assert evidence[0].label == "fall"
        assert evidence[0].confidence == 0.9
