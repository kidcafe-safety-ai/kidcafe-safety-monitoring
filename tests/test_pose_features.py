"""PoseFeatureExtractor 단위 테스트."""

from __future__ import annotations

import pytest

from src.common.types import Track
from src.safety.pose_features import PoseFeatureExtractor

_THRESHOLD = 0.2


def _track_with_keypoints(
    hip_y,
    nose=None,
    nose_conf=1.0,
    eyes=None,
    eyes_conf=1.0,
    ears=None,
    ears_conf=1.0,
    hip_conf=1.0,
    bbox=(0.0, 0.0, 50.0, 100.0),
    track_id=1,
):
    keypoints = [[0.0, 0.0]] * 17
    keypoints_conf = [0.0] * 17
    if nose is not None:
        keypoints[0] = list(nose)
        keypoints_conf[0] = nose_conf
    if eyes is not None:
        keypoints[1] = list(eyes)
        keypoints[2] = list(eyes)
        keypoints_conf[1] = eyes_conf
        keypoints_conf[2] = eyes_conf
    if ears is not None:
        keypoints[3] = list(ears)
        keypoints[4] = list(ears)
        keypoints_conf[3] = ears_conf
        keypoints_conf[4] = ears_conf
    keypoints[11] = [25.0, hip_y]
    keypoints[12] = [25.0, hip_y]
    keypoints_conf[11] = hip_conf
    keypoints_conf[12] = hip_conf
    return Track(
        track_id=track_id,
        bbox=list(bbox),
        foot_point=[25.0, bbox[3]],
        confidence=0.9,
        keypoints=keypoints,
        keypoints_conf=keypoints_conf,
    )


class TestPoseFeatureExtractor:
    def test_standing_posture_has_negative_diff(self):
        """머리가 엉덩이보다 위(작은 y)에 있으면 음수여야 한다."""
        track = _track_with_keypoints(hip_y=60.0, nose=(25.0, 20.0))  # height=100
        extractor = PoseFeatureExtractor()

        features = extractor.extract(track, _THRESHOLD)

        assert features is not None
        assert features.head_hip_diff_norm == pytest.approx(-0.4)  # (20-60)/100
        assert features.is_fallen_pose is False

    def test_fallen_posture_has_positive_diff(self):
        """머리가 엉덩이와 비슷하거나 아래(큰 y)면 양수에 가까워야 한다."""
        track = _track_with_keypoints(hip_y=60.0, nose=(25.0, 90.0))  # height=100

        features = PoseFeatureExtractor().extract(track, _THRESHOLD)

        assert features is not None
        assert features.head_hip_diff_norm == pytest.approx(0.3)  # (90-60)/100
        assert features.is_fallen_pose is True

    def test_falls_back_to_eyes_when_nose_confidence_low(self):
        track = _track_with_keypoints(
            hip_y=60.0, nose=(25.0, 20.0), nose_conf=0.1, eyes=(25.0, 90.0), eyes_conf=0.9
        )

        features = PoseFeatureExtractor().extract(track, _THRESHOLD, min_keypoint_conf=0.3)

        assert features is not None
        assert features.head_hip_diff_norm == pytest.approx(0.3)  # 눈 좌표 사용

    def test_falls_back_to_ears_when_nose_and_eyes_confidence_low(self):
        track = _track_with_keypoints(
            hip_y=60.0,
            nose=(25.0, 20.0),
            nose_conf=0.1,
            eyes=(25.0, 20.0),
            eyes_conf=0.1,
            ears=(25.0, 90.0),
            ears_conf=0.9,
        )

        features = PoseFeatureExtractor().extract(track, _THRESHOLD, min_keypoint_conf=0.3)

        assert features is not None
        assert features.head_hip_diff_norm == pytest.approx(0.3)  # 귀 좌표 사용

    def test_returns_none_when_no_head_keypoint_is_confident_enough(self):
        track = _track_with_keypoints(
            hip_y=60.0,
            nose=(25.0, 20.0),
            nose_conf=0.1,
            eyes=(25.0, 20.0),
            eyes_conf=0.1,
            ears=(25.0, 20.0),
            ears_conf=0.1,
        )

        assert PoseFeatureExtractor().extract(track, _THRESHOLD, min_keypoint_conf=0.3) is None

    def test_returns_none_when_keypoints_missing(self):
        track = Track(
            track_id=1, bbox=[0.0, 0.0, 50.0, 100.0], foot_point=[25.0, 100.0], confidence=0.9
        )

        assert PoseFeatureExtractor().extract(track, _THRESHOLD) is None

    def test_returns_none_when_hip_confidence_too_low(self):
        track = _track_with_keypoints(hip_y=60.0, nose=(25.0, 20.0), hip_conf=0.1)

        assert PoseFeatureExtractor().extract(track, _THRESHOLD, min_keypoint_conf=0.3) is None

    def test_threshold_boundary(self):
        track = _track_with_keypoints(hip_y=60.0, nose=(25.0, 80.0))  # diff = 0.2

        below = PoseFeatureExtractor().extract(track, fallen_pose_threshold=0.21)
        above = PoseFeatureExtractor().extract(track, fallen_pose_threshold=0.19)

        assert below.is_fallen_pose is False
        assert above.is_fallen_pose is True
