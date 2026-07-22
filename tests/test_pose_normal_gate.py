from __future__ import annotations

from src.common.types import Track, TrackingResult
from src.safety.fall_detector import FallDetectorConfig
from src.safety.pose_normal_gate import PoseNormalGate, PoseNormalGateConfig


def _track(
    bbox=None,
    head_y=40.0,
    hip_y=120.0,
    with_pose=True,
    track_id=1,
) -> Track:
    bbox = bbox or [0.0, 0.0, 100.0, 200.0]
    keypoints = [[50.0, 80.0] for _ in range(17)]
    keypoints[0] = [50.0, head_y]
    keypoints[11] = [45.0, hip_y]
    keypoints[12] = [55.0, hip_y]
    return Track(
        track_id=track_id,
        bbox=list(bbox),
        foot_point=[(bbox[0] + bbox[2]) / 2.0, bbox[3]],
        confidence=0.9,
        keypoints=keypoints if with_pose else None,
        keypoints_conf=[0.9] * 17 if with_pose else None,
    )


def _result(frame_number, tracks) -> TrackingResult:
    return TrackingResult(
        frame_number=frame_number,
        timestamp=f"00:00:00.{frame_number:03d}",
        video_source="video",
        tracks=list(tracks),
    )


def _gate() -> PoseNormalGate:
    return PoseNormalGate(
        fps=10.0,
        config=PoseNormalGateConfig(min_track_age_sec=0.1),
    )


def test_stable_upright_track_skips_auxiliary_after_history_warmup():
    gate = _gate()

    first = gate.evaluate(_result(0, [_track()]))
    second = gate.evaluate(_result(1, [_track()]))

    assert first.use_auxiliary is True
    assert second.use_auxiliary is False


def test_downward_motion_uses_auxiliary():
    gate = _gate()
    gate.evaluate(_result(0, [_track()]))

    decision = gate.evaluate(
        _result(1, [_track(bbox=[0.0, 20.0, 100.0, 220.0])])
    )

    assert decision.use_auxiliary is True
    assert decision.descending is True


def test_fallen_pose_uses_auxiliary_even_with_vertical_bbox():
    gate = _gate()
    gate.evaluate(_result(0, [_track(head_y=150.0, hip_y=100.0)]))

    decision = gate.evaluate(
        _result(1, [_track(head_y=150.0, hip_y=100.0)])
    )

    assert decision.use_auxiliary is True
    assert decision.non_normal_posture is True


def test_missing_pose_uses_auxiliary():
    gate = _gate()
    gate.evaluate(_result(0, [_track(with_pose=False)]))

    decision = gate.evaluate(_result(1, [_track(with_pose=False)]))

    assert decision.use_auxiliary is True
    assert decision.pose_unavailable is True


def test_any_non_normal_track_forces_multi_track_fallback():
    gate = _gate()
    gate.evaluate(_result(0, [_track(track_id=1), _track(track_id=2)]))

    decision = gate.evaluate(
        _result(
            1,
            [
                _track(track_id=1),
                _track(track_id=2, head_y=150.0, hip_y=100.0),
            ],
        )
    )

    assert decision.use_auxiliary is True


def test_no_tracks_does_not_request_auxiliary():
    assert _gate().evaluate(_result(0, [])).use_auxiliary is False


def test_config_derives_shared_thresholds_from_fall_detector_config():
    config = PoseNormalGateConfig.from_fall_detector_config(
        FallDetectorConfig(
            min_track_age_sec=0.4,
            normal_aspect_ratio_threshold=0.8,
            recovery_velocity_threshold=0.25,
            pose_fallen_threshold=0.3,
            pose_min_keypoint_conf=0.4,
        )
    )

    assert config.min_track_age_sec == 0.4
    assert config.max_aspect_ratio == 0.8
    assert config.max_center_vertical_velocity == 0.25
    assert config.fallen_pose_threshold == 0.3
    assert config.min_keypoint_conf == 0.4
