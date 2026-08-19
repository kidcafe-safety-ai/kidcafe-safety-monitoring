"""`scripts/evaluate_zone_paths.py`의 채택 기준 2~5번 산출 검증.

이 스크립트는 두 좌표 경로의 우열을 판정하는 근거를 만든다. 집계가 틀리면
잘못된 근거로 채택·미채택을 말하게 되므로, 정답을 아는 합성 입력으로 각
지표를 따로 확인한다.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import phase4_recording_contract as contract  # noqa: E402

from scripts import evaluate_zone_paths as ezp  # noqa: E402

FPS = 60.0
# 계약 파일명 규칙을 따라야 manifest 검증을 통과한다.
VIDEO_ID = "P4_S01_A01_zone_enter_exit_01_cam01"
VIDEO_SHA256 = "a" * 64


def event(frame, kind):
    return {"frame": frame, "type": kind}


def judged(rows):
    """(frame, image, homography) 튜플을 판정 행으로 바꾼다."""
    return [
        {"frame": f, "track": None, "image": i, "homography": h} for f, i, h in rows
    ]


# --- frame 단위 정확도·오판정 (기준 2·3번) ---


def test_frame_score_counts_both_error_directions():
    rows = judged([(0, False, False), (10, True, True), (20, False, True)])
    score = ezp.score_frames(rows, enter=10, exit_=20, path="image")
    assert score == {
        "frames_scored": 3, "correct": 3, "wrong": 0,
        "false_inside": 0, "false_outside": 0, "accuracy": 1.0,
    }
    other = ezp.score_frames(rows, enter=10, exit_=20, path="homography")
    assert other["wrong"] == 1
    assert other["false_inside"] == 1
    assert other["false_outside"] == 0


def test_frame_score_marks_missed_inside_as_false_outside():
    rows = judged([(10, False, True)])
    score = ezp.score_frames(rows, enter=10, exit_=20, path="image")
    assert score["false_outside"] == 1
    assert score["false_inside"] == 0


def test_exit_frame_is_outside_the_interval():
    """exit_frame은 밖으로 나온 첫 frame이므로 구간에 포함하지 않는다."""
    rows = judged([(20, True, False)])
    assert ezp.score_frames(rows, 10, 20, "image")["wrong"] == 1
    assert ezp.score_frames(rows, 10, 20, "homography")["correct"] == 1


# --- Event 오류 (기준 4번) ---


def test_event_score_accepts_events_within_tolerance():
    events = [event(112, "ENTER"), event(205, "EXIT")]
    score = ezp.score_events(events, enter=100, exit_=200, fps=FPS, tolerance_sec=1.0)
    assert score["missed"] == 0
    assert score["false"] == 0
    assert score["duplicate"] == 0
    assert score["total_errors"] == 0


def test_event_score_records_signed_onset_error():
    """확정 지연이 보이도록 부호를 유지한다."""
    events = [event(118, "ENTER"), event(194, "EXIT")]
    score = ezp.score_events(events, 100, 200, FPS, 1.0)
    assert score["onset_error_sec"]["enter"] == pytest.approx(18 / FPS)
    assert score["onset_error_sec"]["exit"] == pytest.approx(-6 / FPS)


def test_event_score_counts_missing_event():
    score = ezp.score_events([event(105, "ENTER")], 100, 200, FPS, 1.0)
    assert score["missed"] == 1
    assert score["onset_error_sec"]["exit"] is None
    assert score["total_errors"] == 1


def test_event_score_counts_out_of_tolerance_as_false():
    score = ezp.score_events([event(400, "ENTER"), event(205, "EXIT")], 100, 200, FPS, 1.0)
    assert score["missed"] == 1
    assert score["false"] == 1
    assert score["total_errors"] == 2


def test_event_score_counts_duplicates_inside_tolerance():
    events = [event(105, "ENTER"), event(115, "ENTER"), event(205, "EXIT")]
    score = ezp.score_events(events, 100, 200, FPS, 1.0)
    assert score["duplicate"] == 1
    assert score["missed"] == 0
    assert score["total_errors"] == 1


# --- 빠른 반전 (기준 5번) ---


def test_fast_flip_counts_only_close_opposite_pairs():
    events = [event(100, "ENTER"), event(120, "EXIT"), event(600, "ENTER")]
    assert ezp.count_flips(events, FPS, 1.0) == 1


def test_same_type_repeats_are_not_flips():
    events = [event(100, "ENTER"), event(110, "ENTER")]
    assert ezp.count_flips(events, FPS, 1.0) == 0


def test_far_apart_transitions_are_not_flips():
    events = [event(100, "ENTER"), event(400, "EXIT")]
    assert ezp.count_flips(events, FPS, 1.0) == 0


# --- 비율과 판정 ---


def test_ratio_is_undefined_when_baseline_has_no_errors():
    """기준선이 0이면 감소율을 만들 수 없다. 0으로 나누지 않는다."""
    assert ezp.ratio_change(0, 0) is None
    assert ezp.ratio_change(0, 3) is None
    assert ezp.ratio_change(10, 7) == pytest.approx(0.3)


def test_criterion_4_needs_thirty_percent_reduction():
    assert ezp._passes_ratio(10, 7, 0.30) is True
    assert ezp._passes_ratio(10, 8, 0.30) is False
    assert ezp._passes_ratio(0, 0, 0.30) is None


def test_criterion_3_passes_on_either_condition():
    """오판정 30% 감소 또는 정확도 5%p 개선 중 하나만 만족해도 된다."""
    assert ezp._passes_criterion_3(100, 60, 0.0) is True      # 비율만
    assert ezp._passes_criterion_3(100, 95, 6.0) is True      # 정확도만
    assert ezp._passes_criterion_3(100, 95, 1.0) is False     # 둘 다 미달
    assert ezp._passes_criterion_3(0, 0, None) is None


# --- Track 선택 ---


def sample_frames():
    return {
        "0": [{"track_id": 1, "bbox": [0, 0, 1, 1], "foot_point": [0, 0], "confidence": 1.0}],
        "5": [
            {"track_id": 1, "bbox": [0, 0, 1, 1], "foot_point": [0, 0], "confidence": 1.0},
            {"track_id": 2, "bbox": [0, 0, 1, 1], "foot_point": [0, 0], "confidence": 1.0},
        ],
        "6": [{"track_id": 2, "bbox": [0, 0, 1, 1], "foot_point": [0, 0], "confidence": 1.0}],
        "7": [{"track_id": 2, "bbox": [0, 0, 1, 1], "foot_point": [0, 0], "confidence": 1.0}],
    }


def test_longest_mode_picks_the_most_seen_track():
    track_id, info = ezp.pick_track(sample_frames(), "longest", enter=0, exit_=1)
    assert track_id == 2
    assert info["frames_total"] == 3


def test_gt_overlap_mode_picks_the_track_inside_the_interval():
    track_id, info = ezp.pick_track(sample_frames(), "gt-overlap", enter=0, exit_=6)
    assert track_id == 1
    assert info["frames_in_gt_interval"] == 2


def test_selection_is_flagged_when_candidates_are_close():
    frames = {
        "0": [{"track_id": 1, "bbox": [0, 0, 1, 1], "foot_point": [0, 0], "confidence": 1.0}],
        "1": [{"track_id": 2, "bbox": [0, 0, 1, 1], "foot_point": [0, 0], "confidence": 1.0}],
    }
    _, info = ezp.pick_track(frames, "longest", 0, 2)
    assert info["ambiguous"] is True
    assert info["candidate_tracks"] == 2


def test_empty_frames_select_nothing():
    assert ezp.pick_track({}, "longest", 0, 1)[0] is None


# --- notes 파싱 ---


def test_notes_are_parsed_into_key_values():
    parsed = ezp.parse_notes("calibration_version=v1; image_zone=a.json; flag=on")
    assert parsed == {"calibration_version": "v1", "image_zone": "a.json", "flag": "on"}


def test_notes_tolerate_empty_and_malformed_chunks():
    assert ezp.parse_notes("") == {}
    assert ezp.parse_notes("bare; a=1") == {"a": 1 and "1"}


# --- end-to-end ---


@pytest.fixture
def workspace(tmp_path):
    """정답을 아는 최소 입력 한 벌을 만든다.

    image Zone과 floor Zone이 같은 사각형을 가리키도록 calibration을 항등에
    가깝게 잡아, 두 경로가 같은 판정을 내는 것이 정상인 상태로 둔다.
    """
    (tmp_path / "configs" / "camera_calibration").mkdir(parents=True)
    (tmp_path / "data" / "zones").mkdir(parents=True)
    width, height = 1000, 1000

    # 픽셀 (x, y) -> floor (x/1000, y/1000)
    (tmp_path / "configs/camera_calibration/cam01.json").write_text(json.dumps({
        "schema_version": 1, "calibration_version": "test-v1", "enabled": False,
        "camera_id": "cam01", "frame_size": {"width": width, "height": height},
        "coordinate_unit": "meter", "origin_description": "테스트 원점",
        "image_points_px": [[0, 0], [1000, 0], [1000, 1000], [0, 1000]],
        "floor_points": [[0, 0], [1, 0], [1, 1], [0, 1]],
    }), encoding="utf-8")

    square_norm = [[0.2, 0.2], [0.8, 0.2], [0.8, 0.8], [0.2, 0.8]]
    (tmp_path / "data/zones/image_cam01.json").write_text(json.dumps([{
        "zone_id": "play_floor", "name": "놀이", "type": "polygon",
        "zone_type": "play", "points": square_norm,
        "rules": {"enter_alert": True, "dwell_threshold_sec": 5},
    }]), encoding="utf-8")
    (tmp_path / "data/zones/floor_cam01.json").write_text(json.dumps({
        "schema_version": 1, "camera_id": "cam01", "coordinate_space": "floor_meters",
        "zones": [{
            "zone_id": "play_floor", "zone_name": "놀이", "type": "polygon",
            "zone_type": "play", "points": square_norm,
            "rules": {"enter_alert": True, "dwell_threshold_sec": 5},
        }],
    }), encoding="utf-8")

    def csv_write(name, header, rows):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="") as file:
            writer = csv.writer(file, lineterminator="\n")
            writer.writerow(header)
            writer.writerows(rows)
        return path

    enter, exit_ = 60, 240
    manifest = csv_write(
        "manifest.csv",
        list(contract.MANIFEST_FIELDS),
        [[VIDEO_ID, "S01", "A01", "A01", "cam01", "zone_enter_exit", "no_fall",
          f"data/videos/{VIDEO_ID}.mp4", FPS, 300, width, height, "indoor",
          "diagnostic", "reviewed", "confirmed", VIDEO_SHA256]],
    )
    intervals = csv_write(
        "intervals.csv",
        list(contract.ZONE_INTERVAL_FIELDS),
        [[VIDEO_ID, "play_floor", 1, enter, exit_, "", "reviewed", "review_mode=blind"]],
    )
    plan = csv_write(
        "plan.csv",
        ["review_index", "original_filename", "contract_filename", "notes"],
        [[1, "IMG_1.MOV", f"{VIDEO_ID}.mp4",
          "calibration_version=test-v1; image_zone=data/zones/image_cam01.json"]],
    )
    identity = csv_write(
        "data/annotations/phase4/zone_eval/track_identity.csv",
        list(ezp.TRACK_IDENTITY_FIELDS),
        [[VIDEO_ID, "A01", 7, "bbox_overlay_visual", "tester", "2026-08-18", ""]],
    )

    # 밖(100) -> 안(500) -> 밖(900). 두 경로 모두 정답과 일치해야 한다.
    frames = {}
    for f in range(300):
        x = 500.0 if enter <= f < exit_ else 100.0
        frames[str(f)] = [{
            "track_id": 7, "bbox": [x - 10, 0, x + 10, 100],
            "foot_point": [x, 500.0], "confidence": 0.9,
        }]
    cache = tmp_path / "cache.json"
    cache.write_text(json.dumps({
        "schema_version": ezp.CACHE_SCHEMA_VERSION,
        "tracker": {"model": "test.pt", "model_sha256": "0" * 64, "confidence": 0.5},
        "videos": {VIDEO_ID: {
            "frame_count": 300, "fps": FPS, "width": width, "height": height,
            "video_sha256": VIDEO_SHA256, "frames": frames,
        }},
    }), encoding="utf-8")

    return {
        "root": tmp_path, "cache": cache, "manifest": manifest,
        "intervals": intervals, "plan": plan, "identity": identity,
        "enter": enter, "exit": exit_,
    }


def run(workspace, **overrides):
    import argparse
    args = argparse.Namespace(
        cache=str(workspace["cache"]), manifest=str(workspace["manifest"]),
        intervals=str(workspace["intervals"]), review_plan=str(workspace["plan"]),
        track_identity=str(workspace["identity"]),
        repo_root=str(workspace["root"]), track_selection="longest",
        event_tolerance_sec=1.0, flip_window_sec=1.0,
        allow_nonstandard_tolerances=False, output="unused",
    )
    for key, value in overrides.items():
        setattr(args, key, value)
    return ezp.evaluate(args)


def test_matching_zones_give_both_paths_the_same_result(workspace):
    """같은 사각형을 가리키면 두 경로 판정이 같아야 한다."""
    result = run(workspace)
    assert result["totals"]["image"]["wrong"] == result["totals"]["homography"]["wrong"]
    assert result["totals"]["image"]["accuracy"] == result["totals"]["homography"]["accuracy"]
    assert result["criteria"]["5_fast_flips_not_increased"]["passes"] is True


def test_perfect_input_yields_no_frame_errors(workspace):
    result = run(workspace)
    for path in ezp.PATHS:
        assert result["totals"][path]["wrong"] == 0
        assert result["totals"][path]["accuracy"] == 1.0


def test_events_lag_by_the_confirm_delay(workspace):
    """EventManager 확정 지연 때문에 예측이 늦게 나오는 것이 정상이다."""
    result = run(workspace)
    events = result["per_video"][0]["image"]["events"]
    assert events["missed"] == 0
    assert events["onset_error_sec"]["enter"] > 0
    assert events["onset_error_sec"]["exit"] > 0


def test_sample_size_note_is_always_present(workspace):
    """작은 표본을 비율만으로 읽지 않도록 원시 건수를 함께 남긴다."""
    sample = run(workspace)["sample"]
    assert sample["boundary_events"] == 2
    assert "원시 건수" in sample["note"]


def test_zero_baseline_errors_make_ratios_undefined(workspace):
    """기준선에 오류가 없으면 감소율을 만들 수 없다고 표시한다."""
    criteria = run(workspace)["criteria"]
    assert criteria["3_zone_error_reduction"]["reduction_ratio"] is None
    assert criteria["4_event_error_reduction"]["passes"] is None


def rewrite_interval(workspace, column, value):
    rows = list(csv.reader(open(workspace["intervals"], encoding="utf-8")))
    rows[1][list(contract.ZONE_INTERVAL_FIELDS).index(column)] = value
    with open(workspace["intervals"], "w", encoding="utf-8", newline="") as file:
        csv.writer(file, lineterminator="\n").writerows(rows)


def test_unreviewed_interval_is_rejected(workspace):
    """동결된 계약 검증을 평가 경로가 그대로 쓴다."""
    rewrite_interval(workspace, "review_status", "needs_review")
    with pytest.raises(ValueError, match="reviewed"):
        run(workspace)


def test_interval_with_exit_before_enter_is_rejected(workspace):
    """enter < exit는 계약이 강제한다. 평가가 이걸 우회하면 안 된다."""
    rewrite_interval(workspace, "enter_frame", "240")
    rewrite_interval(workspace, "exit_frame", "60")
    with pytest.raises(ValueError, match="enter_frame"):
        run(workspace)


def test_interval_frame_outside_the_video_is_rejected(workspace):
    rewrite_interval(workspace, "exit_frame", "9999")
    with pytest.raises(ValueError, match="frame 범위"):
        run(workspace)


def test_interval_index_must_start_at_one(workspace):
    rewrite_interval(workspace, "interval_index", "2")
    with pytest.raises(ValueError, match="interval_index"):
        run(workspace)


def test_unknown_cache_schema_is_rejected(workspace):
    payload = json.loads(workspace["cache"].read_text(encoding="utf-8"))
    payload["schema_version"] = "something_else"
    workspace["cache"].write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ezp.ZoneEvalError, match="schema"):
        run(workspace)


def test_missing_calibration_version_is_rejected(workspace):
    rows = list(csv.reader(open(workspace["plan"], encoding="utf-8")))
    rows[1][3] = "image_zone=data/zones/image_cam01.json"
    with open(workspace["plan"], "w", encoding="utf-8", newline="") as file:
        csv.writer(file, lineterminator="\n").writerows(rows)
    with pytest.raises(ezp.ZoneEvalError, match="calibration_version"):
        run(workspace)


def test_shifted_floor_zone_shows_up_as_homography_errors(workspace):
    """floor Zone만 옮기면 Homography 경로에서만 오류가 늘어야 한다."""
    path = workspace["root"] / "data/zones/floor_cam01.json"
    config = json.loads(path.read_text(encoding="utf-8"))
    config["zones"][0]["points"] = [[x + 0.45, y] for x, y in config["zones"][0]["points"]]
    path.write_text(json.dumps(config), encoding="utf-8")

    totals = run(workspace)["totals"]
    assert totals["image"]["wrong"] == 0
    assert totals["homography"]["wrong"] > 0


# --- 실제 artifact로 확인하는 구조적 성질 ---


ZONE_CLIPS = (
    "clip01", "img7327", "img7328", "img7329", "img7330", "img7331",
    "img7332", "img7333", "img7334", "img7385", "img7387", "img7388",
)
# 두 경로가 갈릴 수 있는 최대 폭. floor Zone 좌표를 소수 4자리로 저장하는데
# 이 촬영 구도에서 1e-4 floor 단위는 약 0.067px이다. 그보다 넉넉히 잡는다.
ROUNDING_BAND_PX = 0.2


def _checkers(clip):
    import json as json_mod

    from shapely.geometry import Polygon

    from src.common.types import Track as RealTrack
    from src.geofencing.floor_plane import FloorPlaneTransformer, load_calibration
    from src.geofencing.floor_zone import FloorZoneChecker, load_floor_zones
    from src.geofencing.zone_checker import ZoneChecker
    from src.geofencing.zone_loader import load_zones

    base = ROOT / "configs/camera_calibration" / f"cam01_{clip}.json"
    calibration = load_calibration(str(base))
    image_path = ROOT / "data/zones" / f"image_cam01_{clip}.json"
    image = ZoneChecker(
        load_zones(str(image_path)),
        calibration.frame_width,
        calibration.frame_height,
    )
    floor = FloorZoneChecker(
        load_floor_zones(str(ROOT / "data/zones" / f"floor_cam01_{clip}.json"))
    )
    transformer = FloorPlaneTransformer(calibration)
    boundary = Polygon(
        [
            [x * calibration.frame_width, y * calibration.frame_height]
            for x, y in json_mod.loads(image_path.read_text(encoding="utf-8"))[0]["points"]
        ]
    ).exterior

    def judge(x, y):
        track = RealTrack(
            track_id=1,
            bbox=[x - 20, y - 160, x + 20, y],
            foot_point=[x, y],
            confidence=0.9,
        )
        return (
            "play_floor" in image.check(track),
            "play_floor" in floor.check_point(transformer.transform([x, y])),
        )

    return judge, calibration, boundary


@pytest.mark.parametrize("clip", ZONE_CLIPS)
def test_two_paths_agree_away_from_the_boundary(clip):
    """두 경로는 같은 클릭에서 만들어져 구조적으로 같은 판정을 낸다.

    floor Zone은 image Zone의 꼭짓점에 homography를 적용해 만든다. 사영변환은
    직선과 포함 관계를 보존하므로, 볼록 폴리곤에서는 두 판정이 좌표 반올림
    오차를 빼면 일치한다. 이 성질이 깨지면 Zone 생성 경로가 바뀐 것이다.
    """
    import random

    from shapely.geometry import Point

    judge, calibration, boundary = _checkers(clip)
    rng = random.Random(11)
    for _ in range(2000):
        x = rng.uniform(0, calibration.frame_width - 1)
        y = rng.uniform(0, calibration.frame_height - 1)
        # 경계에 우연히 얹힌 점은 반올림 밴드 안이라 제외한다. 밴드 자체는
        # 아래 test_boundary_disagreement_stays_inside_the_rounding_band가 본다.
        if Point(x, y).distance(boundary) <= ROUNDING_BAND_PX:
            continue
        image_in, floor_in = judge(x, y)
        assert image_in == floor_in, f"{clip}에서 ({x:.1f}, {y:.1f}) 판정이 갈렸다"


@pytest.mark.parametrize("clip", ZONE_CLIPS[:3])
def test_boundary_disagreement_stays_inside_the_rounding_band(clip):
    """경계 근처에서 갈리더라도 저장 정밀도 안에 머물러야 한다."""
    import random

    from shapely.geometry import Point

    judge, calibration, boundary = _checkers(clip)
    rng = random.Random(5)
    worst = 0.0
    for index in range(4000):
        anchor = boundary.interpolate(boundary.length * index / 4000)
        x = anchor.x + rng.uniform(-1, 1)
        y = anchor.y + rng.uniform(-1, 1)
        if not (0 <= x < calibration.frame_width and 0 <= y < calibration.frame_height):
            continue
        image_in, floor_in = judge(x, y)
        if image_in != floor_in:
            worst = max(worst, Point(x, y).distance(boundary))
    assert worst <= ROUNDING_BAND_PX, f"{clip}에서 경계 {worst:.3f}px 밖까지 판정이 갈렸다"


def test_written_bytes_use_lf_on_every_platform(tmp_path):
    """결과 JSON은 어느 OS에서 만들어도 같은 바이트여야 한다.

    Windows 텍스트 모드가 \\n을 \\r\\n으로 바꿔, 실제로 전 줄 CRLF인 결과가
    나왔다. 커밋되는 artifact이고 저장소는 이미 CRLF 유입으로 `git diff
    --check`가 걸린 적이 있다.
    """
    target = tmp_path / "result.json"
    ezp.write_json_atomic(target, {"schema_version": ezp.RESULT_SCHEMA_VERSION})
    raw = target.read_bytes()
    assert b"\r\n" not in raw
    assert raw.endswith(b"\n")


# --- 캐시·입력 artifact 무결성 (종민 1번) ---


def tamper_cache(workspace, **changes):
    payload = json.loads(workspace["cache"].read_text(encoding="utf-8"))
    entry = payload["videos"][VIDEO_ID]
    entry.update(changes)
    workspace["cache"].write_text(json.dumps(payload), encoding="utf-8")


def test_cache_from_a_different_video_is_rejected(workspace):
    """캐시의 영상 SHA-256이 manifest와 다르면 다른 영상으로 만든 캐시다."""
    tamper_cache(workspace, video_sha256="b" * 64)
    with pytest.raises(ezp.ZoneEvalError, match="SHA-256"):
        run(workspace)


def test_cache_without_video_checksum_is_rejected(workspace):
    tamper_cache(workspace, video_sha256="")
    with pytest.raises(ezp.ZoneEvalError, match="video_sha256"):
        run(workspace)


def test_cache_frame_count_mismatch_is_rejected(workspace):
    tamper_cache(workspace, frame_count=280)
    with pytest.raises(ezp.ZoneEvalError, match="frame 수"):
        run(workspace)


def test_cache_fps_mismatch_is_rejected(workspace):
    """fps가 다르면 같은 frame 번호가 다른 시점을 가리킨다."""
    tamper_cache(workspace, fps=30.0)
    with pytest.raises(ezp.ZoneEvalError, match="fps"):
        run(workspace)


def test_cache_built_from_another_manifest_is_rejected(workspace):
    payload = json.loads(workspace["cache"].read_text(encoding="utf-8"))
    payload["manifest_sha256"] = "c" * 64
    workspace["cache"].write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ezp.ZoneEvalError, match="manifest"):
        run(workspace)


@pytest.mark.parametrize("tracker", [None, {}, {"model_sha256": "짧다"}])
def test_missing_tracker_provenance_is_rejected(workspace, tracker):
    payload = json.loads(workspace["cache"].read_text(encoding="utf-8"))
    if tracker is None:
        payload.pop("tracker")
    else:
        payload["tracker"] = tracker
    workspace["cache"].write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ezp.ZoneEvalError, match="tracker"):
        run(workspace)


def test_result_records_every_input_artifact(workspace):
    """어떤 입력으로 만든 결과인지 파일만 보고 감사할 수 있어야 한다."""
    result = run(workspace)
    digests = result["input_artifacts_sha256"]
    assert set(digests) == {
        "cache", "manifest", "intervals", "review_plan", "track_identity"
    }
    assert all(len(v) == 64 for v in digests.values())
    assert digests["manifest"] == ezp.sha256_file(workspace["manifest"])
    assert result["tracker"]["model_sha256"] == "0" * 64
    assert result["per_video"][0]["video_sha256"] == VIDEO_SHA256


# --- Zone 선택 (종민 3번) ---


def add_decoy_zone(workspace, first: bool):
    """같은 파일에 다른 Zone을 하나 더 넣는다."""
    decoy_image = {
        "zone_id": "decoy", "name": "미끼", "type": "polygon", "zone_type": "play",
        "points": [[0.0, 0.0], [0.05, 0.0], [0.05, 0.05], [0.0, 0.05]],
        "rules": {"enter_alert": True, "dwell_threshold_sec": 5},
    }
    image_path = workspace["root"] / "data/zones/image_cam01.json"
    zones = json.loads(image_path.read_text(encoding="utf-8"))
    zones = [decoy_image] + zones if first else zones + [decoy_image]
    image_path.write_text(json.dumps(zones), encoding="utf-8")

    floor_path = workspace["root"] / "data/zones/floor_cam01.json"
    config = json.loads(floor_path.read_text(encoding="utf-8"))
    decoy_floor = dict(decoy_image)
    decoy_floor["zone_name"] = decoy_floor.pop("name")
    config["zones"] = (
        [decoy_floor] + config["zones"] if first else config["zones"] + [decoy_floor]
    )
    floor_path.write_text(json.dumps(config), encoding="utf-8")


def test_zone_order_does_not_change_the_result(workspace):
    """예전에는 zones[0]을 써서 Zone 순서가 Event 평가 대상을 바꿨다."""
    baseline = run(workspace)
    add_decoy_zone(workspace, first=True)
    with_decoy_first = run(workspace)
    assert with_decoy_first["totals"] == baseline["totals"]
    assert (
        with_decoy_first["per_video"][0]["image"]["event_list"]
        == baseline["per_video"][0]["image"]["event_list"]
    )


def test_missing_zone_id_is_rejected(workspace):
    rewrite_interval(workspace, "zone_id", "does_not_exist")
    with pytest.raises(ezp.ZoneEvalError, match="zone_id"):
        run(workspace)


def test_duplicate_zone_id_is_rejected(workspace):
    image_path = workspace["root"] / "data/zones/image_cam01.json"
    zones = json.loads(image_path.read_text(encoding="utf-8"))
    image_path.write_text(json.dumps(zones + [dict(zones[0])]), encoding="utf-8")
    with pytest.raises((ezp.ZoneEvalError, ValueError), match="중복|duplicate|zone_id"):
        run(workspace)


def test_result_records_the_evaluated_zone(workspace):
    assert run(workspace)["per_video"][0]["zone_id"] == "play_floor"


# --- 대상 Track 확인 기록 (종민 4번) ---


def set_verified_track(workspace, track_id):
    rows = list(csv.reader(open(workspace["identity"], encoding="utf-8")))
    rows[1][2] = str(track_id)
    with open(workspace["identity"], "w", encoding="utf-8", newline="") as file:
        csv.writer(file, lineterminator="\n").writerows(rows)


def test_selected_track_must_match_the_verified_record(workspace):
    """캐시나 tracker가 바뀌어 다른 사람이 선택되면 공식 실행은 멈춘다."""
    set_verified_track(workspace, 99)
    with pytest.raises(ezp.ZoneEvalError, match="확인 기록"):
        run(workspace)


def test_diagnostic_run_records_the_mismatch_instead_of_failing(workspace):
    """진단 실행은 멈추지 않는다.

    gt-overlap처럼 다른 Track을 고르는 규칙을 일부러 돌려보는 것이 진단의
    목적이고, 그 규칙이 대상이 아닌 사람을 고른다는 사실 자체가 결과다.
    공식 실행에서만 막으면 된다.
    """
    set_verified_track(workspace, 99)
    result = run(workspace, event_tolerance_sec=3.0, allow_nonstandard_tolerances=True)
    identity = result["per_video"][0]["track_identity"]
    assert identity["matches_verified_track"] is False
    assert identity["selected_track_id"] == 7
    assert identity["track_id"] == 99


def test_matching_track_is_marked_as_verified(workspace):
    identity = run(workspace)["per_video"][0]["track_identity"]
    assert identity["matches_verified_track"] is True
    assert identity["selected_track_id"] == 7


def test_verified_track_is_carried_into_the_result(workspace):
    identity = run(workspace)["per_video"][0]["track_identity"]
    assert identity["track_id"] == 7
    assert identity["ground_truth_actor"] == "A01"
    assert identity["reviewer_id"] == "tester"
    assert identity["verified_at"] == "2026-08-18"


def test_track_identity_requires_a_reviewer(tmp_path):
    path = tmp_path / "identity.csv"
    with open(path, "w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file, lineterminator="\n")
        writer.writerow(list(ezp.TRACK_IDENTITY_FIELDS))
        writer.writerow(["V1", "A01", 2, "visual", "", "2026-08-18", ""])
    with pytest.raises(ezp.ZoneEvalError, match="reviewer_id"):
        ezp.load_track_identity(path)


def test_track_identity_for_an_unknown_video_is_rejected(workspace):
    rows = list(csv.reader(open(workspace["identity"], encoding="utf-8")))
    rows.append(["P4_S09_A09_zone_enter_exit_09_cam09", "A09", 1, "visual", "t", "2026-08-18", ""])
    with open(workspace["identity"], "w", encoding="utf-8", newline="") as file:
        csv.writer(file, lineterminator="\n").writerows(rows)
    with pytest.raises(ezp.ZoneEvalError, match="manifest에 없는"):
        run(workspace)


# --- 실행 옵션 동결 (현수 3번) ---


def test_nonstandard_tolerance_needs_an_explicit_flag(workspace):
    with pytest.raises(ezp.ZoneEvalError, match="공식 측정 조건"):
        run(workspace, event_tolerance_sec=3.0)


def test_nonstandard_flip_window_needs_an_explicit_flag(workspace):
    with pytest.raises(ezp.ZoneEvalError, match="공식 측정 조건"):
        run(workspace, flip_window_sec=0.2)


def test_diagnostic_run_is_marked_not_official(workspace):
    result = run(workspace, event_tolerance_sec=3.0, allow_nonstandard_tolerances=True)
    assert result["is_official"] is False


def test_official_run_is_marked_official(workspace):
    assert run(workspace)["is_official"] is True


def test_gt_overlap_selection_is_not_official(workspace):
    result = run(
        workspace, track_selection="gt-overlap", allow_nonstandard_tolerances=True
    )
    assert result["is_official"] is False


@pytest.mark.parametrize("value", [0.0, -1.0, float("nan"), float("inf")])
def test_impossible_time_options_are_rejected(workspace, value):
    with pytest.raises(ezp.ZoneEvalError, match="finite 양수"):
        run(workspace, event_tolerance_sec=value, allow_nonstandard_tolerances=True)


# --- 빠른 반전 정의 (현수 1번) ---


def test_dwell_then_exit_is_not_a_fast_flip():
    """체류하다 나가는 것은 경계에서 흔들린 것이 아니다.

    실측에서 빠른 반전 2건이 전부 DWELL -> EXIT였다. 기준 5번은 ENTER·EXIT
    반전을 묻는 항목이므로 이 조합은 세지 않는다.
    """
    events = [event(100, "ENTER"), event(400, "DWELL"), event(430, "EXIT")]
    assert ezp.count_flips(events, FPS, 1.0) == 0


def test_exit_then_enter_is_a_fast_flip():
    assert ezp.count_flips([event(100, "EXIT"), event(120, "ENTER")], FPS, 1.0) == 1


def test_restricted_entry_counts_as_an_entry():
    events = [event(100, "ENTER_RESTRICTED"), event(120, "EXIT")]
    assert ezp.count_flips(events, FPS, 1.0) == 1


def test_dwell_pair_is_not_a_flip():
    events = [event(100, "DWELL"), event(120, "DWELL_ALERT")]
    assert ezp.count_flips(events, FPS, 1.0) == 0


# --- Track이 끊긴 구간 (현수 2번) ---


def drop_track_after(workspace, frame: int):
    """지정 frame 이후로 Track이 사라지게 캐시를 고친다."""
    payload = json.loads(workspace["cache"].read_text(encoding="utf-8"))
    frames = payload["videos"][VIDEO_ID]["frames"]
    for text in list(frames):
        if int(text) > frame:
            del frames[text]
    workspace["cache"].write_text(json.dumps(payload), encoding="utf-8")


def test_lost_track_still_produces_an_exit(workspace):
    """runtime은 Track이 사라지면 flush_stale_tracks로 EXIT를 만든다.

    평가가 Track이 있는 frame만 훑으면 이 경로가 돌지 않아 EXIT가 아예 없는
    결과가 나온다. 실제 pipeline과 다른 수치를 공식 결과로 쓰게 된다.
    """
    drop_track_after(workspace, workspace["enter"] + 60)
    result = run(workspace)
    types = [e["type"] for e in result["per_video"][0]["image"]["event_list"]]
    assert "ENTER" in types
    assert "EXIT" in types, "Track이 끊긴 뒤 EXIT가 나오지 않았다"


def test_events_are_bounded_by_the_manifest_frame_count(workspace):
    """영상 전체를 순회하지만 frame 수를 넘어가지는 않는다."""
    result = run(workspace)
    for path in ezp.PATHS:
        for entry in result["per_video"][0][path]["event_list"]:
            assert 0 <= entry["frame"] < 300
