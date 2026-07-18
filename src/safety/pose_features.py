"""COCO 17 keypoint에서 낙상 판정에 필요한 pose 특징을 추출한다.

bbox aspect_ratio는 카메라 각도에 따라 일부 낙상 방향(forward·left)을
놓친다 (docs/fall_evaluation.md 참고). 처음에는 어깨-엉덩이 벡터가 수직에서
기운 각도(torso_angle)를 시도했으나, 카메라를 향해/멀어지는 방향(깊이 방향)
으로 쓰러지면 몸 전체가 2D 영상에 압축 투영되어 이 벡터도 여전히 수직에
가깝게 나온다 — bbox와 동일한 카메라 각도 문제가 골격 각도에도 그대로
나타난다 (CAUCAFall Subject 1 Fall forward 실측, docs/fall_evaluation.md 참고).

대신 머리(head) 중심이 엉덩이(hip) 중심보다 얼마나 아래에 있는지를
bbox 높이로 정규화한 값(head_hip_diff_norm)을 쓴다. 서 있으면 머리가 항상
엉덩이보다 위(음수)이고, 어느 방향으로 쓰러지든(깊이 방향 포함) 결국 머리가
엉덩이와 비슷한 높이이거나 아래(0 또는 양수)로 내려간다 — 실측 결과 벡터
각도보다 훨씬 안정적으로 분리된다(낙상 최소 ~0.24 vs 일상 동작 최대 ~0.16).

머리 keypoint는 코(nose) 신뢰도가 자세 변화 중 자주 떨어지므로, 코 → 눈
평균 → 귀 평균 순서로 신뢰도가 충분한 첫 keypoint를 사용한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from src.common.types import Track

# COCO 17 keypoint 인덱스
_NOSE = 0
_LEFT_EYE = 1
_RIGHT_EYE = 2
_LEFT_EAR = 3
_RIGHT_EAR = 4
_LEFT_HIP = 11
_RIGHT_HIP = 12

_DEFAULT_MIN_KEYPOINT_CONF = 0.3


@dataclass(frozen=True)
class PoseFeatures:
    """한 프레임의 keypoint로 계산한 pose 특징."""

    head_hip_diff_norm: float  # (head_y - hip_y) / bbox_height. 음수=서 있음, 양수에 가까울수록 누움
    is_fallen_pose: bool  # head_hip_diff_norm이 임계값 이상이면 쓰러진 자세로 판단


def _head_center(
    keypoints: List[List[float]], keypoints_conf: List[float], min_conf: float
) -> Optional[tuple]:
    """코 → 눈 평균 → 귀 평균 순서로 신뢰도가 충분한 첫 head keypoint(들)의 평균을 반환한다."""
    if keypoints_conf[_NOSE] >= min_conf:
        return tuple(keypoints[_NOSE])

    eyes = [i for i in (_LEFT_EYE, _RIGHT_EYE) if keypoints_conf[i] >= min_conf]
    if eyes:
        x = sum(keypoints[i][0] for i in eyes) / len(eyes)
        y = sum(keypoints[i][1] for i in eyes) / len(eyes)
        return (x, y)

    ears = [i for i in (_LEFT_EAR, _RIGHT_EAR) if keypoints_conf[i] >= min_conf]
    if ears:
        x = sum(keypoints[i][0] for i in ears) / len(ears)
        y = sum(keypoints[i][1] for i in ears) / len(ears)
        return (x, y)

    return None


class PoseFeatureExtractor:
    """Track.keypoints에서 PoseFeatures를 계산한다."""

    def extract(
        self,
        track: Track,
        fallen_pose_threshold: float,
        min_keypoint_conf: float = _DEFAULT_MIN_KEYPOINT_CONF,
    ) -> Optional[PoseFeatures]:
        """머리(대체 keypoint 포함)·엉덩이 신뢰도가 부족하면 None을 반환한다 (pose 신호 없음)."""
        if track.keypoints is None or track.keypoints_conf is None:
            return None

        if (
            track.keypoints_conf[_LEFT_HIP] < min_keypoint_conf
            or track.keypoints_conf[_RIGHT_HIP] < min_keypoint_conf
        ):
            return None

        head = _head_center(track.keypoints, track.keypoints_conf, min_keypoint_conf)
        if head is None:
            return None

        height = track.bbox[3] - track.bbox[1]
        if height <= 0:
            return None

        head_y = head[1]
        hip_y = (track.keypoints[_LEFT_HIP][1] + track.keypoints[_RIGHT_HIP][1]) / 2.0
        head_hip_diff_norm = (head_y - hip_y) / height

        return PoseFeatures(
            head_hip_diff_norm=head_hip_diff_norm,
            is_fallen_pose=head_hip_diff_norm >= fallen_pose_threshold,
        )
