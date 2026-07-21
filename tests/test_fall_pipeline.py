"""FallDetector 행동 시나리오(파이프라인 통합) 테스트.

합성 Track sequence로 정상 행동에서 오탐이 없는지, 낙상이 확정됐을 때만
Event 1회가 발생하는지, cooldown·Track 소실·다중 Track·FPS가 달라졌을 때도
계약(docs/interfaces.md FALL_SUSPECT)이 지켜지는지 검증한다. 외부 데이터가
없는 CI에서도 실행 가능하도록 실제 영상은 사용하지 않는다.
"""

from __future__ import annotations

from typing import List, Tuple

import pytest

from src.common.types import Track, TrackingResult
from src.safety.fall_detector import FallDetector, FallDetectorConfig
from src.safety.fall_model_matching import FallModelEvidence

_STANDING_BBOX = (40.0, 0.0, 60.0, 60.0)  # width 20, height 60, aspect 0.33
_LYING_BBOX = (10.0, 50.0, 90.0, 70.0)  # width 80, height 20, aspect 4.0


def _fast_config(**overrides) -> FallDetectorConfig:
    values = {"cooldown_sec": 1.0}
    values.update(overrides)
    return FallDetectorConfig(**values)


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


# PoseFeatureExtractor는 코(0)와 엉덩이(11, 12) keypoint로 head_hip_diff_norm을 계산한다.
_STANDING_KEYPOINTS = {0: (50.0, 10.0), 11: (50.0, 40.0), 12: (50.0, 40.0)}
_LYING_KEYPOINTS = {0: (50.0, 75.0), 11: (50.0, 45.0), 12: (50.0, 45.0)}


def _result_with_keypoints(
    frame_number,
    bbox,
    keypoints_by_index,
    video_source="cam1",
    track_id=1,
    confidence=0.9,
    keypoint_conf=1.0,
):
    keypoints = [[0.0, 0.0]] * 17
    keypoints_conf = [0.0] * 17
    for idx, xy in keypoints_by_index.items():
        keypoints[idx] = list(xy)
        keypoints_conf[idx] = keypoint_conf
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
                keypoints=keypoints,
                keypoints_conf=keypoints_conf,
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

    def test_single_recovered_frame_after_cooldown_does_not_trigger_premature_normal(self):
        """cooldown 만료 후 회복 조건을

        만족하는 프레임이 "단 한 번"만 와도 그것만으로 NORMAL로 전이하면
        안 된다 — 실측에서는 모델이 한 프레임만 "unknown"을 반환한 순간
        (aspect_ratio는 여전히 낮아 실제 회복 기준에도 못 미쳤다) 즉시
        NORMAL로 전이했고, 곧바로 fall 근거가 재개되며 재확정돼 중복
        Event가 생겼다. `_advance_candidate`의 recovery 판정과 동일하게
        recovery_confirm_sec 이상 연속돼야 실제로 NORMAL로 전이해야 한다.
        """
        fps = 10.0
        # y 범위는 _LYING_BBOX와 동일하게 유지해(center_vertical_velocity가
        # 0에 가깝도록) aspect_ratio만 정상 범위로 떨어뜨린 한 프레임을
        # 만든다 — 속도 게이트가 아니라 지속시간 게이트를 정확히 검증하기
        # 위함이다.
        narrow_same_y = (43.0, 50.0, 57.0, 70.0)  # aspect 0.7 < normal_aspect_ratio_threshold

        detector = FallDetector(fps=fps, config=_fast_config(cooldown_sec=0.3))

        events = []
        events += _run(detector, [_STANDING_BBOX] * 5)
        events += detector.process(_result(5, _LYING_BBOX))
        for frame_number in range(6, 11):
            events += detector.process(_result(frame_number, _LYING_BBOX))
        assert len(events) == 1

        # cooldown 만료(0.3초) 이후에도 계속 누워 있다가...
        for frame_number in range(11, 16):
            events += detector.process(_result(frame_number, _LYING_BBOX))
        assert detector._states[("cam1", 1)].state == "COOLDOWN"

        # ...단 한 프레임만 회복 조건을 만족한 뒤 곧바로 다시 눕는다.
        events += detector.process(_result(16, narrow_same_y))
        assert detector._states[("cam1", 1)].state == "COOLDOWN"  # 아직 NORMAL 아님
        events += detector.process(_result(17, _LYING_BBOX))
        assert detector._states[("cam1", 1)].state == "COOLDOWN"

        for frame_number in range(18, 25):
            events += detector.process(_result(frame_number, _LYING_BBOX))

        assert len(events) == 1  # 중복 Event가 생기면 안 된다


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


class TestPoseConfirmation:
    """pose keypoint가 있는 Track에서 confirm 경로(수평 자세 OR pose 기울기)가

    올바르게 동작하는지 검증한다. bbox aspect_ratio 경로가 끝까지 임계값을
    넘지 못하는 CAUCAFall Fall forward 패턴(docs/fall_evaluation.md 참고)을
    합성 데이터로 재현한다.
    """

    _NON_HORIZONTAL_BBOX = (40.0, 20.0, 60.0, 80.0)  # aspect 0.33, bbox 경로로는 확정 불가

    def test_pose_confirms_fall_that_bbox_alone_misses(self):
        fps = 10.0
        detector = FallDetector(fps=fps, config=_fast_config())

        events = []
        for frame_number in range(5):
            events += detector.process(
                _result_with_keypoints(frame_number, _STANDING_BBOX, _STANDING_KEYPOINTS)
            )
        # bbox 동적 근거(하강)로 candidate 진입. keypoints는 아직 서 있는 자세.
        events += detector.process(
            _result_with_keypoints(5, self._NON_HORIZONTAL_BBOX, _STANDING_KEYPOINTS)
        )
        assert events == []

        # bbox는 계속 비수평이지만 pose는 누운 자세로 전환되어 지속됨.
        for frame_number in range(6, 11):
            events += detector.process(
                _result_with_keypoints(frame_number, self._NON_HORIZONTAL_BBOX, _LYING_KEYPOINTS)
            )

        assert len(events) == 1
        assert events[0].event_type == "FALL_SUSPECT"

    def test_without_pose_same_bbox_sequence_never_confirms(self):
        """keypoints가 없는(pose 신호 없음) 동일 bbox 시퀀스는 기존 aspect 기반

        회복 조건이 그대로 적용되어 확정되지 않아야 한다 (위 테스트와의 대조).
        """
        fps = 10.0
        detector = FallDetector(fps=fps, config=_fast_config())

        events = []
        events += _run(detector, [_STANDING_BBOX] * 5)
        events += detector.process(_result(5, self._NON_HORIZONTAL_BBOX))
        for frame_number in range(6, 11):
            events += detector.process(_result(frame_number, self._NON_HORIZONTAL_BBOX))

        assert events == []

    def test_brief_pose_tilt_without_sustained_duration_does_not_confirm(self):
        fps = 10.0
        detector = FallDetector(fps=fps, config=_fast_config())

        events = []
        events += _run(detector, [_STANDING_BBOX] * 5)
        events += detector.process(
            _result_with_keypoints(5, self._NON_HORIZONTAL_BBOX, _STANDING_KEYPOINTS)
        )
        assert events == []

        # 1프레임만 누운 pose, 곧바로 다시 서 있는 pose로 복귀 (지속시간 미달)
        events += detector.process(
            _result_with_keypoints(6, self._NON_HORIZONTAL_BBOX, _LYING_KEYPOINTS)
        )
        for frame_number in range(7, 20):
            events += detector.process(
                _result_with_keypoints(
                    frame_number, self._NON_HORIZONTAL_BBOX, _STANDING_KEYPOINTS
                )
            )

        assert events == []


def _fall_evidence(track_id=1, confidence=0.9, iou=0.9) -> dict:
    return {
        track_id: FallModelEvidence(
            track_id=track_id, label="fall", confidence=confidence, iou=iou
        )
    }


def _nofall_evidence(track_id=1, confidence=0.9, iou=0.9) -> dict:
    return {
        track_id: FallModelEvidence(
            track_id=track_id, label="nofall", confidence=confidence, iou=iou
        )
    }


def _unknown_evidence(track_id=1) -> dict:
    return {
        track_id: FallModelEvidence(track_id=track_id, label="unknown", confidence=None, iou=None)
    }


class TestModelConfirmation:
    """fine-tuned fall/nofall 모델 근거(FallModelEvidence)가 있는 Track에서

    confirm 경로(수평 자세 OR pose OR 모델)가 올바르게 동작하는지 검증한다.
    bbox aspect_ratio 경로가 끝까지 임계값을 넘지 못하는 패턴을 합성 데이터로
    재현한다 — TestPoseConfirmation과 동일한 구조.
    """

    _NON_HORIZONTAL_BBOX = (40.0, 20.0, 60.0, 80.0)  # aspect 0.33, bbox 경로로는 확정 불가

    def test_model_confirms_fall_that_bbox_alone_misses(self):
        fps = 10.0
        config = _fast_config(model_confirm_sec=0.5, model_vote_window_sec=0.5)
        detector = FallDetector(fps=fps, config=config)

        events = []
        events += _run(detector, [_STANDING_BBOX] * 5)
        # bbox 동적 근거(하강)로 candidate 진입. 모델은 아직 fall 근거 없음.
        events += detector.process(_result(5, self._NON_HORIZONTAL_BBOX))
        assert events == []

        # bbox는 계속 비수평이지만 모델이 fall로 지속 판정.
        for frame_number in range(6, 11):
            events += detector.process(
                _result(frame_number, self._NON_HORIZONTAL_BBOX),
                model_evidence=_fall_evidence(),
            )

        assert len(events) == 1
        assert events[0].event_type == "FALL_SUSPECT"

    def test_without_model_evidence_same_bbox_sequence_never_confirms(self):
        """model_evidence를 아예 전달하지 않으면(None) 기존 bbox 전용 동작과

        동일해야 한다 — 이 경로가 완전히 비활성화된다.
        """
        fps = 10.0
        detector = FallDetector(fps=fps, config=_fast_config())

        events = []
        events += _run(detector, [_STANDING_BBOX] * 5)
        events += detector.process(_result(5, self._NON_HORIZONTAL_BBOX))
        for frame_number in range(6, 11):
            events += detector.process(_result(frame_number, self._NON_HORIZONTAL_BBOX))

        assert events == []

    def test_brief_model_fall_without_sustained_duration_does_not_confirm(self):
        fps = 10.0
        config = _fast_config(model_confirm_sec=0.5, model_vote_window_sec=0.5)
        detector = FallDetector(fps=fps, config=config)

        events = []
        events += _run(detector, [_STANDING_BBOX] * 5)
        events += detector.process(_result(5, self._NON_HORIZONTAL_BBOX))
        assert events == []

        # 1프레임만 fall 판정, 나머지는 계속 nofall (윈도우 안에서도 근거 총합이 미달)
        events += detector.process(
            _result(6, self._NON_HORIZONTAL_BBOX), model_evidence=_fall_evidence()
        )
        for frame_number in range(7, 20):
            events += detector.process(
                _result(frame_number, self._NON_HORIZONTAL_BBOX),
                model_evidence=_nofall_evidence(),
            )

        assert events == []

    def test_intermittent_nofall_does_not_prevent_confirm_within_window(self):
        """간헐적 nofall이 섞여도 윈도우 안에서 fall 근거 총합만 채우면 confirm돼야

        한다 — 단일 nofall 프레임에 전체를 리셋하던 이전 방식과의 핵심 차이.
        Development 실측(docs/fall_evaluation.md 참고)에서 모델이 fall/nofall
        사이를 자주 오가 연속
        누적 방식으로는 Event Recall이 크게 낮았던 문제를 해결하기 위한 설계다.
        """
        fps = 10.0
        config = _fast_config(model_confirm_sec=0.5, model_vote_window_sec=1.0)
        detector = FallDetector(fps=fps, config=config)

        events = []
        events += _run(detector, [_STANDING_BBOX] * 5)
        events += detector.process(_result(5, self._NON_HORIZONTAL_BBOX))

        # fall 6프레임(0.6초) + nofall 2프레임 간섭 -> 부동소수점 경계 여유를 위해
        # 문턱(0.5초)보다 살짝 더 채운다.
        sequence = ["fall", "fall", "nofall", "fall", "fall", "nofall", "fall", "fall"]
        for offset, label in enumerate(sequence):
            frame_number = 6 + offset
            evidence = _fall_evidence() if label == "fall" else _nofall_evidence()
            events += detector.process(
                _result(frame_number, self._NON_HORIZONTAL_BBOX), model_evidence=evidence
            )

        assert len(events) == 1
        assert events[0].event_type == "FALL_SUSPECT"

    def test_evidence_outside_window_no_longer_counts(self):
        """model_vote_window_sec보다 오래된 fall 근거는 자동으로 제외돼야 한다."""
        fps = 10.0
        config = _fast_config(model_confirm_sec=0.3, model_vote_window_sec=0.5)
        detector = FallDetector(fps=fps, config=config)

        events = []
        events += _run(detector, [_STANDING_BBOX] * 5)
        events += detector.process(_result(5, self._NON_HORIZONTAL_BBOX))
        for frame_number in range(6, 8):  # fall 0.2초 (윈도우 안에서는 아직 0.3초 미달)
            events += detector.process(
                _result(frame_number, self._NON_HORIZONTAL_BBOX),
                model_evidence=_fall_evidence(),
            )
        assert events == []

        # unknown을 window_sec(0.5초)보다 길게 흘려보내 앞선 fall 근거를 만료시킨다.
        for frame_number in range(8, 13):
            events += detector.process(
                _result(frame_number, self._NON_HORIZONTAL_BBOX),
                model_evidence=_unknown_evidence(),
            )
        assert events == []

        # 만료된 뒤 fall 근거 1프레임(0.1초)만 추가 -> 0.3초 문턱에 못 미쳐야 한다.
        events += detector.process(
            _result(13, self._NON_HORIZONTAL_BBOX), model_evidence=_fall_evidence()
        )
        assert events == []

    def test_brief_unknown_before_window_expiry_does_not_clear_evidence(self):
        """윈도우가 만료되기 전의 짧은 unknown은 이미 쌓인 근거를 지우면 안 된다."""
        fps = 10.0
        config = _fast_config(model_confirm_sec=0.5, model_vote_window_sec=1.0)
        detector = FallDetector(fps=fps, config=config)

        events = []
        events += _run(detector, [_STANDING_BBOX] * 5)
        events += detector.process(_result(5, self._NON_HORIZONTAL_BBOX))
        for frame_number in range(6, 9):  # 0.3초 fall 누적
            events += detector.process(
                _result(frame_number, self._NON_HORIZONTAL_BBOX),
                model_evidence=_fall_evidence(),
            )
        assert events == []

        # unknown 1프레임 (윈도우 1.0초 안에서는 근거가 그대로 유지돼야 함)
        events += detector.process(
            _result(9, self._NON_HORIZONTAL_BBOX), model_evidence=_unknown_evidence()
        )
        # 다시 fall로 이어져 나머지 0.2초를 채우면 confirm돼야 한다.
        for frame_number in range(10, 13):
            events += detector.process(
                _result(frame_number, self._NON_HORIZONTAL_BBOX),
                model_evidence=_fall_evidence(),
            )

        assert len(events) == 1

    def test_model_fall_suppresses_recovery(self):
        """모델이 fall로 보는 동안에는 aspect_ratio 기반 회복 조건이 만족돼도

        candidate가 초기화되지 않아야 한다 (pose와 동일한 정책).
        """
        fps = 10.0
        config = _fast_config(model_confirm_sec=0.5, model_vote_window_sec=0.5)
        detector = FallDetector(fps=fps, config=config)

        events = []
        events += _run(detector, [_STANDING_BBOX] * 5)
        events += detector.process(_result(5, self._NON_HORIZONTAL_BBOX))
        # 회복 조건을 만족하는 STANDING_BBOX로 돌아가지만, 모델은 계속 fall이라고 함.
        for frame_number in range(6, 11):
            events += detector.process(
                _result(frame_number, _STANDING_BBOX), model_evidence=_fall_evidence()
            )

        assert len(events) == 1

    def test_model_fall_prevents_early_cooldown_exit_and_duplicate_event(self):
        """cooldown 만료 후에도 모델이 fall로 보는 동안에는 NORMAL로 조기 전이해

        재확정(중복 Event)이 발생하면 안 된다 — 이전에 겪은 cooldown
        pose-blindness와 동일한 문제를 모델 경로에서도 검증한다
        (docs/fall_evaluation.md 참고).
        """
        fps = 10.0
        config = _fast_config(cooldown_sec=0.3, model_confirm_sec=0.5, model_vote_window_sec=0.5)
        detector = FallDetector(fps=fps, config=config)

        events = []
        events += _run(detector, [_STANDING_BBOX] * 5)
        events += detector.process(_result(5, self._NON_HORIZONTAL_BBOX))
        for frame_number in range(6, 11):
            events += detector.process(
                _result(frame_number, self._NON_HORIZONTAL_BBOX),
                model_evidence=_fall_evidence(),
            )
        assert len(events) == 1  # 최초 confirm

        # cooldown_sec(0.3초)을 넘겨도 모델이 계속 fall이라고 하면 재확정되면 안 된다.
        for frame_number in range(11, 30):
            events += detector.process(
                _result(frame_number, self._NON_HORIZONTAL_BBOX),
                model_evidence=_fall_evidence(),
            )

        assert len(events) == 1  # 여전히 1건

    def test_track_missing_from_evidence_dict_is_treated_as_unknown_not_disabled(self):
        """model_evidence 딕셔너리 자체는 전달됐지만 이 track_id가 빠져 있으면

        "모델을 안 쓴다"(None)가 아니라 "unknown"으로 취급해야 한다. 빈 딕셔너리를
        계속 전달해도(track_id가 한 번도 채워지지 않음) 결국 윈도우가 만료돼
        confirm되지 않아야 한다.
        """
        fps = 10.0
        config = _fast_config(model_confirm_sec=0.3, model_vote_window_sec=0.5)
        detector = FallDetector(fps=fps, config=config)

        events = []
        events += _run(detector, [_STANDING_BBOX] * 5)
        events += detector.process(_result(5, self._NON_HORIZONTAL_BBOX))
        for frame_number in range(6, 8):  # fall 0.2초로 진행
            events += detector.process(
                _result(frame_number, self._NON_HORIZONTAL_BBOX),
                model_evidence=_fall_evidence(),
            )
        assert events == []

        # 이 Track(track_id=1)이 빠진 빈 딕셔너리를 계속 전달 -> unknown 취급
        # -> window_sec(0.5초)을 넘기면 근거가 자연스럽게 만료돼야 한다.
        for frame_number in range(8, 20):
            events += detector.process(
                _result(frame_number, self._NON_HORIZONTAL_BBOX), model_evidence={}
            )

        assert events == []  # confirm되지 않아야 함(근거가 만료됐으므로)

    def test_model_evidence_becoming_none_mid_candidate_resets_model_duration(self):
        """model_evidence 딕셔너리 자체가 None으로(예: 모델 로딩 실패로 비활성화)

        바뀌면 이전에 쌓인 근거도 즉시 비워야 한다 — None은 "이 경로를 완전히
        비활성화한다"는 계약이므로, 진행 중이던 근거가 남아 있으면 그 계약과
        어긋난다.
        """
        fps = 10.0
        config = _fast_config(model_confirm_sec=0.5, model_vote_window_sec=0.5)
        detector = FallDetector(fps=fps, config=config)

        events = []
        events += _run(detector, [_STANDING_BBOX] * 5)
        events += detector.process(_result(5, self._NON_HORIZONTAL_BBOX))
        for frame_number in range(6, 9):  # fall 0.3초 누적
            events += detector.process(
                _result(frame_number, self._NON_HORIZONTAL_BBOX),
                model_evidence=_fall_evidence(),
            )
        assert events == []

        # model_evidence 자체가 None으로 전환 (완전 비활성화)
        events += detector.process(_result(9, self._NON_HORIZONTAL_BBOX), model_evidence=None)

        # 다시 fall 근거가 와도 처음부터 다시 쌓여야 하므로 0.2초(2프레임)로는 confirm 안 됨.
        for frame_number in range(10, 12):
            events += detector.process(
                _result(frame_number, self._NON_HORIZONTAL_BBOX),
                model_evidence=_fall_evidence(),
            )

        assert events == []


class TestCooldownSurvivesTrackLoss:
    """S4_fall_forward 중복 Event의 근본 원인(COOLDOWN 중 Track이

    track_grace_sec을 넘겨 소실되면 _TrackState 자체가 삭제돼 cooldown
    기억이 사라지는 문제)에 대한 회귀 테스트.
    """

    def test_state_stays_cooldown_after_track_loss_beyond_grace_period(self):
        fps = 10.0
        config = _fast_config(track_grace_sec=0.2, cooldown_sec=5.0)
        detector = FallDetector(fps=fps, config=config)

        events = []
        events += _run(detector, [_STANDING_BBOX] * 5)
        events += detector.process(_result(5, _LYING_BBOX))
        for frame_number in range(6, 11):
            events += detector.process(_result(frame_number, _LYING_BBOX))
        assert len(events) == 1  # 최초 confirm, 이제 COOLDOWN 상태여야 함
        assert detector._states[("cam1", 1)].state == "COOLDOWN"

        # track_grace_sec(0.2초)보다 길게 이 Track이 아예 감지되지 않음 (occlusion 등)
        for frame_number in range(11, 15):  # 0.4초
            detector.process(
                TrackingResult(
                    frame_number=frame_number,
                    timestamp="00:00:00.000",
                    video_source="cam1",
                    tracks=[],
                )
            )

        # 재등장 - tombstone 수정이 없다면 이 시점에 상태가 삭제돼 새 NORMAL로
        # 시작했을 것이다.
        events += detector.process(_result(15, _LYING_BBOX))
        assert detector._states[("cam1", 1)].state == "COOLDOWN"

        # 계속 누운 자세가 이어져도(재확정 여지가 있는 조건) cooldown이 남아있는
        # 한 재확정되면 안 된다.
        for frame_number in range(16, 21):
            events += detector.process(_result(frame_number, _LYING_BBOX))

        assert len(events) == 1  # 여전히 1건 (중복 없음)

    def test_falling_candidate_state_is_still_forgotten_on_track_loss(self):
        """COOLDOWN만 예외이고, 미확정(FALLING_CANDIDATE) 상태는 기존처럼

        grace period 초과 시 그대로 삭제(정리)돼야 한다 — 무한정 보존 대상이
        아니다.
        """
        fps = 10.0
        config = _fast_config(track_grace_sec=0.2)
        detector = FallDetector(fps=fps, config=config)

        events = []
        events += _run(detector, [_STANDING_BBOX] * 5)
        events += detector.process(_result(5, _LYING_BBOX))  # candidate 진입만, 아직 미확정
        assert detector._states[("cam1", 1)].state == "FALLING_CANDIDATE"
        assert events == []

        for frame_number in range(6, 10):  # grace period 초과 소실
            detector.process(
                TrackingResult(
                    frame_number=frame_number,
                    timestamp="00:00:00.000",
                    video_source="cam1",
                    tracks=[],
                )
            )

        assert ("cam1", 1) not in detector._states  # FALLING_CANDIDATE는 정리돼야 함


class TestExpiredCooldownIsForgottenOnTrackLoss:
    """cooldown_until_sec이 지난 뒤에도 Track이 계속 소실 상태면 COOLDOWN

    상태를 무기한 보존하지 않고 함께 지워야 한다 — 그러지 않으면 실시간
    스트림에서 Track이 다시 나타나지 않는 한(카메라 밖으로 나감 등) 상태가
    낙상마다 하나씩 영구히 누적된다.
    """

    def test_cooldown_state_deleted_once_cooldown_expires_while_track_lost(self):
        fps = 10.0
        config = _fast_config(track_grace_sec=0.2, cooldown_sec=0.5)
        detector = FallDetector(fps=fps, config=config)

        events = []
        events += _run(detector, [_STANDING_BBOX] * 5)
        events += detector.process(_result(5, _LYING_BBOX))
        for frame_number in range(6, 11):
            events += detector.process(_result(frame_number, _LYING_BBOX))
        assert len(events) == 1
        assert detector._states[("cam1", 1)].state == "COOLDOWN"

        # Track이 사라진 채로 cooldown_sec(0.5초)보다 길게 흘러도(occlusion이
        # 아니라 실제로 다시 나타나지 않는 상황을 흉내낸다) 상태가 남아 있으면 안 된다.
        for frame_number in range(11, 30):  # 1.9초 경과, cooldown_sec 0.5초를 크게 초과
            detector.process(
                TrackingResult(
                    frame_number=frame_number,
                    timestamp="00:00:00.000",
                    video_source="cam1",
                    tracks=[],
                )
            )

        assert ("cam1", 1) not in detector._states

    def test_cooldown_state_preserved_while_still_within_cooldown_window(self):
        """cooldown 만료 전까지는(위 TestCooldownSurvivesTrackLoss와 동일하게) 여전히 보존돼야 한다."""
        fps = 10.0
        config = _fast_config(track_grace_sec=0.2, cooldown_sec=5.0)
        detector = FallDetector(fps=fps, config=config)

        events = []
        events += _run(detector, [_STANDING_BBOX] * 5)
        events += detector.process(_result(5, _LYING_BBOX))
        for frame_number in range(6, 11):
            events += detector.process(_result(frame_number, _LYING_BBOX))
        assert len(events) == 1
        assert detector._states[("cam1", 1)].state == "COOLDOWN"

        for frame_number in range(11, 15):  # 0.4초, cooldown_sec(5.0초) 이내
            detector.process(
                TrackingResult(
                    frame_number=frame_number,
                    timestamp="00:00:00.000",
                    video_source="cam1",
                    tracks=[],
                )
            )

        assert ("cam1", 1) in detector._states
        assert detector._states[("cam1", 1)].state == "COOLDOWN"


class TestModelVotingFpsInvariance:
    """model_confirm_sec/model_vote_window_sec은 초 단위 계약이므로 fps가

    달라도 같은 실제 시간(초)이 지나면 temporal voting이 동일하게
    동작해야 한다 (TestFpsInvariance의 bbox 경로와 동일한 검증을
    model confirm 경로에 적용).
    """

    _NON_HORIZONTAL_BBOX = (40.0, 20.0, 60.0, 80.0)

    @pytest.mark.parametrize("fps", [10.0, 20.0, 30.0])
    def test_confirm_duration_is_equivalent_across_fps(self, fps):
        config = _fast_config(model_confirm_sec=0.5, model_vote_window_sec=1.0)
        detector = FallDetector(fps=fps, config=config)

        standing_frames = max(5, int(0.5 * fps))
        events = _run(detector, [_STANDING_BBOX] * standing_frames)

        frame_number = standing_frames
        events += detector.process(_result(frame_number, self._NON_HORIZONTAL_BBOX))
        assert events == []

        # 0.5초 문턱보다 확실히 넉넉하게(0.6초) 채워 부동소수점 경계 문제를 피한다.
        fall_frame_count = int(round(0.6 * fps))
        for offset in range(1, fall_frame_count + 1):
            events += detector.process(
                _result(frame_number + offset, self._NON_HORIZONTAL_BBOX),
                model_evidence=_fall_evidence(),
            )

        assert len(events) == 1, f"fps={fps}에서 예상과 다른 Event 개수: {len(events)}"
        assert events[0].event_type == "FALL_SUSPECT"

    @pytest.mark.parametrize("fps", [10.0, 20.0, 30.0])
    def test_evidence_expiry_is_equivalent_across_fps(self, fps):
        """model_vote_window_sec보다 오래된 근거가 만료되는 시점도 fps와

        무관하게 실제 시간(초) 기준으로 동일해야 한다.
        """
        config = _fast_config(model_confirm_sec=0.3, model_vote_window_sec=0.5)
        detector = FallDetector(fps=fps, config=config)

        standing_frames = max(5, int(0.5 * fps))
        events = _run(detector, [_STANDING_BBOX] * standing_frames)

        frame_number = standing_frames
        events += detector.process(_result(frame_number, self._NON_HORIZONTAL_BBOX))

        # fall 0.2초 (0.3초 문턱 미달)
        fall_frame_count = int(round(0.2 * fps))
        for offset in range(1, fall_frame_count + 1):
            events += detector.process(
                _result(frame_number + offset, self._NON_HORIZONTAL_BBOX),
                model_evidence=_fall_evidence(),
            )
        assert events == []

        # window(0.5초)보다 길게 unknown을 흘려 앞선 근거를 모두 만료시킨다.
        unknown_frame_count = int(round(0.7 * fps))
        base = frame_number + fall_frame_count
        for offset in range(1, unknown_frame_count + 1):
            events += detector.process(
                _result(base + offset, self._NON_HORIZONTAL_BBOX),
                model_evidence=_unknown_evidence(),
            )
        assert events == []

        # 만료 후 짧은 fall 근거만 추가 -> 여전히 0.3초 문턱에 못 미쳐야 한다.
        events += detector.process(
            _result(base + unknown_frame_count + 1, self._NON_HORIZONTAL_BBOX),
            model_evidence=_fall_evidence(),
        )
        assert events == [], f"fps={fps}에서 만료되지 않은 근거가 남아 있음"


class TestModelAssistedCandidateEntry:
    """ReID 없이 재획득된 Track이 이미 쓰러진 상태라 bbox 동적 근거가 없어도,

    모델이 지속적으로 fall이라고 판단하면 candidate에 진입해 confirm까지
    이어져야 한다 (Development 12개 미검출 영상 실측, 자세한 내용은
    docs/fall_evaluation.md 참고). bbox는 첫 프레임부터 끝까지 고정(정적)해 "재획득 시점부터 이미
    누워서 움직이지 않는 새 Track"을 재현한다 — 이 bbox만으로는 dynamic
    evidence(하강 속도·높이 수축)가 전혀 발생하지 않는다.
    """

    _ALREADY_FALLEN_BBOX = (40.0, 20.0, 60.0, 80.0)  # 고정, aspect 0.33

    def _config(self, **overrides):
        defaults = {
            "model_candidate_entry_sec": 0.1,
            "model_confirm_sec": 0.2,
            "model_vote_window_sec": 0.5,
        }
        defaults.update(overrides)
        return _fast_config(**defaults)

    def test_already_fallen_new_track_confirms_via_model_alone(self):
        fps = 10.0
        detector = FallDetector(fps=fps, config=self._config())

        events = []
        for frame_number in range(10):
            events += detector.process(
                _result(frame_number, self._ALREADY_FALLEN_BBOX),
                model_evidence=_fall_evidence(),
            )

        assert len(events) == 1
        assert events[0].event_type == "FALL_SUSPECT"

    def test_single_fall_frame_does_not_confirm(self):
        """모델 fall 근거가 단 1프레임만 있으면 candidate에도 진입하지 못해야 한다

        (model_candidate_entry_sec 0.1초 = 1프레임 미만).
        """
        fps = 10.0
        detector = FallDetector(fps=fps, config=self._config())

        events = []
        events += detector.process(
            _result(0, self._ALREADY_FALLEN_BBOX), model_evidence=_fall_evidence()
        )
        for frame_number in range(1, 10):
            events += detector.process(
                _result(frame_number, self._ALREADY_FALLEN_BBOX),
                model_evidence=_nofall_evidence(),
            )

        assert events == []

    def test_model_candidate_then_sustained_nofall_returns_to_normal(self):
        """model 경로로 candidate에 진입한 뒤, 근거가 윈도우 밖으로 만료될

        만큼 충분히 오래 nofall이 이어지고 bbox도 회복 조건을 만족하면
        NORMAL로 되돌아가야 한다. 단발성 nofall 한 프레임으로는 최근 근거가
        곧바로 사라지지 않으므로(모듈 docstring), 윈도우보다 긴 nofall
        구간을 사용한다.
        """
        fps = 10.0
        config = self._config(
            model_confirm_sec=0.4,  # 짧은 진입 구간(0.1~0.3초)만으로는 confirm 안 되도록 여유
            model_vote_window_sec=0.5,
            recovery_confirm_sec=0.2,
        )
        detector = FallDetector(fps=fps, config=config)
        recovering_bbox = _STANDING_BBOX  # aspect<0.9, 정지 -> 회복 조건 충족

        events = []
        for frame_number in range(4):  # min_track_age_sec(0.3s) 통과 + entry(0.1s)
            events += detector.process(
                _result(frame_number, recovering_bbox), model_evidence=_fall_evidence()
            )
        assert detector._states[("cam1", 1)].state == "FALLING_CANDIDATE"
        assert events == []

        # 윈도우(0.5초)보다 충분히 긴 nofall 구간(1.2초) -> 근거가 모두 만료된다.
        for frame_number in range(4, 16):
            events += detector.process(
                _result(frame_number, recovering_bbox), model_evidence=_nofall_evidence()
            )

        assert events == []
        assert detector._states[("cam1", 1)].state == "NORMAL"

    def test_no_tracks_produces_no_event(self):
        fps = 10.0
        detector = FallDetector(fps=fps, config=self._config())

        events = []
        for frame_number in range(10):
            events += detector.process(
                TrackingResult(
                    frame_number=frame_number,
                    timestamp="00:00:00.000",
                    video_source="cam1",
                    tracks=[],
                )
            )

        assert events == []

    def test_multiple_tracks_model_evidence_independent(self):
        """한 Track의 모델 근거가 다른 Track의 candidate 진입에 영향을 주면 안 된다."""
        fps = 10.0
        detector = FallDetector(fps=fps, config=self._config())

        events = []
        for frame_number in range(10):
            result = TrackingResult(
                frame_number=frame_number,
                timestamp="00:00:00.000",
                video_source="cam1",
                tracks=[
                    Track(
                        track_id=1,
                        bbox=list(self._ALREADY_FALLEN_BBOX),
                        foot_point=[50.0, 80.0],
                        confidence=0.9,
                    ),
                    Track(
                        track_id=2,
                        bbox=list(_STANDING_BBOX),
                        foot_point=[50.0, 60.0],
                        confidence=0.9,
                    ),
                ],
            )
            evidence = {
                1: FallModelEvidence(track_id=1, label="fall", confidence=0.9, iou=0.9),
                2: FallModelEvidence(track_id=2, label="nofall", confidence=0.9, iou=0.9),
            }
            events += detector.process(result, model_evidence=evidence)

        fall_events = [e for e in events if e.track_id == 1]
        no_events_for_track2 = [e for e in events if e.track_id == 2]
        assert len(fall_events) == 1
        assert no_events_for_track2 == []

    def test_bbox_only_dynamic_entry_path_still_works_without_model(self):
        """model_evidence가 아예 없을 때(None) 기존 bbox 동적 candidate 경로는

        그대로 동작해야 한다 — model-assisted 진입 추가가 기존 경로를 깨면
        안 된다.
        """
        fps = 10.0
        detector = FallDetector(fps=fps, config=self._config())

        events = []
        events += _run(detector, [_STANDING_BBOX] * 5)
        events += detector.process(_result(5, _LYING_BBOX))
        for frame_number in range(6, 11):
            events += detector.process(_result(frame_number, _LYING_BBOX))

        assert len(events) == 1


class TestSpatialCooldownInheritance:
    """ReID 없이 재획득된 같은 사람이 새 track_id로 candidate/confirm을 다시

    만드는 것을 막는 공간 기반 cooldown 승계(Development 실측
    S2_fall_forward·S3_fall_right 중복 Event, 자세한 내용은
    docs/fall_evaluation.md 참고).
    """

    _FALLEN_BBOX = (40.0, 20.0, 60.0, 80.0)  # 고정 위치, aspect 0.33
    _OTHER_LOCATION_BBOX = (200.0, 20.0, 220.0, 80.0)  # 겹치지 않는 다른 위치

    def _config(self, **overrides):
        defaults = {
            "cooldown_sec": 5.0,
            "model_candidate_entry_sec": 0.1,
            "model_confirm_sec": 0.2,
            "model_vote_window_sec": 0.5,
            "cooldown_inherit_iou_threshold": 0.3,
        }
        defaults.update(overrides)
        return _fast_config(**defaults)

    def _confirm_track1(self, detector, fps):
        """track_id=1을 model 경로로 confirm시키고 이어서 track_id=1을 소실시킨다."""
        events = []
        for frame_number in range(6):  # min_track_age_sec 통과 + entry + confirm
            events += detector.process(
                _result(frame_number, self._FALLEN_BBOX, track_id=1),
                model_evidence=_fall_evidence(track_id=1),
            )
        assert len(events) == 1
        return events

    def test_same_location_new_track_id_inherits_cooldown_single_event(self):
        fps = 10.0
        detector = FallDetector(fps=fps, config=self._config())
        events = self._confirm_track1(detector, fps)

        # track_id=1 소실, 같은 위치에서 track_id=2로 재검출 (ReID 없는 ID switch 재현)
        for frame_number in range(6, 20):
            events += detector.process(
                _result(frame_number, self._FALLEN_BBOX, track_id=2),
                model_evidence=_fall_evidence(track_id=2),
            )

        assert len(events) == 1  # 새 track_id로도 재확정되면 안 된다
        assert detector._states[("cam1", 2)].state == "COOLDOWN"

    def test_repeated_id_switches_share_same_cooldown(self):
        """같은 낙상이 ID 1→2→3으로 연속 재획득돼도 Event는 한 번만 발생한다."""
        fps = 10.0
        detector = FallDetector(fps=fps, config=self._config())
        events = self._confirm_track1(detector, fps)

        for frame_number in range(6, 10):
            events += detector.process(
                _result(frame_number, self._FALLEN_BBOX, track_id=2),
                model_evidence=_fall_evidence(track_id=2),
            )
        for frame_number in range(10, 20):
            events += detector.process(
                _result(frame_number, self._FALLEN_BBOX, track_id=3),
                model_evidence=_fall_evidence(track_id=3),
            )

        assert len(events) == 1
        assert detector._states[("cam1", 2)].state == "COOLDOWN"
        assert detector._states[("cam1", 3)].state == "COOLDOWN"

    def test_different_location_track_detected_independently(self):
        """다른 위치의 Track은 cooldown을 물려받지 않고 독립적으로 감지돼야 한다."""
        fps = 10.0
        detector = FallDetector(fps=fps, config=self._config())
        events = self._confirm_track1(detector, fps)

        for frame_number in range(6, 12):
            events += detector.process(
                _result(frame_number, self._OTHER_LOCATION_BBOX, track_id=2),
                model_evidence=_fall_evidence(track_id=2),
            )

        assert len(events) == 2  # 다른 위치의 낙상은 별도로 확정돼야 한다
        assert {e.track_id for e in events} == {1, 2}

    def test_cooldown_expiry_allows_new_event_after_recovery(self):
        """cooldown을 물려받아도, 그 뒤 실제로 회복(nofall)하고 cooldown이 만료되면

        NORMAL로 돌아가 다음 낙상은 새 Event로 인정돼야 한다 — 승계가 해당
        track을 영구히 억제하는 것은 아니다.
        """
        fps = 10.0
        detector = FallDetector(fps=fps, config=self._config(cooldown_sec=0.5))
        events = self._confirm_track1(detector, fps)  # frame 0~4, confirm은 frame4

        # track_id=2로 재검출, cooldown을 물려받지만 nofall이라 cooldown 만료
        # 후(t>=0.9s) 회복 조건도 만족해 NORMAL로 돌아가야 한다.
        for frame_number in range(6, 16):
            events += detector.process(
                _result(frame_number, self._FALLEN_BBOX, track_id=2),
                model_evidence=_nofall_evidence(track_id=2),
            )
        assert detector._states[("cam1", 2)].state == "NORMAL"
        assert len(events) == 1  # 아직 재확정 없음

        # 이제 새로운 낙상 근거가 다시 이어지면 완전히 새로운 확정이어야 한다.
        for frame_number in range(16, 22):
            events += detector.process(
                _result(frame_number, self._FALLEN_BBOX, track_id=2),
                model_evidence=_fall_evidence(track_id=2),
            )

        assert len(events) == 2  # cooldown 만료·회복 후이므로 새로운 확정으로 인정돼야 한다

    def test_expired_tombstone_is_pruned_and_does_not_inherit(self):
        """cooldown이 만료된 tombstone은 정리되어, 그 이후 재검출은 승계되지 않아야 한다."""
        fps = 10.0
        detector = FallDetector(fps=fps, config=self._config(cooldown_sec=0.3))
        self._confirm_track1(detector, fps)

        # cooldown(0.3초=3프레임) 초과, track이 전혀 없는 상태로 시간을 흘려보낸다.
        for frame_number in range(6, 15):
            detector.process(
                TrackingResult(
                    frame_number=frame_number,
                    timestamp="00:00:00.000",
                    video_source="cam1",
                    tracks=[],
                )
            )

        assert detector._cooldown_tombstones.get("cam1", []) == []

    def test_existing_same_track_id_cooldown_still_prevents_duplicate(self):
        """동일 track_id가 계속 이어지는 기존 cooldown 동작은 그대로 유지돼야 한다."""
        fps = 10.0
        detector = FallDetector(fps=fps, config=self._config())
        events = self._confirm_track1(detector, fps)

        for frame_number in range(6, 20):
            events += detector.process(
                _result(frame_number, self._FALLEN_BBOX, track_id=1),
                model_evidence=_fall_evidence(track_id=1),
            )

        assert len(events) == 1
