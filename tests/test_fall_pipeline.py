"""FallDetector 행동 시나리오(파이프라인 통합) 테스트.

합성 Track sequence로 정상 행동에서 오탐이 없는지, 낙상이 확정됐을 때만
Event 1회가 발생하는지, cooldown·Track 소실·다중 Track·FPS가 달라졌을 때도
계약(docs/interfaces.md FALL_SUSPECT)이 지켜지는지 검증한다. 외부 데이터가
없는 CI에서도 실행 가능하도록 실제 영상은 사용하지 않는다.
"""

from __future__ import annotations

from typing import List, Tuple

from src.common.types import Track, TrackingResult
from src.safety.fall_detector import FallDetector, FallDetectorConfig

_STANDING_BBOX = (40.0, 0.0, 60.0, 60.0)  # width 20, height 60, aspect 0.33
_LYING_BBOX = (10.0, 50.0, 90.0, 70.0)  # width 80, height 20, aspect 4.0


def _fast_config(**overrides) -> FallDetectorConfig:
    cfg = FallDetectorConfig(cooldown_sec=1.0)
    for key, value in overrides.items():
        setattr(cfg, key, value)
    return cfg


def _foot_point(bbox: Tuple[float, float, float, float]) -> Tuple[float, float]:
    return ((bbox[0] + bbox[2]) / 2.0, bbox[3])


def _result(frame_number, bbox, video_source="cam1", track_id=1, confidence=0.9):
    return TrackingResult(
        frame_number=frame_number,
        timestamp="00:00:00.000",
        video_source=video_source,
        tracks=[
            Track(
                track_id=track_id,
                bbox=list(bbox),
                foot_point=list(_foot_point(bbox)),
                confidence=confidence,
            )
        ],
    )


def _interpolated_bboxes(start_bbox, end_bbox, steps) -> List[Tuple[float, float, float, float]]:
    """steps+1개의 bbox를 반환한다 (start_bbox 포함, end_bbox로 선형 보간)."""
    bboxes = []
    for i in range(steps + 1):
        ratio = i / steps
        bboxes.append(tuple(s + (e - s) * ratio for s, e in zip(start_bbox, end_bbox)))
    return bboxes


def _run(detector: FallDetector, bboxes, start_frame=0, video_source="cam1", track_id=1):
    events = []
    for offset, bbox in enumerate(bboxes):
        events += detector.process(
            _result(start_frame + offset, bbox, video_source=video_source, track_id=track_id)
        )
    return events


class TestNormalActivityNoEvent:
    def test_walking_produces_no_event(self):
        """제자리에서 좌우로 천천히 걷는 동안(자세 변화 없음) Event가 없어야 한다."""
        fps = 10.0
        detector = FallDetector(fps=fps, config=_fast_config())

        bboxes = []
        for i in range(40):
            dx = (i % 10) * 1.0  # 느린 좌우 이동, 자세(aspect ratio) 변화 없음
            bboxes.append((40.0 + dx, 0.0, 60.0 + dx, 60.0))

        events = _run(detector, bboxes)
        assert events == []

    def test_running_produces_no_event(self):
        """뛰기: 걷기보다 빠르지만 자세는 계속 서 있는 형태를 유지한다."""
        fps = 10.0
        detector = FallDetector(fps=fps, config=_fast_config())

        bboxes = []
        for i in range(40):
            dx = (i % 5) * 4.0  # 걷기보다 빠른 수평 이동
            bboxes.append((40.0 + dx, 0.0, 60.0 + dx, 60.0))

        events = _run(detector, bboxes)
        assert events == []

    def test_sitting_down_gradually_produces_no_event(self):
        """천천히 앉는 동작(0.5초에 걸친 완만한 높이 감소)은 오탐이 없어야 한다."""
        fps = 10.0
        detector = FallDetector(fps=fps, config=_fast_config())

        standing = _STANDING_BBOX
        sitting = (35.0, 20.0, 65.0, 60.0)  # width 30, height 40, aspect 0.75 (여전히 서 있는 비율)
        bboxes = [standing] * 5 + _interpolated_bboxes(standing, sitting, steps=5) + [sitting] * 20

        events = _run(detector, bboxes)
        assert events == []

    def test_kneeling_produces_no_event(self):
        fps = 10.0
        detector = FallDetector(fps=fps, config=_fast_config())

        standing = _STANDING_BBOX
        kneeling = (35.0, 15.0, 65.0, 60.0)  # width 30, height 45, aspect 0.67
        bboxes = (
            [standing] * 5 + _interpolated_bboxes(standing, kneeling, steps=5) + [kneeling] * 20
        )

        events = _run(detector, bboxes)
        assert events == []

    def test_picking_up_object_produces_no_event(self):
        fps = 10.0
        detector = FallDetector(fps=fps, config=_fast_config())

        standing = _STANDING_BBOX
        bending = (32.0, 25.0, 68.0, 60.0)  # width 36, height 35, aspect ~1.03 (임계값 1.3 미만)
        bboxes = (
            [standing] * 5
            + _interpolated_bboxes(standing, bending, steps=5)
            + [bending] * 10
            + _interpolated_bboxes(bending, standing, steps=5)
            + [standing] * 10
        )

        events = _run(detector, bboxes)
        assert events == []


class TestTemporallySeparatedEvidence:
    """candidate 진입(동적 근거)과 confirm(수평 자세 지속)이 서로 다른 시점에

    나타나는 실제 CAUCAFall 낙상 패턴을 재현한다 (Subject 1 Fall backwards
    개발 데이터: 높이 수축/하강은 frame 68~71, 수평 자세는 frame 75+에야
    도달 — 같은 프레임에 동시 발생하지 않음).
    """

    _CROUCH_BBOX = (38.0, 35.0, 62.0, 60.0)  # width 24, height 25, aspect 0.96 (수평 아님)
    _DESCENT_ONLY_BBOX = (40.0, 20.0, 60.0, 80.0)  # width 20, height 60 (표준 유지), 아래로 이동만

    def test_height_shrink_then_later_horizontal_posture_confirms(self):
        """높이 수축(candidate 진입) 후 몇 프레임 뒤 수평 자세가 지속되면 확정돼야 한다."""
        fps = 10.0
        detector = FallDetector(fps=fps, config=_fast_config())

        events = []
        events += _run(detector, [_STANDING_BBOX] * 5)  # age gate
        events += detector.process(_result(5, self._CROUCH_BBOX))  # height_shrink만 트리거
        assert events == []  # candidate 진입, 아직 수평 아님

        # 수평이 아닌 채로 몇 프레임 더 유지 (동적 근거와 수평 자세 사이 간격 재현)
        for frame_number in range(6, 10):
            events += detector.process(_result(frame_number, self._CROUCH_BBOX))
        assert events == []

        events += detector.process(_result(10, _LYING_BBOX))  # 이제서야 수평 자세 시작
        for frame_number in range(11, 16):
            events += detector.process(_result(frame_number, _LYING_BBOX))

        assert len(events) == 1
        assert events[0].event_type == "FALL_SUSPECT"

    def test_descent_then_later_horizontal_posture_confirms(self):
        """하강 속도(candidate 진입) 후 몇 프레임 뒤 수평 자세가 지속되면 확정돼야 한다."""
        fps = 10.0
        detector = FallDetector(fps=fps, config=_fast_config())

        events = []
        events += _run(detector, [_STANDING_BBOX] * 5)
        events += detector.process(_result(5, self._DESCENT_ONLY_BBOX))  # descent만 트리거
        assert events == []

        for frame_number in range(6, 10):
            events += detector.process(_result(frame_number, self._DESCENT_ONLY_BBOX))
        assert events == []

        events += detector.process(_result(10, _LYING_BBOX))
        for frame_number in range(11, 16):
            events += detector.process(_result(frame_number, _LYING_BBOX))

        assert len(events) == 1

    def test_horizontal_posture_without_dynamic_evidence_never_confirms(self):
        """동적 근거(하강/높이수축) 없이 아주 완만하게(30 step) 수평 자세에 도달해도

        candidate 자체에 진입하지 않으므로 Event가 없어야 한다.
        """
        fps = 10.0
        detector = FallDetector(fps=fps, config=_fast_config())

        bboxes = [_STANDING_BBOX] * 5 + _interpolated_bboxes(
            _STANDING_BBOX, _LYING_BBOX, steps=30
        )
        events = _run(detector, bboxes)
        # 30 step에 걸친 완만한 전환이라 각 프레임의 순간 변화율은 임계값 미만이어야 한다.
        events += _run(detector, [_LYING_BBOX] * 10, start_frame=len(bboxes))

        assert events == []

    def test_descent_only_without_reaching_horizontal_posture_times_out(self):
        """candidate에 진입했어도 수평 자세에 끝내 도달하지 못하면 timeout 후 Event가 없어야 한다."""
        fps = 10.0
        detector = FallDetector(fps=fps, config=_fast_config(fall_candidate_timeout_sec=1.0))

        events = []
        events += _run(detector, [_STANDING_BBOX] * 5)
        events += detector.process(_result(5, self._DESCENT_ONLY_BBOX))
        assert events == []

        # fall_candidate_timeout_sec(1.0초=10frame)를 넘도록 수평 자세 없이 유지
        for frame_number in range(6, 20):
            events += detector.process(_result(frame_number, self._DESCENT_ONLY_BBOX))

        assert events == []

    def test_height_shrink_only_without_reaching_horizontal_posture_times_out(self):
        fps = 10.0
        detector = FallDetector(fps=fps, config=_fast_config(fall_candidate_timeout_sec=1.0))

        events = []
        events += _run(detector, [_STANDING_BBOX] * 5)
        events += detector.process(_result(5, self._CROUCH_BBOX))
        assert events == []

        for frame_number in range(6, 20):
            events += detector.process(_result(frame_number, self._CROUCH_BBOX))

        assert events == []


class TestRapidDescentWithRecoveryDoesNotConfirm:
    def test_quick_crouch_and_stand_back_up_is_not_confirmed(self):
        """급격히 내려갔다가(candidate 진입) 빠르게 회복하면 confirmed까지 가지 않아야 한다."""
        fps = 10.0
        detector = FallDetector(fps=fps, config=_fast_config())

        standing = _STANDING_BBOX
        # 한 frame만에 급격히 낮아지되, 눕지는 않는 자세(aspect < horizontal 임계값)
        crouched = (38.0, 40.0, 62.0, 60.0)  # width 24, height 20, aspect 1.2 (horizontal 임계값 미만)

        events = []
        events += _run(detector, [standing] * 5)
        events += detector.process(_result(5, crouched))  # candidate 진입 가능성 있는 급격한 변화
        # 곧바로 회복 (aspect < normal_aspect_ratio_threshold, 속도도 진정)
        events += detector.process(_result(6, standing))
        for frame_number in range(7, 20):
            events += detector.process(_result(frame_number, standing))

        assert events == []


class TestCooldownPreventsDuplicateEvents:
    def test_confirmed_fall_then_continued_lying_does_not_refire(self):
        fps = 10.0
        detector = FallDetector(fps=fps, config=_fast_config(cooldown_sec=0.5))

        events = []
        events += _run(detector, [_STANDING_BBOX] * 5)
        events += detector.process(_result(5, _LYING_BBOX))
        for frame_number in range(6, 11):
            events += detector.process(_result(frame_number, _LYING_BBOX))
        assert len(events) == 1  # FALL_CONFIRMED 1회

        # cooldown_sec(0.5초=5frame) 동안 계속 누워 있어도 재발생하지 않는다.
        for frame_number in range(11, 16):
            events += detector.process(_result(frame_number, _LYING_BBOX))
        assert len(events) == 1

    def test_continuing_to_lie_after_cooldown_expires_does_not_refire(self):
        """cooldown 만료 후에도 계속 누워 있으면 재감지하지 않는다."""
        fps = 10.0
        detector = FallDetector(fps=fps, config=_fast_config(cooldown_sec=0.3))

        events = []
        events += _run(detector, [_STANDING_BBOX] * 5)
        events += detector.process(_result(5, _LYING_BBOX))
        for frame_number in range(6, 11):
            events += detector.process(_result(frame_number, _LYING_BBOX))
        assert len(events) == 1

        # cooldown_sec(0.3초=3frame) 만료 후에도 20frame(2초) 더 누워 있는다.
        for frame_number in range(11, 31):
            events += detector.process(_result(frame_number, _LYING_BBOX))
        assert len(events) == 1

    def test_recovery_after_cooldown_allows_new_detection(self):
        """cooldown 만료 후 회복 자세를 확인해야 NORMAL로 돌아가고, 그 후 재낙상은 새 Event로 기록된다."""
        fps = 10.0
        detector = FallDetector(fps=fps, config=_fast_config(cooldown_sec=0.3))

        events = []
        events += _run(detector, [_STANDING_BBOX] * 5)
        events += detector.process(_result(5, _LYING_BBOX))
        for frame_number in range(6, 11):
            events += detector.process(_result(frame_number, _LYING_BBOX))
        assert len(events) == 1

        # cooldown 만료(0.3초=3frame) 이후 회복 자세로 전환
        for frame_number in range(11, 15):
            events += detector.process(_result(frame_number, _STANDING_BBOX))
        assert len(events) == 1  # 아직 새 낙상 없음

        # 다시 정지 상태를 충분히 유지해 track_age 게이트를 재충족한 뒤 두 번째로 낙상
        for frame_number in range(15, 20):
            events += detector.process(_result(frame_number, _STANDING_BBOX))
        events += detector.process(_result(20, _LYING_BBOX))
        for frame_number in range(21, 26):
            events += detector.process(_result(frame_number, _LYING_BBOX))

        assert len(events) == 2  # 회복 후 재낙상은 새 Event로 기록되어야 한다


class TestMultiTrackIndependence:
    def test_two_tracks_in_same_video_source_are_independent(self):
        fps = 10.0
        detector = FallDetector(fps=fps, config=_fast_config())

        def frame(frame_number, bbox_1, bbox_2):
            return TrackingResult(
                frame_number=frame_number,
                timestamp="00:00:00.000",
                video_source="cam1",
                tracks=[
                    Track(
                        track_id=1,
                        bbox=list(bbox_1),
                        foot_point=list(_foot_point(bbox_1)),
                        confidence=0.9,
                    ),
                    Track(
                        track_id=2,
                        bbox=list(bbox_2),
                        foot_point=list(_foot_point(bbox_2)),
                        confidence=0.9,
                    ),
                ],
            )

        events = []
        for frame_number in range(5):
            events += detector.process(frame(frame_number, _STANDING_BBOX, _STANDING_BBOX))

        # track 1만 낙상, track 2는 계속 서 있음
        events += detector.process(frame(5, _LYING_BBOX, _STANDING_BBOX))
        for frame_number in range(6, 11):
            events += detector.process(frame(frame_number, _LYING_BBOX, _STANDING_BBOX))

        assert len(events) == 1
        assert events[0].track_id == 1


class TestVideoSourceIndependence:
    def test_same_track_id_different_video_source_are_independent(self):
        fps = 10.0
        detector = FallDetector(fps=fps, config=_fast_config())

        events = []
        events += _run(detector, [_STANDING_BBOX] * 5, video_source="cam1", track_id=1)
        events += _run(detector, [_STANDING_BBOX] * 5, video_source="cam2", track_id=1)

        events += detector.process(_result(5, _LYING_BBOX, video_source="cam1", track_id=1))
        for frame_number in range(6, 11):
            events += detector.process(
                _result(frame_number, _LYING_BBOX, video_source="cam1", track_id=1)
            )
        # cam2의 동일 track_id=1은 계속 서 있는 상태 → 영향받지 않아야 한다
        for frame_number in range(5, 11):
            events += detector.process(
                _result(frame_number, _STANDING_BBOX, video_source="cam2", track_id=1)
            )

        assert len(events) == 1
        assert events[0].video_source == "cam1"


class TestTrackGraceRecovery:
    def test_track_lost_within_grace_period_keeps_candidate_progress(self):
        """짧게 track이 끊겨도(grace period 이내) candidate 진행 상태가 유지돼야 한다."""
        fps = 10.0
        detector = FallDetector(fps=fps, config=_fast_config(track_grace_sec=0.5))

        events = []
        events += _run(detector, [_STANDING_BBOX] * 5)
        events += detector.process(_result(5, _LYING_BBOX))

        # frame 6~7 (0.2초) 동안 이 track이 잠깐 감지되지 않음 (grace_sec=0.5초 이내)
        for frame_number in range(6, 8):
            detector.process(
                TrackingResult(
                    frame_number=frame_number,
                    timestamp="00:00:00.000",
                    video_source="cam1",
                    tracks=[],
                )
            )

        # 다시 나타나 누운 자세를 이어감. 재등장 프레임(8) 자체는 소실 구간이
        # 섞인 raw_dt라 지속시간에 포함되지 않으므로(_visible_step_dt), 그 뒤로
        # fall_confirm_sec(0.5초)만큼 더 관측돼야 confirm된다 (frame 9~13에서 0.5초).
        for frame_number in range(8, 14):
            events += detector.process(_result(frame_number, _LYING_BBOX))

        assert len(events) == 1

    def test_invisible_gap_time_does_not_count_toward_lying_duration(self):
        """Track 소실 구간은 누운 자세 지속시간(fall_confirm_sec)에 포함되면 안 된다.

        candidate 진입 직후 grace period 이내로 짧게 사라졌다가 다시 나타난
        경우, 소실된 시간까지 지속시간으로 인정하면 재등장하자마자
        (실제로 눈으로 관측된 누운 시간은 훨씬 짧은데도) confirm되어 버린다.
        """
        fps = 10.0
        detector = FallDetector(fps=fps, config=_fast_config(track_grace_sec=0.5))

        events = []
        events += _run(detector, [_STANDING_BBOX] * 5)  # frame 0~4, t=0.0~0.4
        events += detector.process(_result(5, _LYING_BBOX))  # t=0.5, candidate 진입

        # frame 6~9 (0.4초) 동안 track 소실 (grace_sec=0.5초 이내이므로 상태는 유지됨)
        for frame_number in range(6, 10):
            detector.process(
                TrackingResult(
                    frame_number=frame_number,
                    timestamp="00:00:00.000",
                    video_source="cam1",
                    tracks=[],
                )
            )

        # 재등장 직후(t=1.0) 시점: wall-clock으로는 candidate 진입(t=0.5)로부터
        # 0.5초가 지났지만, 실제 관측된 누운 시간은 0에 가까우므로 아직 confirm되면 안 된다.
        events += detector.process(_result(10, _LYING_BBOX))
        assert events == []

        # 실제로 눈에 보이는 상태로 fall_confirm_sec(0.5초)만큼 더 누워 있어야 confirm된다.
        # 재등장(frame 10) 이후 5개 관측 프레임(0.1초씩, frame 11~15)이 지난
        # frame 15에서 정확히 confirm되어야 한다 (frame 13처럼 소실 시간이 일부
        # 새어 들어가 조기 confirm되면 안 된다).
        for frame_number in range(11, 15):
            events += detector.process(_result(frame_number, _LYING_BBOX))
        assert events == []

        events += detector.process(_result(15, _LYING_BBOX))
        assert len(events) == 1


class TestFpsInvariance:
    def test_confirm_timing_is_based_on_seconds_not_frame_count(self):
        """FPS가 달라도 fall_confirm_sec(초) 기준 confirm 시점은 동일해야 한다."""
        for fps in (10.0, 30.0):
            detector = FallDetector(fps=fps, config=_fast_config())
            standing_frames = max(5, int(0.5 * fps))
            events = _run(detector, [_STANDING_BBOX] * standing_frames)

            frame_number = standing_frames
            events += detector.process(_result(frame_number, _LYING_BBOX))

            confirm_frame_count = int(round(0.5 * fps))
            for offset in range(1, confirm_frame_count + 1):
                events += detector.process(_result(frame_number + offset, _LYING_BBOX))

            assert len(events) == 1, f"fps={fps}에서 예상과 다른 Event 개수: {len(events)}"


class TestEventContract:
    def test_confirmed_event_matches_fall_suspect_contract(self):
        fps = 10.0
        detector = FallDetector(fps=fps, config=_fast_config())

        events = []
        events += _run(detector, [_STANDING_BBOX] * 5)
        events += detector.process(_result(5, _LYING_BBOX))
        for frame_number in range(6, 11):
            events += detector.process(_result(frame_number, _LYING_BBOX))

        assert len(events) == 1
        event = events[0]
        assert event.event_type == "FALL_SUSPECT"
        assert event.zone_id == "__global__"
        assert event.cause is None
        assert event.event_confidence is not None
        assert 0.0 <= event.event_confidence <= 1.0
