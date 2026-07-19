"""src/safety/fall_cause_attributor.py 테스트.

FallDetector와 완전히 분리된 순수 시나리오로 검증한다 — 실제 FallDetector와의
연결(candidate_since_sec 보존 등)은 tests/test_fall_detector.py,
tests/test_fall_pipeline_module.py에서 확인한다.
"""

from __future__ import annotations

import pytest

from src.common.types import Track, TrackingResult
from src.safety.fall_cause_attributor import FallCauseAttributor, FallCauseAttributorConfig

_VIDEO_SOURCE = "cam1"
_BBOX_HEIGHT = 100.0


def _track(track_id: int, x: float, y: float = 500.0) -> Track:
    return Track(
        track_id=track_id,
        bbox=[x - 50.0, y - _BBOX_HEIGHT, x + 50.0, y],
        foot_point=[x, y],
        confidence=0.9,
    )


def _result(frame_number: int, tracks, video_source: str = _VIDEO_SOURCE) -> TrackingResult:
    return TrackingResult(
        frame_number=frame_number,
        timestamp="00:00:00.000",
        video_source=video_source,
        tracks=tracks,
    )


def _fast_config(**overrides) -> FallCauseAttributorConfig:
    defaults = dict(
        lookback_sec=1.0,
        history_window_sec=4.0,
        track_grace_sec=4.0,
        min_samples=2,
        distance_threshold=1.5,
        closing_speed_threshold=1.0,
        min_closing_speed_norm=0.1,
        distance_weight=0.5,
        speed_weight=0.5,
        score_threshold=0.5,
    )
    defaults.update(overrides)
    return FallCauseAttributorConfig(**defaults)


_FPS = 10.0


def _feed_victim_stationary(attributor, x=500.0, t_start=0.0, t_end=2.0, step=0.1):
    """피해 Track(id=1)을 t_start~t_end 동안 고정 위치에 채운다."""
    t = t_start
    while t <= t_end + 1e-9:
        frame_number = round(t * _FPS)
        attributor.update(_result(frame_number, [_track(1, x)]))
        t += step


def _feed_frames_in_order(attributor, frame_tracks):
    """frame_number -> Track 리스트 딕셔너리를 프레임 오름차순으로 update()한다.

    같은 frame_number에 여러 Track이 있으면 한 번의 update() 호출로 합쳐서
    보낸다 — 실제 파이프라인은 한 프레임의 모든 Track을 하나의
    TrackingResult로 묶어 한 번만 update()를 호출하므로, 테스트도 이
    순서·묶음을 지켜야 시간이 뒤섞인 비현실적 입력을 피할 수 있다.
    """
    for frame_number in sorted(frame_tracks):
        attributor.update(_result(frame_number, frame_tracks[frame_number]))


class TestApproachingCandidate:
    def test_approaching_candidate_produces_nearby_track_cause(self):
        """실제 파이프라인처럼 프레임 번호 오름차순 단일 루프로 채운다 —

        한 프레임당 update() 호출은 한 번뿐이어야 현실적이다.
        """
        attributor = FallCauseAttributor(fps=_FPS, config=_fast_config())

        t = 0.0
        while t <= 2.0 + 1e-9:
            frame_number = round(t * _FPS)
            tracks = [_track(1, 500.0)]
            if t >= 1.0:
                # 후보(id=2)가 t=1.0(x=700, norm dist=2.0)에서
                # t=2.0(x=520, norm dist=0.2)까지 접근.
                candidate_x = 700.0 - (700.0 - 520.0) * ((t - 1.0) / 1.0)
                tracks.append(_track(2, candidate_x))
            attributor.update(_result(frame_number, tracks))
            t += 0.1

        cause = attributor.attribute(_VIDEO_SOURCE, victim_track_id=1, fall_start_sec=2.0)

        assert cause is not None
        assert cause.type == "NEARBY_TRACK"
        assert cause.track_id == 2
        assert 0.0 < cause.score <= 1.0
        assert cause.evidence.min_distance_norm < 0.5
        assert cause.evidence.closing_speed_norm >= 0.1
        assert cause.evidence.time_to_fall_sec >= 0.0


class TestNoClosingEvidence:
    def test_near_but_not_approaching_returns_none(self):
        """가까이 있어도 순 접근 속도가 없으면(정지 상태) cause=null이어야 한다."""
        attributor = FallCauseAttributor(fps=_FPS, config=_fast_config())
        t = 0.0
        while t <= 2.0 + 1e-9:
            frame_number = round(t * _FPS)
            # 후보가 계속 victim과 같은 거리(norm=0.3)를 유지 — 접근도 이탈도 아님.
            attributor.update(
                _result(frame_number, [_track(1, 500.0), _track(2, 530.0)])
            )
            t += 0.1

        cause = attributor.attribute(_VIDEO_SOURCE, victim_track_id=1, fall_start_sec=2.0)

        assert cause is None

    def test_far_candidate_beyond_distance_threshold_returns_none(self):
        attributor = FallCauseAttributor(fps=_FPS, config=_fast_config())
        t = 1.0
        while t <= 2.0 + 1e-9:
            frame_number = round(t * _FPS)
            # distance_threshold(1.5) * bbox_height(100) = 150 훨씬 밖.
            attributor.update(
                _result(frame_number, [_track(1, 500.0), _track(2, 900.0)])
            )
            t += 0.1

        cause = attributor.attribute(_VIDEO_SOURCE, victim_track_id=1, fall_start_sec=2.0)

        assert cause is None


class TestCandidateAppearingAfterFallStart:
    def test_candidate_first_seen_after_fall_start_is_excluded(self):
        """실제 파이프라인처럼 프레임 번호 오름차순 단일 루프로 채운다."""
        attributor = FallCauseAttributor(fps=_FPS, config=_fast_config())

        t = 0.0
        while t <= 2.5 + 1e-9:
            frame_number = round(t * _FPS)
            tracks = [_track(1, 500.0)]
            # 후보가 fall_start_sec(2.0) "이후"인 2.1초에 처음 등장, 거리도 0에 가까움.
            if t >= 2.1:
                tracks.append(_track(2, 500.0))
            attributor.update(_result(frame_number, tracks))
            t += 0.1

        cause = attributor.attribute(_VIDEO_SOURCE, victim_track_id=1, fall_start_sec=2.0)

        assert cause is None


class TestVictimSelfExcluded:
    def test_victim_alone_never_becomes_own_cause(self):
        """다른 Track이 전혀 없으면(피해자 자신 제외 로직이 없다면 자기 자신이

        거리 0의 완벽한 후보가 될 것이다) cause=null이어야 한다.
        """
        attributor = FallCauseAttributor(fps=_FPS, config=_fast_config())
        _feed_victim_stationary(attributor, x=500.0, t_start=0.0, t_end=2.0)

        cause = attributor.attribute(_VIDEO_SOURCE, victim_track_id=1, fall_start_sec=2.0)

        assert cause is None


class TestDifferentVideoSourceExcluded:
    def test_candidate_in_different_video_source_is_excluded(self):
        attributor = FallCauseAttributor(fps=_FPS, config=_fast_config())
        t = 1.0
        while t <= 2.0 + 1e-9:
            frame_number = round(t * _FPS)
            attributor.update(_result(frame_number, [_track(1, 500.0)], video_source="cam1"))
            # 다른 video_source에서 완벽한 후보 조건(가까움+접근)을 만족시켜도 무시돼야 함.
            candidate_x = 700.0 - (700.0 - 500.0) * ((t - 1.0) / 1.0)
            attributor.update(
                _result(frame_number, [_track(2, candidate_x)], video_source="cam2")
            )
            t += 0.1

        cause = attributor.attribute(_VIDEO_SOURCE, victim_track_id=1, fall_start_sec=2.0)

        assert cause is None


class TestInsufficientHistory:
    def test_missing_victim_history_returns_none(self):
        attributor = FallCauseAttributor(fps=_FPS, config=_fast_config())

        cause = attributor.attribute(_VIDEO_SOURCE, victim_track_id=1, fall_start_sec=2.0)

        assert cause is None

    def test_single_sample_below_min_samples_returns_none(self):
        attributor = FallCauseAttributor(fps=_FPS, config=_fast_config(min_samples=2))
        # victim은 window 안에 샘플이 1개뿐 (min_samples=2 미달).
        attributor.update(_result(round(2.0 * _FPS), [_track(1, 500.0), _track(2, 510.0)]))

        cause = attributor.attribute(_VIDEO_SOURCE, victim_track_id=1, fall_start_sec=2.0)

        assert cause is None

    def test_fall_start_sec_none_returns_none_without_using_current_time(self):
        attributor = FallCauseAttributor(fps=_FPS, config=_fast_config())
        t = 0.0
        while t <= 2.0 + 1e-9:
            frame_number = round(t * _FPS)
            tracks = [_track(1, 500.0)]
            if t >= 1.0:
                candidate_x = 700.0 - (700.0 - 510.0) * ((t - 1.0) / 1.0)
                tracks.append(_track(2, candidate_x))
            attributor.update(_result(frame_number, tracks))
            t += 0.1

        cause = attributor.attribute(_VIDEO_SOURCE, victim_track_id=1, fall_start_sec=None)

        assert cause is None

    def test_disabled_attributor_never_produces_cause(self):
        attributor = FallCauseAttributor(fps=_FPS, config=_fast_config(enabled=False))
        t = 1.0
        while t <= 2.0 + 1e-9:
            frame_number = round(t * _FPS)
            candidate_x = 700.0 - (700.0 - 510.0) * ((t - 1.0) / 1.0)
            attributor.update(
                _result(frame_number, [_track(1, 500.0), _track(2, candidate_x)])
            )
            t += 0.1

        cause = attributor.attribute(_VIDEO_SOURCE, victim_track_id=1, fall_start_sec=2.0)

        assert cause is None


class TestTieBreakDeterminism:
    def test_equal_score_prefers_lower_track_id(self):
        attributor = FallCauseAttributor(fps=_FPS, config=_fast_config())
        t = 1.0
        while t <= 2.0 + 1e-9:
            frame_number = round(t * _FPS)
            progress = (t - 1.0) / 1.0
            # 후보 3(왼쪽)과 후보 2(오른쪽)가 victim(500)을 향해 대칭으로 접근 —
            # 거리·접근 속도가 완전히 동일해야 track_id로만 tie-break된다.
            right_x = 700.0 - 200.0 * progress  # 700 -> 500
            left_x = 300.0 + 200.0 * progress  # 300 -> 500
            attributor.update(
                _result(
                    frame_number,
                    [_track(1, 500.0), _track(2, right_x), _track(3, left_x)],
                )
            )
            t += 0.1

        cause = attributor.attribute(_VIDEO_SOURCE, victim_track_id=1, fall_start_sec=2.0)

        assert cause is not None
        assert cause.track_id == 2  # 점수 동률이면 track_id가 더 작은 쪽


class TestCandidateHistorySurvivesDisappearance:
    def test_candidate_removed_from_scene_still_attributable_within_grace(self):
        attributor = FallCauseAttributor(
            fps=_FPS, config=_fast_config(track_grace_sec=4.0)
        )
        t = 1.0
        while t <= 2.0 + 1e-9:
            frame_number = round(t * _FPS)
            candidate_x = 700.0 - (700.0 - 510.0) * ((t - 1.0) / 1.0)
            attributor.update(
                _result(frame_number, [_track(1, 500.0), _track(2, candidate_x)])
            )
            t += 0.1

        # 후보가 접촉 직후(2.0초) 화면에서 사라짐 — 이후 victim만 계속 관측된다.
        # track_grace_sec(4.0초) 이내이므로 후보 이력은 여전히 조회 가능해야 한다.
        t = 2.1
        while t <= 3.5 + 1e-9:
            frame_number = round(t * _FPS)
            attributor.update(_result(frame_number, [_track(1, 500.0)]))
            t += 0.1

        cause = attributor.attribute(_VIDEO_SOURCE, victim_track_id=1, fall_start_sec=2.0)

        assert cause is not None
        assert cause.track_id == 2

    def test_candidate_history_evicted_after_grace_period_expires(self):
        attributor = FallCauseAttributor(
            fps=_FPS, config=_fast_config(track_grace_sec=1.0)
        )
        t = 1.0
        while t <= 2.0 + 1e-9:
            frame_number = round(t * _FPS)
            candidate_x = 700.0 - (700.0 - 510.0) * ((t - 1.0) / 1.0)
            attributor.update(
                _result(frame_number, [_track(1, 500.0), _track(2, candidate_x)])
            )
            t += 0.1

        # grace_sec(1.0초)보다 오래 후보가 안 보이면 이력에서 제거돼야 한다.
        t = 2.1
        while t <= 4.0 + 1e-9:
            frame_number = round(t * _FPS)
            attributor.update(_result(frame_number, [_track(1, 500.0)]))
            t += 0.1

        cause = attributor.attribute(_VIDEO_SOURCE, victim_track_id=1, fall_start_sec=2.0)

        assert cause is None


class TestFallCauseAttributorConfigValidation:
    @pytest.mark.parametrize(
        "overrides",
        [
            {"lookback_sec": 0.0},
            {"lookback_sec": -1.0},
            {"history_window_sec": 1.0, "lookback_sec": 1.0},
            {"track_grace_sec": 0.0},
            {"min_samples": 0},
            {"distance_threshold": 0.0},
            {"closing_speed_threshold": 0.0},
            {"min_closing_speed_norm": -0.1},
            {"distance_weight": -0.1},
            {"speed_weight": -0.1},
            {"score_threshold": -0.1},
            {"score_threshold": 1.1},
        ],
    )
    def test_rejects_invalid_values(self, overrides):
        with pytest.raises(ValueError):
            _fast_config(**overrides)

    def test_from_file_reads_cause_attribution_section(self):
        config = FallCauseAttributorConfig.from_file("configs/fall_detection.json")

        assert config.enabled is True
        assert config.lookback_sec == 1.0
        assert config.history_window_sec == 4.0
        assert config.max_pairing_gap_frames == 1.5

    def test_from_file_defaults_when_section_missing(self, tmp_path):
        import json

        config_path = tmp_path / "no_cause_section.json"
        config_path.write_text(json.dumps({}), encoding="utf-8")

        config = FallCauseAttributorConfig.from_file(str(config_path))

        assert config == FallCauseAttributorConfig()


class TestFallCauseAttributorConstruction:
    def test_rejects_non_positive_fps(self):
        with pytest.raises(ValueError):
            FallCauseAttributor(fps=0.0)
        with pytest.raises(ValueError):
            FallCauseAttributor(fps=-1.0)


class TestNoCoOccurringObservationsRejected:
    """피해자·후보가 단 한 프레임도 동시에 관측되지 않았다면(관측 구간이

    서로 겹치지 않음), '가장 가까운 시각' 매칭만으로 근접·접근 근거를
    인위적으로 만들면 안 된다 — 실제로 재현된 회귀 케이스.
    """

    def test_no_overlapping_frames_returns_none_even_with_close_positions(self):
        """실제 파이프라인처럼 프레임 번호 오름차순(시간순)으로 update()를

        호출한다 — FallPipeline.process()는 항상 이 순서로 호출하므로,
        시간이 뒤섞인 입력은 실제로 발생하지 않는 상황을 테스트하는
        셈이 되어 오해를 준다.
        """
        attributor = FallCauseAttributor(fps=_FPS, config=_fast_config())

        # 피해자: frame 10, 20만 관측. 후보: frame 14, 16만 관측 — 동시 관측 프레임 0개.
        attributor.update(_result(10, [_track(1, 500.0)]))
        # 후보가 멀리(800)에서 가까이(505)로 '접근하는 것처럼' 보이지만
        # victim과 겹치는 관측 프레임이 전혀 없다.
        attributor.update(_result(14, [_track(2, 800.0)]))
        attributor.update(_result(16, [_track(2, 505.0)]))
        attributor.update(_result(20, [_track(1, 500.0)]))

        cause = attributor.attribute(_VIDEO_SOURCE, victim_track_id=1, fall_start_sec=2.0)

        assert cause is None

    def test_pairing_within_max_gap_still_works(self):
        """허용 간격(기본 1.5프레임=0.15초) 이내의 약간 어긋난 관측은

        여전히 정상적으로 짝지어져 근접 근거로 인정돼야 한다 — 버그
        수정이 정상 케이스까지 막지 않는지 확인한다.
        """
        attributor = FallCauseAttributor(fps=_FPS, config=_fast_config())

        # victim: 매 프레임(0.1초 간격), candidate: 1프레임(0.1초)씩 어긋나게 관측
        # (실제 감지 프레임 미스 등으로 흔히 발생) — gap이 0.1초로 허용 범위(0.15초) 이내.
        frame_tracks = {}
        for frame_number in range(10, 21):
            frame_tracks.setdefault(frame_number, []).append(_track(1, 500.0))
        t = 1.0
        while t <= 2.0 + 1e-9:
            candidate_x = 700.0 - (700.0 - 520.0) * ((t - 1.0) / 1.0)
            frame_number = round(t * _FPS) + 1  # victim과 1프레임씩 어긋나게 관측
            frame_tracks.setdefault(frame_number, []).append(_track(2, candidate_x))
            t += 0.2
        _feed_frames_in_order(attributor, frame_tracks)

        cause = attributor.attribute(_VIDEO_SOURCE, victim_track_id=1, fall_start_sec=2.0)

        assert cause is not None
        assert cause.track_id == 2

    def test_pairing_beyond_max_gap_is_excluded_from_matching(self):
        """max_pairing_gap_frames를 넘는 간격은 짝짓지 않아 min_samples

        미달로 cause=null이 돼야 한다 — 좁은 gap 설정으로 명시적으로 확인.
        """
        attributor = FallCauseAttributor(
            fps=_FPS, config=_fast_config(max_pairing_gap_frames=0.5)
        )
        # 후보가 victim과 2프레임(0.2초) 어긋나게만 관측됨 — gap(0.2초) >
        # max_pairing_gap_frames(0.5)/fps(10)=0.05초이므로 짝지어지지 않아야 한다.
        _feed_frames_in_order(
            attributor,
            {
                10: [_track(1, 500.0)],
                12: [_track(2, 505.0)],
                18: [_track(2, 505.0)],
                20: [_track(1, 500.0)],
            },
        )

        cause = attributor.attribute(_VIDEO_SOURCE, victim_track_id=1, fall_start_sec=2.0)

        assert cause is None


class TestMaxPairingGapConfigValidation:
    def test_rejects_non_positive_max_pairing_gap_frames(self):
        with pytest.raises(ValueError):
            _fast_config(max_pairing_gap_frames=0.0)
        with pytest.raises(ValueError):
            _fast_config(max_pairing_gap_frames=-1.0)


class TestSingleCandidateObservationNotReused:
    """후보 관측이 실질적으로 1개뿐이면(같은 샘플이 여러 victim 샘플에

    "가장 가까운 시각" 매칭으로 반복 재사용되는 상황이면), victim 자신의
    움직임만으로 마치 후보가 접근한 것처럼 보이는 근거가 만들어지면 안
    된다 — 실제로 재현된 회귀 케이스.
    """

    def test_victims_own_motion_toward_single_candidate_sample_is_not_cause(self):
        fps = 20.0
        attributor = FallCauseAttributor(fps=fps, config=_fast_config())

        # victim이 스스로 x=300(멀리)에서 x=110(가까이)으로 0.2초 동안
        # 빠르게 이동한다 — 후보는 전혀 움직이지 않는다.
        frame_tracks = {}
        for i, x in enumerate([300.0, 250.0, 150.0, 130.0, 110.0]):
            frame_number = round(i * 0.05 * fps)
            frame_tracks.setdefault(frame_number, []).append(_track(1, x))

        # 후보는 t=0.1(victim 근처, x=100)에 한 번, t=0.9(victim과 전혀
        # 겹치지 않는 먼 시각, 그러나 lookback window 안)에 한 번만 관측된다.
        # min_samples(2) 사전 필터는 통과하지만 실제로 victim과 "동시에"
        # 근접했던 관측은 t=0.1 하나뿐이다.
        frame_tracks.setdefault(round(0.1 * fps), []).append(_track(2, 100.0))
        frame_tracks.setdefault(round(0.9 * fps), []).append(_track(2, 100.0))
        _feed_frames_in_order(attributor, frame_tracks)

        cause = attributor.attribute(_VIDEO_SOURCE, victim_track_id=1, fall_start_sec=1.0)

        assert cause is None

    def test_two_genuinely_distinct_candidate_observations_still_work(self):
        """수정이 정상 케이스까지 막지 않는지 확인한다 — 후보가 실제로

        서로 다른 두 시각에 victim과 가깝게 관측되면 여전히 cause가 나와야 한다.
        """
        fps = 10.0
        attributor = FallCauseAttributor(fps=fps, config=_fast_config())

        frame_tracks = {}
        for frame_number in range(10, 21):
            frame_tracks.setdefault(frame_number, []).append(_track(1, 500.0))
        # 후보가 t=1.0(멀리)에서 t=2.0(가까이)까지 실제로 여러 프레임에 걸쳐 접근.
        t = 1.0
        while t <= 2.0 + 1e-9:
            candidate_x = 700.0 - (700.0 - 505.0) * ((t - 1.0) / 1.0)
            frame_tracks.setdefault(round(t * fps), []).append(_track(2, candidate_x))
            t += 0.2
        _feed_frames_in_order(attributor, frame_tracks)

        cause = attributor.attribute(_VIDEO_SOURCE, victim_track_id=1, fall_start_sec=2.0)

        assert cause is not None
        assert cause.track_id == 2
