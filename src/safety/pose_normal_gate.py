"""Cheap conservative gate for skipping RGB on an obviously normal pose."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.common.types import TrackingResult
from src.safety.fall_features import FallFeatureExtractor
from src.safety.multi_track_history import MultiTrackHistory
from src.safety.pose_features import PoseFeatureExtractor

if TYPE_CHECKING:
    from src.safety.fall_detector import FallDetectorConfig


@dataclass(frozen=True)
class PoseNormalGateConfig:
    min_track_age_sec: float = 0.3
    max_aspect_ratio: float = 0.9
    max_center_vertical_velocity: float = 0.3
    max_foot_vertical_velocity: float = 0.3
    min_height_change_rate: float = -0.3
    fallen_pose_threshold: float = 0.2
    min_keypoint_conf: float = 0.3

    def __post_init__(self) -> None:
        if self.min_track_age_sec < 0:
            raise ValueError("min_track_age_sec must be non-negative")
        if self.max_aspect_ratio <= 0:
            raise ValueError("max_aspect_ratio must be positive")
        if self.max_center_vertical_velocity < 0:
            raise ValueError("max_center_vertical_velocity must be non-negative")
        if self.max_foot_vertical_velocity < 0:
            raise ValueError("max_foot_vertical_velocity must be non-negative")
        if self.min_height_change_rate > 0:
            raise ValueError("min_height_change_rate must be non-positive")
        if self.fallen_pose_threshold <= 0:
            raise ValueError("fallen_pose_threshold must be positive")
        if not (0.0 <= self.min_keypoint_conf <= 1.0):
            raise ValueError("min_keypoint_conf must be in [0, 1]")

    @classmethod
    def from_fall_detector_config(
        cls, config: "FallDetectorConfig"
    ) -> "PoseNormalGateConfig":
        return cls(
            min_track_age_sec=config.min_track_age_sec,
            max_aspect_ratio=config.normal_aspect_ratio_threshold,
            max_center_vertical_velocity=config.recovery_velocity_threshold,
            fallen_pose_threshold=config.pose_fallen_threshold,
            min_keypoint_conf=config.pose_min_keypoint_conf,
        )


@dataclass(frozen=True)
class PoseNormalGateDecision:
    use_auxiliary: bool
    unready: bool
    pose_unavailable: bool
    descending: bool
    non_normal_posture: bool


class PoseNormalGate:
    """Skip RGB only when every active Track is stable, upright, and pose-valid."""

    def __init__(self, fps: float, config: PoseNormalGateConfig | None = None):
        self.config = config or PoseNormalGateConfig()
        self._history = MultiTrackHistory(fps=fps)
        self._feature_extractor = FallFeatureExtractor()
        self._pose_extractor = PoseFeatureExtractor()

    def evaluate(self, tracking_result: TrackingResult) -> PoseNormalGateDecision:
        self._history.update(tracking_result)
        if not tracking_result.tracks:
            return PoseNormalGateDecision(False, False, False, False, False)

        unready = False
        pose_unavailable = False
        descending = False
        non_normal_posture = False
        for track in tracking_result.tracks:
            history = self._history.get_history(
                tracking_result.video_source, track.track_id
            )
            features = self._feature_extractor.extract(
                history, self.config.max_aspect_ratio
            )
            if (
                features is None
                or features.track_age_sec < self.config.min_track_age_sec
            ):
                unready = True
                continue

            pose = self._pose_extractor.extract(
                track,
                self.config.fallen_pose_threshold,
                self.config.min_keypoint_conf,
            )
            if pose is None:
                pose_unavailable = True
                continue

            descending = descending or (
                features.center_vertical_velocity
                > self.config.max_center_vertical_velocity
                or features.foot_point_vertical_velocity
                > self.config.max_foot_vertical_velocity
                or features.height_change_rate < self.config.min_height_change_rate
            )
            non_normal_posture = non_normal_posture or (
                features.aspect_ratio >= self.config.max_aspect_ratio
                or pose.is_fallen_pose
            )

        return PoseNormalGateDecision(
            use_auxiliary=(
                unready or pose_unavailable or descending or non_normal_posture
            ),
            unready=unready,
            pose_unavailable=pose_unavailable,
            descending=descending,
            non_normal_posture=non_normal_posture,
        )
