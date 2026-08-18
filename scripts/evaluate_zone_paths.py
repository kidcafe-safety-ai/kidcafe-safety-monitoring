"""채택 기준 2~5번을 image 경로와 Homography 경로로 각각 측정해 비교한다.

두 경로에 **같은 Track·같은 foot point**를 넣고 Zone 정의만 바꾼다. 그래야 판정
차이가 좌표 경로 차이로 귀속된다. foot point는 `cache_zone_foot_points.py`가
미리 만든 캐시에서 읽으므로 이 스크립트는 모델도 영상도 필요 없다.

- image 경로: 픽셀 foot point를 프레임 크기로 정규화해 image polygon으로 판정
- Homography 경로: 픽셀 foot point를 floor 좌표로 변환해 floor polygon으로 판정

두 경로 모두 판정 결과를 같은 `EventManager`에 넣어 ENTER·EXIT를 만든다.
debounce·hysteresis 설정도 같으므로 Event 차이 역시 좌표 경로에서만 온다.

측정 항목은 `docs/homography_calibration.md` 6절의 채택 기준 2~5번이다.

| # | 기준 | 이 스크립트의 산출 |
|---|---|---|
| 2 | Zone inside/outside 정확도 개선 | frame 단위 정확도 |
| 3 | Zone 오판정 30% 감소 또는 정확도 5%p 개선 | frame 단위 오판정 수 |
| 4 | ENTER·EXIT Event 오류 30% 감소 | 누락·오검출·중복 Event 수 |
| 5 | 빠른 ENTER·EXIT 반전 증가 없음 | 임계 시간 내 반전 수 |

**비율과 함께 원시 건수를 항상 기록한다.** 계획서 15절이 표본이 작을 때 그렇게
하도록 정하고 있고, 이번 표본은 영상 12개·경계 24건으로 작다. 오류 1건이
비율에서 크게 움직이므로 비율만 보면 잘못 읽는다.

사용 예:

    python scripts/evaluate_zone_paths.py \\
        --cache outputs/phase4_zone_eval/foot_points.json \\
        --manifest data/annotations/phase4/recordings_manifest.csv \\
        --intervals data/annotations/phase4/zone_intervals.csv \\
        --review-plan data/annotations/phase4/zone_eval/recording_review_plan.csv \\
        --output outputs/phase4_zone_eval/zone_path_comparison.json
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.common.types import Track  # noqa: E402
from src.events.event_manager import EventManager  # noqa: E402
from src.geofencing.floor_plane import (  # noqa: E402
    FloorPlaneTransformer,
    load_calibration,
)
from src.geofencing.floor_zone import FloorZoneChecker, load_floor_zones  # noqa: E402
from src.geofencing.zone_checker import ZoneChecker  # noqa: E402
from src.geofencing.zone_loader import load_zones  # noqa: E402

RESULT_SCHEMA_VERSION = "phase4_zone_path_comparison_v1"
CACHE_SCHEMA_VERSION = "phase4_zone_foot_points_v1"
PATHS = ("image", "homography")

# ENTER·EXIT를 맞다고 볼 시간 여유(초). EventManager가 enter 0.3초·exit 0.5초
# 확정 지연을 두므로 예측은 구조적으로 ground truth보다 늦게 나온다. 그 지연을
# 오류로 세지 않도록 기본값을 확정 지연보다 넉넉히 잡는다. 부호 있는 오차도
# 함께 기록해 지연 자체를 볼 수 있게 한다.
DEFAULT_EVENT_TOLERANCE_SEC = 1.0
# 이 시간 안에 ENTER 다음 EXIT(또는 반대)가 오면 빠른 반전으로 센다.
DEFAULT_FLIP_WINDOW_SEC = 1.0


class ZoneEvalError(RuntimeError):
    """측정을 수행할 수 없는 입력 상태."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--intervals", required=True)
    parser.add_argument("--review-plan", required=True)
    parser.add_argument("--repo-root", default=".")
    parser.add_argument(
        "--track-selection",
        choices=("longest", "gt-overlap"),
        default="longest",
        help=(
            "longest=영상에서 가장 오래 잡힌 Track (기본). "
            "gt-overlap=ground truth 구간과 가장 많이 겹치는 Track (진단용, "
            "정답을 보고 고르므로 두 경로 모두에 같은 이점을 준다)."
        ),
    )
    parser.add_argument(
        "--event-tolerance-sec", type=float, default=DEFAULT_EVENT_TOLERANCE_SEC
    )
    parser.add_argument("--flip-window-sec", type=float, default=DEFAULT_FLIP_WINDOW_SEC)
    parser.add_argument("--output", required=True)
    return parser.parse_args()


def read_csv(path: Path, required: Sequence[str]) -> List[dict]:
    if not path.is_file():
        raise ZoneEvalError(f"파일이 없습니다: {path}")
    with open(path, "r", encoding="utf-8", newline="") as file:
        rows = list(csv.DictReader(file))
    if not rows:
        raise ZoneEvalError(f"{path}에 행이 없습니다.")
    missing = [f for f in required if f not in rows[0]]
    if missing:
        raise ZoneEvalError(f"{path}에 필드가 없습니다: {missing}")
    return rows


def parse_notes(text: str) -> Dict[str, str]:
    """`a=1; b=2` 형태의 notes를 dict로 읽는다."""
    result: Dict[str, str] = {}
    for chunk in text.split(";"):
        chunk = chunk.strip()
        if "=" in chunk:
            key, value = chunk.split("=", 1)
            result[key.strip()] = value.strip()
    return result


def index_calibrations(root: Path) -> Dict[str, Path]:
    """`calibration_version`으로 config 파일을 찾을 수 있게 색인한다.

    경로를 version 문자열에서 조립하지 않는다. 이름 규칙이 바뀌면 조용히 다른
    파일을 집게 되므로, 파일 안의 값을 읽어 대조한다.
    """
    index: Dict[str, Path] = {}
    directory = root / "configs" / "camera_calibration"
    for path in sorted(directory.glob("*.json")):
        version = json.loads(path.read_text(encoding="utf-8")).get("calibration_version")
        if not isinstance(version, str):
            continue
        if version in index:
            raise ZoneEvalError(f"calibration_version이 중복입니다: {version}")
        index[version] = path
    if not index:
        raise ZoneEvalError(f"calibration config를 찾을 수 없습니다: {directory}")
    return index


def build_video_inputs(
    review_plan: Sequence[dict], root: Path
) -> Dict[str, Dict[str, Path]]:
    """video_id마다 calibration·image Zone·floor Zone 경로를 정한다."""
    calibrations = index_calibrations(root)
    inputs: Dict[str, Dict[str, Path]] = {}
    for row in review_plan:
        video_id = Path(row["contract_filename"]).stem
        notes = parse_notes(row.get("notes", ""))
        version = notes.get("calibration_version")
        image_zone_text = notes.get("image_zone")
        if not version or not image_zone_text:
            raise ZoneEvalError(
                f"{video_id}: notes에 calibration_version·image_zone이 필요합니다."
            )
        if version not in calibrations:
            raise ZoneEvalError(f"{video_id}: calibration_version을 찾을 수 없습니다: {version}")
        image_zone = root / image_zone_text
        floor_zone = image_zone.with_name(image_zone.name.replace("image_", "floor_", 1))
        for path in (image_zone, floor_zone):
            if not path.is_file():
                raise ZoneEvalError(f"{video_id}: Zone 파일이 없습니다: {path}")
        inputs[video_id] = {
            "calibration": calibrations[version],
            "calibration_version": version,
            "image_zone": image_zone,
            "floor_zone": floor_zone,
            "original_filename": row.get("original_filename", ""),
            "target_actor": notes.get("ground_truth_actor", ""),
        }
    return inputs


def pick_track(
    frames: Dict[str, List[dict]], mode: str, enter: int, exit_: int
) -> Tuple[Optional[int], dict]:
    """영상에서 평가 대상 Track 하나를 고른다.

    두 경로가 **같은** Track을 쓰기 때문에 선택 규칙이 두 경로 사이의 비교를
    치우치게 하지는 않는다. 다만 절대 수치에는 영향을 주므로 어떤 규칙으로
    골랐는지와 후보가 여럿이었는지를 함께 남긴다.
    """
    total: Dict[int, int] = {}
    inside: Dict[int, int] = {}
    for text, tracks in frames.items():
        number = int(text)
        for track in tracks:
            track_id = int(track["track_id"])
            total[track_id] = total.get(track_id, 0) + 1
            if enter <= number < exit_:
                inside[track_id] = inside.get(track_id, 0) + 1
    if not total:
        return None, {"reason": "Track이 없다"}

    scores = inside if mode == "gt-overlap" else total
    if not scores:
        return None, {"reason": "ground truth 구간에 Track이 없다"}
    best = max(sorted(scores), key=lambda t: scores[t])
    ranked = sorted(scores.values(), reverse=True)
    runner_up = ranked[1] if len(ranked) > 1 else 0
    return best, {
        "selection": mode,
        "track_id": best,
        "frames_total": total.get(best, 0),
        "frames_in_gt_interval": inside.get(best, 0),
        "candidate_tracks": len(total),
        "runner_up_score": runner_up,
        "ambiguous": bool(runner_up and runner_up >= scores[best] * 0.8),
    }


def judge_frames(
    frames: Dict[str, List[dict]],
    track_id: int,
    zone_id: str,
    width: int,
    height: int,
    image_checker: ZoneChecker,
    floor_checker: FloorZoneChecker,
    transformer: FloorPlaneTransformer,
) -> List[dict]:
    """frame마다 두 경로의 Zone 포함 여부를 함께 낸다."""
    rows: List[dict] = []
    for text in sorted(frames, key=int):
        entry = next(
            (t for t in frames[text] if int(t["track_id"]) == track_id), None
        )
        if entry is None:
            continue
        foot = [float(entry["foot_point"][0]), float(entry["foot_point"][1])]
        track = Track(
            track_id=track_id,
            bbox=[float(v) for v in entry["bbox"]],
            foot_point=foot,
            confidence=float(entry["confidence"]),
        )
        rows.append(
            {
                "frame": int(text),
                "track": track,
                "image": zone_id in image_checker.check(track),
                "homography": zone_id in floor_checker.check_point(
                    transformer.transform(list(foot))
                ),
            }
        )
    return rows


def run_events(
    judged: Sequence[dict], zones, fps: float, path: str, video_id: str
) -> List[dict]:
    """한 경로의 판정 결과를 EventManager에 넣어 ENTER·EXIT를 만든다."""
    manager = EventManager(zones=zones, fps=fps)
    events: List[dict] = []
    for row in judged:
        zones_in = [zones[0].zone_id] if row[path] else []
        for event in manager.process(row["track"], zones_in, row["frame"], video_id):
            events.append({"frame": row["frame"], "type": str(event.event_type)})
    return events


def score_frames(judged: Sequence[dict], enter: int, exit_: int, path: str) -> dict:
    """frame 단위 정확도와 오판정 수 (채택 기준 2·3번)."""
    correct = wrong = false_inside = false_outside = 0
    for row in judged:
        truth = enter <= row["frame"] < exit_
        if row[path] == truth:
            correct += 1
        else:
            wrong += 1
            if row[path]:
                false_inside += 1
            else:
                false_outside += 1
    total = correct + wrong
    return {
        "frames_scored": total,
        "correct": correct,
        "wrong": wrong,
        "false_inside": false_inside,
        "false_outside": false_outside,
        "accuracy": round(correct / total, 6) if total else None,
    }


def score_events(
    events: Sequence[dict], enter: int, exit_: int, fps: float, tolerance_sec: float
) -> dict:
    """ENTER·EXIT Event 오류 수 (채택 기준 4번).

    ground truth는 영상마다 ENTER 1건·EXIT 1건이다. 허용 시간 안에 있는 Event가
    하나면 맞은 것으로, 없으면 누락, 허용 밖이거나 추가로 더 나오면 오검출로
    센다. 부호 있는 시간 오차도 함께 남겨 확정 지연을 볼 수 있게 한다.
    """
    tolerance = tolerance_sec * fps
    result = {"missed": 0, "false": 0, "duplicate": 0, "onset_error_sec": {}}
    for label, truth, kind in (("enter", enter, "ENTER"), ("exit", exit_, "EXIT")):
        matched = [e for e in events if e["type"] == kind and abs(e["frame"] - truth) <= tolerance]
        others = [e for e in events if e["type"] == kind and e not in matched]
        if not matched:
            result["missed"] += 1
            result["onset_error_sec"][label] = None
        else:
            best = min(matched, key=lambda e: abs(e["frame"] - truth))
            result["onset_error_sec"][label] = round((best["frame"] - truth) / fps, 4)
            result["duplicate"] += len(matched) - 1
        result["false"] += len(others)
    result["total_errors"] = result["missed"] + result["false"] + result["duplicate"]
    return result


def count_flips(events: Sequence[dict], fps: float, window_sec: float) -> int:
    """짧은 시간 안의 ENTER↔EXIT 반전 수 (채택 기준 5번)."""
    window = window_sec * fps
    flips = 0
    for earlier, later in zip(events, events[1:]):
        if earlier["type"] != later["type"] and later["frame"] - earlier["frame"] <= window:
            flips += 1
    return flips


def ratio_change(baseline: int, candidate: int) -> Optional[float]:
    """기준선 대비 감소 비율. 기준선이 0이면 비율을 정의하지 않는다."""
    if baseline == 0:
        return None
    return round((baseline - candidate) / baseline, 6)


def write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        # 바이너리로 쓴다. 텍스트 모드로 열면 Windows가 \n을 \r\n으로 바꿔
        # 같은 입력인데 OS에 따라 파일 바이트가 달라진다.
        with os.fdopen(handle, "wb") as file:
            text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
            file.write((text + "\n").encode("utf-8"))
            file.flush()
            os.fsync(file.fileno())
        os.replace(temp_name, path)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise


def evaluate(args: argparse.Namespace) -> dict:
    root = Path(args.repo_root).resolve()
    cache = json.loads(Path(args.cache).read_text(encoding="utf-8"))
    if cache.get("schema_version") != CACHE_SCHEMA_VERSION:
        raise ZoneEvalError(f"지원하지 않는 캐시 schema입니다: {cache.get('schema_version')}")

    manifest = {
        r["video_id"]: r
        for r in read_csv(Path(args.manifest), ("video_id", "fps", "width", "height"))
    }
    intervals = read_csv(
        Path(args.intervals),
        ("video_id", "zone_id", "enter_frame", "exit_frame", "review_status"),
    )
    plan = read_csv(
        Path(args.review_plan), ("contract_filename", "original_filename", "notes")
    )
    inputs = build_video_inputs(plan, root)

    per_video: List[dict] = []
    totals = {p: {"frames": 0, "wrong": 0, "correct": 0, "event_errors": 0, "flips": 0}
              for p in PATHS}

    for row in intervals:
        video_id = row["video_id"]
        if row["review_status"] != "reviewed":
            raise ZoneEvalError(f"{video_id}: reviewed가 아닌 interval은 측정에 쓸 수 없습니다.")
        if video_id not in manifest:
            raise ZoneEvalError(f"{video_id}: manifest에 없습니다.")
        if video_id not in inputs:
            raise ZoneEvalError(f"{video_id}: 대응표에 없습니다.")
        if video_id not in cache["videos"]:
            raise ZoneEvalError(f"{video_id}: 캐시에 없습니다.")

        meta = manifest[video_id]
        fps = float(meta["fps"])
        width, height = int(meta["width"]), int(meta["height"])
        enter, exit_ = int(row["enter_frame"]), int(row["exit_frame"])
        zone_id = row["zone_id"]
        entry = inputs[video_id]

        calibration = load_calibration(str(entry["calibration"]))
        if (calibration.frame_width, calibration.frame_height) != (width, height):
            raise ZoneEvalError(f"{video_id}: calibration 해상도가 manifest와 다릅니다.")
        image_zones = load_zones(str(entry["image_zone"]))
        floor_config = load_floor_zones(str(entry["floor_zone"]))
        image_checker = ZoneChecker(image_zones, width, height)
        floor_checker = FloorZoneChecker(floor_config)
        transformer = FloorPlaneTransformer(calibration)

        frames = cache["videos"][video_id]["frames"]
        track_id, selection = pick_track(frames, args.track_selection, enter, exit_)
        if track_id is None:
            raise ZoneEvalError(f"{video_id}: 평가할 Track을 고르지 못했습니다.")

        judged = judge_frames(
            frames, track_id, zone_id, width, height,
            image_checker, floor_checker, transformer,
        )
        if not judged:
            raise ZoneEvalError(f"{video_id}: 선택한 Track의 frame이 없습니다.")

        video_result = {
            "video_id": video_id,
            "original_filename": entry["original_filename"],
            "calibration_version": entry["calibration_version"],
            "ground_truth": {"enter_frame": enter, "exit_frame": exit_},
            "track": selection,
        }
        for path in PATHS:
            events = run_events(judged, image_zones if path == "image" else
                                floor_config.zones, fps, path, video_id)
            frame_score = score_frames(judged, enter, exit_, path)
            event_score = score_events(events, enter, exit_, fps, args.event_tolerance_sec)
            flips = count_flips(events, fps, args.flip_window_sec)
            video_result[path] = {
                "frames": frame_score,
                "events": event_score,
                "fast_flips": flips,
                "event_list": events,
            }
            totals[path]["frames"] += frame_score["frames_scored"]
            totals[path]["correct"] += frame_score["correct"]
            totals[path]["wrong"] += frame_score["wrong"]
            totals[path]["event_errors"] += event_score["total_errors"]
            totals[path]["flips"] += flips
        per_video.append(video_result)

    for path in PATHS:
        scored = totals[path]["frames"]
        totals[path]["accuracy"] = (
            round(totals[path]["correct"] / scored, 6) if scored else None
        )

    base, cand = totals["image"], totals["homography"]
    accuracy_gain = (
        round((cand["accuracy"] - base["accuracy"]) * 100.0, 4)
        if base["accuracy"] is not None and cand["accuracy"] is not None
        else None
    )
    criteria = {
        "2_zone_accuracy_improved": {
            "image_accuracy": base["accuracy"],
            "homography_accuracy": cand["accuracy"],
            "accuracy_gain_percentage_point": accuracy_gain,
            "passes": None if accuracy_gain is None else accuracy_gain > 0,
        },
        "3_zone_error_reduction": {
            "image_wrong_frames": base["wrong"],
            "homography_wrong_frames": cand["wrong"],
            "reduction_ratio": ratio_change(base["wrong"], cand["wrong"]),
            "accuracy_gain_percentage_point": accuracy_gain,
            "passes": _passes_criterion_3(base["wrong"], cand["wrong"], accuracy_gain),
        },
        "4_event_error_reduction": {
            "image_event_errors": base["event_errors"],
            "homography_event_errors": cand["event_errors"],
            "reduction_ratio": ratio_change(base["event_errors"], cand["event_errors"]),
            "passes": _passes_ratio(base["event_errors"], cand["event_errors"], 0.30),
        },
        "5_fast_flips_not_increased": {
            "image_fast_flips": base["flips"],
            "homography_fast_flips": cand["flips"],
            "passes": cand["flips"] <= base["flips"],
        },
    }

    boundaries = len(per_video) * 2
    return {
        "schema_version": RESULT_SCHEMA_VERSION,
        "tracker": cache.get("tracker"),
        "settings": {
            "track_selection": args.track_selection,
            "event_tolerance_sec": args.event_tolerance_sec,
            "flip_window_sec": args.flip_window_sec,
        },
        "sample": {
            "videos": len(per_video),
            "intervals": len(per_video),
            "boundary_events": boundaries,
            "note": (
                "표본이 작다. 계획서 15절에 따라 비율과 함께 원시 건수를 기록한다. "
                f"경계 {boundaries}건에서는 오류 1건이 "
                f"{round(100.0 / boundaries, 2)}%p로 움직인다."
            ),
        },
        "totals": totals,
        "criteria": criteria,
        "per_video": per_video,
    }


def _passes_ratio(baseline: int, candidate: int, required: float) -> Optional[bool]:
    if baseline == 0:
        return None
    return (baseline - candidate) / baseline >= required


def _passes_criterion_3(
    baseline: int, candidate: int, accuracy_gain: Optional[float]
) -> Optional[bool]:
    """오판정 30% 감소 **또는** 정확도 5%p 개선."""
    by_ratio = _passes_ratio(baseline, candidate, 0.30)
    by_accuracy = None if accuracy_gain is None else accuracy_gain >= 5.0
    if by_ratio is None and by_accuracy is None:
        return None
    return bool(by_ratio) or bool(by_accuracy)


def main() -> None:
    args = parse_args()
    try:
        payload = evaluate(args)
    except (ZoneEvalError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc

    write_json_atomic(Path(args.output), payload)
    sample, totals = payload["sample"], payload["totals"]
    print(f"영상 {sample['videos']}개 / 경계 {sample['boundary_events']}건")
    print(f"{'':12s} {'정확도':>9s} {'오판정':>7s} {'Event오류':>9s} {'빠른반전':>8s}")
    for path in PATHS:
        t = totals[path]
        accuracy = f"{t['accuracy'] * 100:.3f}%" if t["accuracy"] is not None else "-"
        print(
            f"{path:12s} {accuracy:>9s} {t['wrong']:7d} {t['event_errors']:9d} "
            f"{t['flips']:8d}"
        )
    print()
    for key, value in payload["criteria"].items():
        verdict = value["passes"]
        mark = "통과" if verdict else ("판정불가" if verdict is None else "미달")
        print(f"  {key}: {mark}")
    print(f"\n-> {args.output}")
    print("표본이 작으므로 비율보다 원시 건수를 먼저 본다.")


if __name__ == "__main__":
    main()
