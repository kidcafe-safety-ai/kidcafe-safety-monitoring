"""Track 이력에서 낙상 판정에 필요한 특징을 추출한다.

속도·변화율은 절대 픽셀 단위 대신 최근 bbox 높이로 정규화한다. 카메라와의
거리에 따라 사람의 픽셀 크기가 달라지므로, 절대 속도만으로는 가까운 사람의
느린 움직임과 먼 사람의 빠른 움직임을 구분할 수 없기 때문이다.

속도·변화율은 MultiTrackHistory가 보관하는 전체 history_window_sec(기본 2초)
구간이 아니라, 가장 최근 두 샘플 간의 순간 변화량으로 계산한다. 전체 구간의
oldest-latest 차이로 계산하면, 1~2초간 가만히 있다가 마지막 0.2~0.3초에
급격히 쓰러진 경우에도 변화율이 전체 구간(2초)으로 나뉘어 희석되어 실제보다
훨씬 완만한 움직임으로 보이기 때문이다. track_age_sec만 전체 이력 구간
(가장 오래된 샘플~최신 샘플)을 그대로 사용해, "Track이 얼마나 오래
유지됐는가"를 판단하는 min_track_age_sec 게이트와 분리한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from src.safety.multi_track_history import TrackSample


@dataclass(frozen=True)
class FallFeatures:
    """최근 두 샘플 간 순간 변화량 기준으로 계산한 낙상 판정 특징."""

    aspect_ratio: float  # width / height (최신 샘플 기준)
    height_change_rate: float  # 높이 변화율(직전→최신 샘플), 높이로 정규화한 초당 변화량
    area_change_rate: float  # 면적 변화율(직전→최신 샘플), 초당 변화 비율
    center_vertical_velocity: float  # bbox 중심 y 속도(직전→최신), 초당 변화량 (양수=아래로 이동)
    foot_point_vertical_velocity: float  # foot_point y 속도(직전→최신), 초당 변화량
    center_horizontal_velocity: float  # bbox 중심 x 속도(직전→최신), 최근 이동 방향 판단용
    is_horizontal_posture: bool  # aspect_ratio가 임계값 이상이면 누운 자세로 판단
    track_age_sec: float  # 전체 이력 구간 길이 (가장 오래된 샘플~최신 샘플, 초)
    avg_confidence: float  # 이력 구간 평균 tracker confidence


class FallFeatureExtractor:
    """MultiTrackHistory가 쌓은 샘플 목록에서 FallFeatures를 계산한다."""

    def extract(
        self,
        history: List[TrackSample],
        horizontal_aspect_ratio_threshold: float,
    ) -> Optional[FallFeatures]:
        """샘플이 2개 미만이면 속도를 계산할 수 없으므로 None을 반환한다."""
        if len(history) < 2:
            return None

        latest = history[-1]
        previous = history[-2]
        full_earliest = history[0]

        width = latest.bbox[2] - latest.bbox[0]
        height = latest.bbox[3] - latest.bbox[1]
        if height <= 0:
            return None
        aspect_ratio = width / height

        track_age_sec = latest.time_sec - full_earliest.time_sec
        if track_age_sec < 0:
            return None

        dt = latest.time_sec - previous.time_sec
        if dt <= 0:
            return None

        norm = height  # 정규화 기준: 최신 bbox 높이

        previous_width = previous.bbox[2] - previous.bbox[0]
        previous_height = previous.bbox[3] - previous.bbox[1]
        previous_area = previous_width * previous_height
        latest_area = width * height

        height_change_rate = (height - previous_height) / norm / dt
        area_denominator = previous_area if previous_area > 0 else norm * norm
        area_change_rate = (latest_area - previous_area) / area_denominator / dt

        latest_center_y = (latest.bbox[1] + latest.bbox[3]) / 2.0
        previous_center_y = (previous.bbox[1] + previous.bbox[3]) / 2.0
        center_vertical_velocity = (latest_center_y - previous_center_y) / norm / dt

        latest_center_x = (latest.bbox[0] + latest.bbox[2]) / 2.0
        previous_center_x = (previous.bbox[0] + previous.bbox[2]) / 2.0
        center_horizontal_velocity = (latest_center_x - previous_center_x) / norm / dt

        foot_point_vertical_velocity = (latest.foot_point[1] - previous.foot_point[1]) / norm / dt

        avg_confidence = sum(sample.confidence for sample in history) / len(history)

        return FallFeatures(
            aspect_ratio=aspect_ratio,
            height_change_rate=height_change_rate,
            area_change_rate=area_change_rate,
            center_vertical_velocity=center_vertical_velocity,
            foot_point_vertical_velocity=foot_point_vertical_velocity,
            center_horizontal_velocity=center_horizontal_velocity,
            is_horizontal_posture=aspect_ratio >= horizontal_aspect_ratio_threshold,
            track_age_sec=track_age_sec,
            avg_confidence=avg_confidence,
        )
