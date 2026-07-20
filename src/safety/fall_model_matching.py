"""보조 fall/nofall detector(AuxiliaryFallModel)의 detection을 같은 프레임의

기존 ByteTrack Track에 IoU 기준으로 매칭한다.

보조 모델은 자체 추적을 하지 않으므로(src/safety/auxiliary_fall_model.py
참고) 매 프레임 독립적으로 나온 bbox를 Track ID와 연결하는 이 단계가
필요하다. Track마다 정확히 하나의 FallModelEvidence를 만든다(누락 없이) —
매칭 실패는 "fall이 아니다"라는 근거가 아니라 "이 프레임에서 이 사람에
대한 모델 판단이 없다"는 뜻이므로 `label="nofall"`이 아니라
`label="unknown"`으로 구분한다. 이 둘을 합치면 모델이 그 사람을 놓친
프레임을 "낙상 아님" 증거로 잘못 취급하게 된다.

Track마다·detection마다 최대 1개씩만 연결한다(one-to-one). IoU가 가장 높은
순서로 그리디하게 짝짓는다 — 헝가리안 알고리즘 같은 전역 최적 할당이
아니지만, 한 화면의 인원 수가 적은 키즈카페 상황에서는 그리디와 전역
최적의 차이가 실질적으로 없고 구현이 훨씬 단순하다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from src.common.types import Track
from src.safety.auxiliary_fall_model import FallDetection


@dataclass(frozen=True)
class FallModelEvidence:
    """한 프레임에서 특정 Track에 연결된(또는 연결 실패한) 보조 모델 판단."""

    track_id: int
    label: str  # "fall" | "nofall" | "unknown" (매칭 실패)
    confidence: Optional[float]  # unknown이면 None
    iou: Optional[float]  # unknown이면 None


def compute_iou(bbox_a: List[float], bbox_b: List[float]) -> float:
    """두 [x1, y1, x2, y2] bbox의 IoU. 겹치지 않으면 0.0."""
    ax1, ay1, ax2, ay2 = bbox_a
    bx1, by1, bx2, by2 = bbox_b

    inter_x1 = max(ax1, bx1)
    inter_y1 = max(ay1, by1)
    inter_x2 = min(ax2, bx2)
    inter_y2 = min(ay2, by2)
    inter_area = max(0.0, inter_x2 - inter_x1) * max(0.0, inter_y2 - inter_y1)

    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - inter_area
    if union <= 0.0:
        return 0.0
    return inter_area / union


def match_detections_to_tracks(
    tracks: List[Track],
    detections: List[FallDetection],
    iou_threshold: float,
) -> List[FallModelEvidence]:
    """Track별로 정확히 1개의 FallModelEvidence를 반환한다(입력 tracks와 같은 개수·순서)."""
    if not (0.0 < iou_threshold <= 1.0):
        raise ValueError(
            f"iou_threshold는 0보다 크고 1 이하여야 합니다: {iou_threshold} "
            "(0을 허용하면 전혀 겹치지 않는 bbox끼리도 매칭됩니다)"
        )

    # (iou, confidence, track_index, detection_index). IoU가 같으면 confidence가
    # 높은 detection이 우선하도록 정렬 키에 confidence도 포함한다 — 같은 위치에
    # fall/nofall detection이 둘 다 남아 있을 때 입력 순서가 아니라 모델이 더
    # 확신하는 쪽이 선택돼야 한다.
    candidates: List[Tuple[float, float, int, int]] = []
    for track_idx, track in enumerate(tracks):
        for det_idx, detection in enumerate(detections):
            iou = compute_iou(track.bbox, detection.bbox)
            if iou >= iou_threshold:
                candidates.append((iou, detection.confidence, track_idx, det_idx))

    # (IoU, confidence) 내림차순으로 그리디 매칭 — 높은 확신부터 먼저 배정한다.
    candidates.sort(key=lambda c: (c[0], c[1]), reverse=True)

    used_tracks = set()
    used_detections = set()
    matched: Dict[int, FallModelEvidence] = {}
    for iou, _confidence, track_idx, det_idx in candidates:
        if track_idx in used_tracks or det_idx in used_detections:
            continue
        track = tracks[track_idx]
        detection = detections[det_idx]
        matched[track.track_id] = FallModelEvidence(
            track_id=track.track_id,
            label=detection.label,
            confidence=detection.confidence,
            iou=iou,
        )
        used_tracks.add(track_idx)
        used_detections.add(det_idx)

    evidence: List[FallModelEvidence] = []
    for track in tracks:
        if track.track_id in matched:
            evidence.append(matched[track.track_id])
        else:
            evidence.append(
                FallModelEvidence(
                    track_id=track.track_id, label="unknown", confidence=None, iou=None
                )
            )
    return evidence
