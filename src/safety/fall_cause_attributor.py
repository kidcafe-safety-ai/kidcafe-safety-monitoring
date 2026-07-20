"""FALL_SUSPECT 확정 시 외부 접촉 원인 후보를 추정한다.

결과는 ``NEARBY_TRACK`` 후보 또는 ``None``이며 실제 충돌이나 인과관계를
확정하지 않는다. 낙상 판정의 특징 창을 바꾸지 않도록 foot point, bbox 높이,
시각만 별도 이력으로 관리한다.

Candidate 진입 시각 이전의 동시 관측 샘플에서 거리와 접근 속도 기준을 모두
만족한 Track만 채점한다. 승계 전 피해 Track ID는 alias로 병합하되 후보에서는
제외한다. 세부 계약과 임계값 근거는 ``docs/interfaces.md``와
``docs/decisions.md`` ADR-016에 기록한다.
"""

from __future__ import annotations

import json
import math
from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict, FrozenSet, List, Optional, Tuple

from src.common.types import EventCause, EventCauseEvidence, TrackingResult

TrackKey = Tuple[str, int]


@dataclass(frozen=True)
class _CauseSample:
    """attribution 전용 최소 스냅샷 (immutable)."""

    frame_number: int
    time_sec: float
    foot_point: Tuple[float, float]
    bbox_height: float


@dataclass
class FallCauseAttributorConfig:
    """configs/fall_detection.json의 "cause_attribution" 섹션에서 로드한다."""

    enabled: bool = True
    lookback_sec: float = 1.0
    history_window_sec: float = 4.0
    track_grace_sec: float = 4.0
    min_samples: int = 2
    distance_threshold: float = 1.5
    closing_speed_threshold: float = 1.0
    min_closing_speed_norm: float = 0.1
    distance_weight: float = 0.5
    speed_weight: float = 0.5
    score_threshold: float = 0.5
    # 동시 관측으로 간주할 최대 샘플 간격. 멀리 떨어진 시점의 Track을
    # 짝지어 인위적인 접근 패턴을 만들지 않는다.
    max_pairing_gap_frames: float = 1.5

    def __post_init__(self):
        if self.lookback_sec <= 0:
            raise ValueError("lookback_sec는 0보다 커야 합니다.")
        if self.history_window_sec <= self.lookback_sec:
            raise ValueError(
                "history_window_sec는 lookback_sec보다 커야 합니다 "
                "(그렇지 않으면 lookback 구간 초반 샘플이 이미 잘려나갑니다)."
            )
        if self.track_grace_sec <= 0:
            raise ValueError("track_grace_sec는 0보다 커야 합니다.")
        if self.min_samples < 1:
            raise ValueError("min_samples는 1 이상이어야 합니다.")
        if self.max_pairing_gap_frames <= 0:
            raise ValueError("max_pairing_gap_frames는 0보다 커야 합니다.")
        if self.distance_threshold <= 0:
            raise ValueError("distance_threshold는 0보다 커야 합니다.")
        if self.closing_speed_threshold <= 0:
            raise ValueError("closing_speed_threshold는 0보다 커야 합니다.")
        if self.min_closing_speed_norm < 0:
            raise ValueError("min_closing_speed_norm은 0 이상이어야 합니다.")
        if self.distance_weight < 0 or self.speed_weight < 0:
            raise ValueError("distance_weight/speed_weight는 음수일 수 없습니다.")
        if not (0.0 <= self.score_threshold <= 1.0):
            raise ValueError("score_threshold는 0~1 사이여야 합니다.")

    @classmethod
    def from_file(cls, path: str) -> "FallCauseAttributorConfig":
        with open(path, "r", encoding="utf-8") as file:
            data = json.load(file)
        section = data.get("cause_attribution", {})
        return cls(**section)


@dataclass
class _ScoredCandidate:
    track_id: int
    score: float
    min_distance_norm: float
    closing_speed_norm: float
    time_to_fall_sec: float


class FallCauseAttributor:
    """Track별 독립 이력을 관리하며, 확정된 낙상에 외부 접촉 원인 후보를 붙인다."""

    def __init__(self, fps: float, config: Optional[FallCauseAttributorConfig] = None) -> None:
        if fps <= 0:
            raise ValueError("fps는 0보다 커야 합니다.")
        self.fps = fps
        self.config = config or FallCauseAttributorConfig()
        self._max_pairing_gap_sec = self.config.max_pairing_gap_frames / fps
        self._history: Dict[TrackKey, Deque[_CauseSample]] = {}
        self._last_seen_sec: Dict[TrackKey, float] = {}

    def update(self, tracking_result: TrackingResult) -> None:
        """한 프레임의 TrackingResult를 이력에 반영한다.

        `FallDetector.process()`와 별도로, `FallPipeline`이 매 프레임 호출한다.
        """
        if not self.config.enabled:
            return

        time_sec = tracking_result.frame_number / self.fps
        video_source = tracking_result.video_source
        seen_keys = set()

        for track in tracking_result.tracks:
            key = (video_source, track.track_id)
            seen_keys.add(key)
            x1, y1, x2, y2 = track.bbox
            bbox_height = max(y2 - y1, 1e-6)
            sample = _CauseSample(
                frame_number=tracking_result.frame_number,
                time_sec=time_sec,
                foot_point=(float(track.foot_point[0]), float(track.foot_point[1])),
                bbox_height=float(bbox_height),
            )
            history = self._history.setdefault(key, deque())
            history.append(sample)
            self._trim_window(history, time_sec)
            self._last_seen_sec[key] = time_sec

        self._evict_expired(video_source, seen_keys, time_sec)

    def _trim_window(self, history: Deque[_CauseSample], now_sec: float) -> None:
        while history and (now_sec - history[0].time_sec) > self.config.history_window_sec:
            history.popleft()

    def _evict_expired(self, video_source: str, seen_keys: set, now_sec: float) -> None:
        expired = [
            key
            for key, last_seen in self._last_seen_sec.items()
            if key[0] == video_source
            and key not in seen_keys
            and (now_sec - last_seen) > self.config.track_grace_sec
        ]
        for key in expired:
            self._history.pop(key, None)
            self._last_seen_sec.pop(key, None)

    def attribute(
        self,
        video_source: str,
        victim_track_id: int,
        fall_start_sec: Optional[float],
        victim_track_id_aliases: FrozenSet[int] = frozenset(),
    ) -> Optional[EventCause]:
        """확정된 낙상 하나에 대해 외부 접촉 원인 후보를 찾는다. 근거 부족 시 None.

        fall_start_sec: FALLING_CANDIDATE 진입 시각(onset proxy). None이면
            (state 불변식 위반이든, attribution 비활성 상태에서 흘러들어온
            값이든) 현재 시각으로 대체하지 않고 즉시 None을 반환한다.
        victim_track_id_aliases: Candidate Handoff(src/safety/fall_detector.py
            모듈 docstring)로 이 피해자가 승계 이전에 썼던 옛 track_id들.
            이 클래스는 `FallDetector`와 완전히 독립된 자체 이력을 Track별로
            관리하므로(모듈 docstring), handoff로 track_id가 바뀌면 그 전
            시각의 샘플은 옛 track_id 밑에 그대로 남아있다 — fall_start_sec
            직전 lookback 구간이 handoff 이전 시각까지 걸쳐 있으면, 새
            track_id만 조회해서는 그 구간의 victim 샘플을 못 찾아 근거
            부족으로 잘못 cause=None이 될 수 있다. 또한 옛 track_id는
            피해자 자신의 이력이므로, 후보(가해자 의심 Track) 목록에서도
            제외해야 한다 — 그러지 않으면 피해자가 자기 자신의 예전
            track_id를 스스로의 낙상 원인으로 지목하는 자기 참조가 생긴다.
        """
        if not self.config.enabled or fall_start_sec is None:
            return None

        victim_track_ids = victim_track_id_aliases | {victim_track_id}
        victim_history: List[_CauseSample] = []
        for vid in victim_track_ids:
            victim_history.extend(self._history.get((video_source, vid), []))
        if not victim_history:
            return None
        victim_history.sort(key=lambda s: s.time_sec)

        window_start = fall_start_sec - self.config.lookback_sec
        victim_samples = [
            s for s in victim_history if window_start <= s.time_sec <= fall_start_sec
        ]
        if len(victim_samples) < self.config.min_samples:
            return None

        scored_candidates: List[_ScoredCandidate] = []
        for key, history in self._history.items():
            candidate_video_source, candidate_track_id = key
            if candidate_video_source != video_source or candidate_track_id in victim_track_ids:
                continue
            if not history or history[0].time_sec > fall_start_sec:
                # 낙상 시작 "뒤"에 처음 등장한 Track은 원인일 수 없다.
                continue
            candidate_samples = [
                s for s in history if window_start <= s.time_sec <= fall_start_sec
            ]
            if len(candidate_samples) < self.config.min_samples:
                continue

            scored = self._score_candidate(
                candidate_track_id, victim_samples, candidate_samples, fall_start_sec
            )
            if scored is not None:
                scored_candidates.append(scored)

        if not scored_candidates:
            return None

        scored_candidates.sort(
            key=lambda c: (-c.score, c.min_distance_norm, c.track_id)
        )
        best = scored_candidates[0]
        if best.score < self.config.score_threshold:
            return None

        return EventCause(
            type="NEARBY_TRACK",
            track_id=best.track_id,
            score=best.score,
            evidence=EventCauseEvidence(
                min_distance_norm=best.min_distance_norm,
                closing_speed_norm=best.closing_speed_norm,
                time_to_fall_sec=best.time_to_fall_sec,
            ),
        )

    def _pair_samples_one_to_one(
        self,
        victim_samples: List[_CauseSample],
        candidate_samples: List[_CauseSample],
    ) -> List[Tuple[_CauseSample, _CauseSample]]:
        """시간 간격이 가까운 순으로 그리디하게 1:1 매칭한다.

        (src/safety/fall_model_matching.py의 IoU 그리디 매칭과 동일한 패턴).
        "가장 가까운 시각" 매칭을 victim 샘플마다 독립적으로 하면, 후보
        관측이 실제로는 1개뿐인데도 그 하나가 여러 victim 샘플에 반복
        재사용되어(예: victim이 그 사이 스스로 움직인 것뿐인데도) 마치
        후보가 여러 번 관측되며 접근한 것처럼 보이는 근거가 인위적으로
        만들어질 수 있다. 각 candidate 샘플·victim 샘플을 최대 1회씩만
        쓰도록 강제해 이를 막는다.

        gap 오름차순 그리디는 전역 최적(최대 매칭 수) 배정을 보장하지
        않는다 — 드물게 최적 배정보다 적게 짝지어질 수 있다. 다만 그 경우
        결과는 항상 "근거 부족으로 cause=None"(min_samples 미달) 방향으로만
        보수적으로 기운다 — false cause(근거 없이 후보를 만드는 것)를
        만드는 방향이 아니므로 Phase 3 PoC 범위에서는 허용한다.
        """
        gaps: List[Tuple[float, int, int]] = []
        for v_idx, victim_sample in enumerate(victim_samples):
            for c_idx, candidate_sample in enumerate(candidate_samples):
                gap = abs(victim_sample.time_sec - candidate_sample.time_sec)
                if gap <= self._max_pairing_gap_sec:
                    gaps.append((gap, v_idx, c_idx))
        gaps.sort(key=lambda item: item[0])

        used_victim_idx = set()
        used_candidate_idx = set()
        pairs: List[Tuple[_CauseSample, _CauseSample]] = []
        for _gap, v_idx, c_idx in gaps:
            if v_idx in used_victim_idx or c_idx in used_candidate_idx:
                continue
            pairs.append((victim_samples[v_idx], candidate_samples[c_idx]))
            used_victim_idx.add(v_idx)
            used_candidate_idx.add(c_idx)
        return pairs

    def _score_candidate(
        self,
        candidate_track_id: int,
        victim_samples: List[_CauseSample],
        candidate_samples: List[_CauseSample],
        fall_start_sec: float,
    ) -> Optional[_ScoredCandidate]:
        cfg = self.config
        pairs = self._pair_samples_one_to_one(victim_samples, candidate_samples)
        if len(pairs) < cfg.min_samples:
            # 독립적으로 관측된 샘플 수가 아니라, 실제로 짝지어진(=1:1로 동시
            # 관측된) 거리 샘플이 충분해야 한다 — 후보 관측이 실질적으로
            # 1개뿐이면(같은 샘플이 여러 victim에 재사용될 상황이면) 여기서 걸러진다.
            return None

        distances: List[Tuple[float, float]] = [
            (
                victim_sample.time_sec,
                _euclidean(victim_sample.foot_point, candidate_sample.foot_point)
                / victim_sample.bbox_height,
            )
            for victim_sample, candidate_sample in pairs
        ]

        min_distance_time, min_distance_norm = min(distances, key=lambda d: d[1])
        if min_distance_norm > cfg.distance_threshold:
            return None

        distances.sort(key=lambda d: d[0])
        first_time, first_distance = distances[0]
        last_time, last_distance = distances[-1]
        elapsed = last_time - first_time
        if elapsed <= 0:
            closing_speed_norm = 0.0
        else:
            closing_speed_norm = max(0.0, (first_distance - last_distance) / elapsed)

        if closing_speed_norm < cfg.min_closing_speed_norm:
            return None

        proximity_score = max(0.0, 1.0 - min_distance_norm / cfg.distance_threshold)
        closing_score = min(1.0, closing_speed_norm / cfg.closing_speed_threshold)
        score = cfg.distance_weight * proximity_score + cfg.speed_weight * closing_score
        score = max(0.0, min(1.0, score))

        return _ScoredCandidate(
            track_id=candidate_track_id,
            score=score,
            min_distance_norm=min_distance_norm,
            closing_speed_norm=closing_speed_norm,
            time_to_fall_sec=max(0.0, fall_start_sec - min_distance_time),
        )


def _euclidean(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])
