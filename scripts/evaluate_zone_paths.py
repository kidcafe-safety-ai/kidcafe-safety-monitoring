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
        --manifest data/annotations/phase4/zone_eval/recordings_manifest.csv \\
        --intervals data/annotations/phase4/zone_intervals.csv \\
        --review-plan data/annotations/phase4/zone_eval/recording_review_plan.csv \\
        --output outputs/phase4_zone_eval/zone_path_comparison.json
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import phase4_recording_contract as contract  # noqa: E402

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
# 이 시간 안에 진입 계열과 EXIT가 뒤집히면 빠른 반전으로 센다.
DEFAULT_FLIP_WINDOW_SEC = 1.0

# 공식 측정에 쓰는 값. 이 두 값은 결과를 바꿀 수 있다. tolerance를 키우면 기준
# 4번의 누락·오검출이 줄고, flip window를 바꾸면 기준 5번의 반전 수가 달라진다.
# 같은 데이터로도 실행 옵션에 따라 판정이 뒤집히므로, 공식 결과에는 이 값만
# 허용하고 다르면 `--allow-nonstandard-tolerances`를 명시하게 한다.
OFFICIAL_EVENT_TOLERANCE_SEC = 1.0
OFFICIAL_FLIP_WINDOW_SEC = 1.0

# 공식 캐시를 만든 detector·tracker. 형식만 보면 64자리 hex 아무 값이나 통과해
# 다른 모델로 만든 캐시가 공식 결과로 둔갑할 수 있다. 실제 값을 여기 동결하고
# 정확히 일치할 때만 공식으로 인정한다. 모델을 바꾸면 이 상수와 문서 7.4절을
# 함께 고쳐야 하고, 그것이 공식 수치를 다시 내야 한다는 신호가 된다.
OFFICIAL_TRACKER_MODEL = "yolo26n.pt"
OFFICIAL_TRACKER_MODEL_SHA256 = (
    "9b09cc8bf347f0fc8a5f7657480587f25db09b34bf33b0652110fb03a8ad4fef"
)
OFFICIAL_TRACKER_CONFIDENCE = 0.5

# 채택 기준 5번은 "빠른 ENTER·EXIT 반전 증가 없음"이다. 진입 계열과 EXIT
# 사이의 전환만 반전으로 센다. DWELL은 체류 중에 나오는 Event라 DWELL 다음
# EXIT는 반전이 아니라 정상적인 이탈이다.
ENTRY_EVENT_TYPES = ("ENTER", "ENTER_RESTRICTED")
EXIT_EVENT_TYPES = ("EXIT",)

TRACK_IDENTITY_FIELDS = (
    "video_id",
    "ground_truth_actor",
    "track_id",
    "verification_method",
    "reviewer_id",
    "verified_at",
    "notes",
)

# 영상별 calibration·Zone 파일의 동결 SHA-256. 경로는 review plan에 있지만
# 경로만 맞추고 내용을 바꾸면 다른 입력으로 공식 결과를 만들 수 있다. 판정에
# 실제로 쓰이는 세 파일의 revision을 여기서 대조한다.
INPUT_CHECKSUM_FIELDS = (
    "video_id",
    "calibration_version",
    "calibration_sha256",
    "image_zone_sha256",
    "floor_zone_sha256",
)


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
        "--track-identity",
        default=None,
        help=(
            "다중 인원 영상의 대상 Track을 사람이 확인해 적어둔 CSV. 여기 있는 "
            "영상은 선택된 Track이 기록과 같은지 검증한다. 기본값은 "
            "data/annotations/phase4/zone_eval/track_identity.csv."
        ),
    )
    parser.add_argument(
        "--input-checksums",
        default=None,
        help=(
            "영상별 calibration·image Zone·floor Zone의 동결 SHA-256 CSV. "
            "기본값은 data/annotations/phase4/zone_eval/input_checksums.csv."
        ),
    )
    parser.add_argument(
        "--event-tolerance-sec", type=float, default=DEFAULT_EVENT_TOLERANCE_SEC
    )
    parser.add_argument("--flip-window-sec", type=float, default=DEFAULT_FLIP_WINDOW_SEC)
    parser.add_argument(
        "--allow-nonstandard-tolerances",
        action="store_true",
        help=(
            "공식값과 다른 tolerance·flip window로 실행한다. 결과는 "
            "is_official=false로 표시된다."
        ),
    )
    parser.add_argument("--output", required=True)
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(path: Path) -> str:
    """줄바꿈을 LF로 맞춘 뒤 해시한다.

    동결값과 **대조**하는 텍스트 파일에만 쓴다. Windows는 `core.autocrlf`로
    작업 트리의 LF를 CRLF로 바꿔 두므로, 원시 바이트를 해시하면 같은 파일이
    OS마다 다른 값이 된다. 실제로 Windows에서 calibration JSON이 동결값과
    다르다고 거부됐고, 원인은 내용이 아니라 줄바꿈이었다.

    JSON·CSV에서 CRLF와 LF는 같은 내용이므로 정규화해도 놓치는 변조가 없다.
    내용이 한 글자라도 바뀌면 값은 그대로 달라진다.
    """
    raw = Path(path).read_bytes()
    return hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest()


def check_positive_seconds(name: str, value: float) -> None:
    """시간 옵션이 실수로 음수·NaN이 되면 판정이 조용히 뒤집힌다."""
    if not math.isfinite(value) or value <= 0:
        raise ZoneEvalError(f"{name}는 finite 양수여야 합니다: {value}")


def resolve_officiality(args: argparse.Namespace) -> bool:
    """실행 옵션이 공식 측정 조건인지 판단한다."""
    check_positive_seconds("--event-tolerance-sec", args.event_tolerance_sec)
    check_positive_seconds("--flip-window-sec", args.flip_window_sec)
    standard = (
        args.event_tolerance_sec == OFFICIAL_EVENT_TOLERANCE_SEC
        and args.flip_window_sec == OFFICIAL_FLIP_WINDOW_SEC
        and args.track_selection == "longest"
    )
    if not standard and not args.allow_nonstandard_tolerances:
        raise ZoneEvalError(
            "공식 측정 조건이 아닙니다. event-tolerance-sec="
            f"{OFFICIAL_EVENT_TOLERANCE_SEC}, flip-window-sec="
            f"{OFFICIAL_FLIP_WINDOW_SEC}, track-selection=longest가 공식값입니다. "
            "진단 목적이면 --allow-nonstandard-tolerances를 붙이세요."
        )
    return standard


def read_csv(
    path: Path, required: Sequence[str], allow_empty: bool = False
) -> List[dict]:
    if not path.is_file():
        raise ZoneEvalError(f"파일이 없습니다: {path}")
    with open(path, "r", encoding="utf-8", newline="") as file:
        reader = csv.DictReader(file)
        header = reader.fieldnames or []
        rows = list(reader)
    if not rows and not allow_empty:
        raise ZoneEvalError(f"{path}에 행이 없습니다.")
    missing = [f for f in required if f not in header]
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


def select_zone(zones: Sequence, zone_id: str, label: str):
    """요청된 `zone_id`와 같은 Zone을 명시적으로 고른다.

    예전에는 `zones[0]`을 썼다. Zone이 하나일 때는 맞지만 여러 개가 되거나 파일
    안의 순서가 바뀌면 frame 판정과 Event 판정이 서로 다른 Zone을 보게 된다.
    """
    matched = [zone for zone in zones if zone.zone_id == zone_id]
    if not matched:
        available = sorted(zone.zone_id for zone in zones)
        raise ZoneEvalError(f"{label}에 zone_id가 없습니다: {zone_id} (있는 것: {available})")
    if len(matched) > 1:
        raise ZoneEvalError(f"{label}에 zone_id가 중복입니다: {zone_id}")
    return matched[0]


def load_track_identity(path: Path) -> Dict[str, dict]:
    """사람이 확인한 대상 Track 기록을 읽는다.

    다중 인원 영상은 Track 선택 규칙이 어느 사람을 고를지가 절대 수치를 바꾼다.
    누가 언제 무엇으로 확인했는지를 파일로 남겨야 나중에 캐시나 tracker가 바뀌어도
    같은 확인을 다시 할 수 있다.
    """
    # 확인이 필요한 영상이 아직 없으면 헤더만 있는 파일이 정상이다. 다중 인원
    # 영상에 기록이 없는 경우는 verify_track_identity가 따로 막는다.
    rows = read_csv(path, TRACK_IDENTITY_FIELDS, allow_empty=True)
    index: Dict[str, dict] = {}
    for row in rows:
        video_id = row["video_id"].strip()
        if video_id in index:
            raise ZoneEvalError(f"track identity에 중복 video_id가 있습니다: {video_id}")
        try:
            track_id = int(row["track_id"])
        except (TypeError, ValueError):
            raise ZoneEvalError(f"{video_id}: track_id가 정수가 아닙니다: {row['track_id']!r}")
        if not row["reviewer_id"].strip() or not row["verified_at"].strip():
            raise ZoneEvalError(f"{video_id}: reviewer_id와 verified_at이 필요합니다.")
        if not row["ground_truth_actor"].strip():
            raise ZoneEvalError(f"{video_id}: ground_truth_actor가 필요합니다.")
        index[video_id] = {
            "ground_truth_actor": row["ground_truth_actor"].strip(),
            "track_id": track_id,
            "verification_method": row["verification_method"].strip(),
            "reviewer_id": row["reviewer_id"].strip(),
            "verified_at": row["verified_at"].strip(),
            "notes": row["notes"].strip(),
        }
    return index


def parse_actor_ids(text: str) -> List[str]:
    """manifest·review plan의 `A01|A02` 형태를 목록으로 읽는다."""
    return [chunk.strip() for chunk in str(text or "").split("|") if chunk.strip()]


def verify_track_identity(
    video_id: str,
    chosen: int,
    record: Optional[dict],
    official: bool,
    target_actor: str,
    actor_ids: Sequence[str],
    primary_actor_id: str,
) -> Optional[dict]:
    """고른 Track이 사람이 확인한 **그 사람**인지 본다.

    Track ID만 대조하면 절반만 막힌다. `track_identity.csv`의
    `ground_truth_actor`를 A01에서 A02로 바꿔도 Track ID가 같으면 통과하므로,
    기록이 어느 사람을 가리키는지는 아무도 검증하지 않는 상태가 된다. 그래서
    actor를 review plan·manifest와 함께 묶어 확인한다.

    다중 인원 영상은 확인 기록 자체를 필수로 본다. 어느 사람을 평가했는지가
    절대 수치를 바꾸는데 기록이 없으면 재검증할 방법이 없기 때문이다.

    공식 측정에서는 어긋나면 멈춘다. 캐시나 tracker가 바뀌어 다른 사람이
    평가되는 것을 공식 수치로 낼 수는 없기 때문이다.

    진단 실행에서는 멈추지 않고 불일치를 결과에 적는다. `gt-overlap`처럼 다른
    Track을 고르는 규칙을 일부러 돌려보는 것이 진단의 목적이고, 그 규칙이 대상이
    아닌 사람을 고른다는 사실 자체가 봐야 할 결과다.
    """
    multi_actor = len(actor_ids) > 1
    if record is None:
        if multi_actor and official:
            raise ZoneEvalError(
                f"{video_id}: 인원이 {len(actor_ids)}명인데 track identity 기록이 "
                "없습니다. 대상 Track을 확인해 기록하세요."
            )
        return None

    actor = record["ground_truth_actor"]
    # actor는 세 artifact가 같은 사람을 가리킬 때만 유효하다. review plan에
    # ground_truth_actor가 없는 단일 인원 영상은 manifest의 대표 actor를 쓴다.
    expected_actor = target_actor.strip() or primary_actor_id.strip()
    if expected_actor and actor != expected_actor:
        raise ZoneEvalError(
            f"{video_id}: track identity의 ground_truth_actor가 대응표와 다릅니다: "
            f"{actor!r} != {expected_actor!r}"
        )
    if actor_ids and actor not in actor_ids:
        raise ZoneEvalError(
            f"{video_id}: track identity의 ground_truth_actor가 manifest의 "
            f"actor_ids에 없습니다: {actor!r} not in {list(actor_ids)}"
        )

    entry = dict(record)
    entry["selected_track_id"] = chosen
    entry["expected_actor"] = expected_actor
    entry["actor_ids"] = list(actor_ids)
    entry["primary_actor_id"] = primary_actor_id
    entry["matches_verified_track"] = chosen == record["track_id"]
    if entry["matches_verified_track"]:
        return entry
    message = (
        f"{video_id}: 선택된 Track {chosen}이 확인 기록의 Track "
        f"{record['track_id']}({actor})과 다릅니다."
    )
    if official:
        raise ZoneEvalError(
            message + " 캐시나 tracker가 바뀌었을 수 있으니 대상 인물을 다시 확인하세요."
        )
    print(f"경고: {message} 진단 실행이므로 계속합니다.", flush=True)
    return entry


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
    judged: Sequence[dict],
    zone,
    fps: float,
    path: str,
    video_id: str,
    frame_count: int,
) -> List[dict]:
    """한 경로의 판정 결과를 EventManager에 넣어 ENTER·EXIT를 만든다.

    **runtime과 같은 순서로 돈다.** `src/main.py`는 frame마다 `process()` 뒤에
    `flush_stale_tracks()`를 부른다. 후자는 Track이 사라진 채로 grace period가
    지나면 EXIT를 만든다. 평가가 Track이 있는 frame만 훑으면 이 경로가 아예 돌지
    않아, Track이 끊기는 영상에서 실제 pipeline과 ENTER·EXIT 결과가 갈린다.

    그래서 영상 전체 frame을 순회하고, 선택한 Track이 없는 frame에서도
    `flush_stale_tracks()`를 부른다.
    """
    manager = EventManager(zones=[zone], fps=fps)
    by_frame = {row["frame"]: row for row in judged}
    events: List[dict] = []
    for frame in range(frame_count):
        row = by_frame.get(frame)
        active: Set[int] = set()
        if row is not None:
            active = {int(row["track"].track_id)}
            zones_in = [zone.zone_id] if row[path] else []
            for event in manager.process(row["track"], zones_in, frame, video_id):
                events.append({"frame": frame, "type": str(event.event_type)})
        for event in manager.flush_stale_tracks(active, frame, video_id):
            events.append({"frame": frame, "type": str(event.event_type)})
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
    """짧은 시간 안의 진입↔EXIT 반전 수 (채택 기준 5번).

    기준 5번은 "빠른 ENTER·EXIT 반전 증가 없음"이다. 따라서 진입 계열(ENTER,
    ENTER_RESTRICTED)과 EXIT 사이의 전환만 센다. 예전에는 인접 Event의 type이
    다르기만 하면 셌는데, 그러면 DWELL 다음 EXIT처럼 반전이 아닌 조합까지
    들어간다. 체류하다 나가는 것은 정상적인 이탈이지 경계에서 흔들린 것이 아니다.
    """
    window = window_sec * fps
    flips = 0
    for earlier, later in zip(events, events[1:]):
        pair = (earlier["type"], later["type"])
        reversal = (
            pair[0] in ENTRY_EVENT_TYPES and pair[1] in EXIT_EVENT_TYPES
        ) or (pair[0] in EXIT_EVENT_TYPES and pair[1] in ENTRY_EVENT_TYPES)
        if reversal and later["frame"] - earlier["frame"] <= window:
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


def verify_cache_against_manifest(video_id: str, entry: dict, meta: dict) -> None:
    """캐시가 manifest가 가리키는 영상으로 만들어졌는지 확인한다.

    캐시는 tracking 결과를 그대로 담고 있어서 안을 봐도 어느 영상인지 알기
    어렵다. 다른 영상으로 만든 캐시를 넣으면 ground truth의 frame 번호가 다른
    시점을 가리키는데 수치는 그럴듯하게 나온다. 그래서 계약 값과 대조한다.
    """
    expected_digest = (meta.get("checksum_sha256") or "").strip()
    actual_digest = (entry.get("video_sha256") or "").strip()
    if not actual_digest:
        raise ZoneEvalError(f"{video_id}: 캐시에 video_sha256이 없습니다.")
    if actual_digest != expected_digest:
        raise ZoneEvalError(
            f"{video_id}: 캐시의 영상 SHA-256이 manifest와 다릅니다: "
            f"{actual_digest} != {expected_digest}"
        )
    expected_frames = int(meta["frame_count"])
    if int(entry.get("frame_count", -1)) != expected_frames:
        raise ZoneEvalError(
            f"{video_id}: 캐시 frame 수가 manifest와 다릅니다: "
            f"{entry.get('frame_count')} != {expected_frames}"
        )
    cached_fps = entry.get("fps")
    if cached_fps is None or abs(float(cached_fps) - float(meta["fps"])) > 0.01:
        raise ZoneEvalError(
            f"{video_id}: 캐시 fps가 manifest와 다릅니다: {cached_fps} != {meta['fps']}"
        )


def verify_tracker_provenance(cache: dict, official: bool) -> dict:
    """어떤 모델로 만든 캐시인지 확인한다.

    형식 검사만으로는 부족하다. 64자리 hex이기만 하면 `000...000`도 통과하므로
    캐시의 tracker 항목을 유효한 형식의 다른 값으로 바꿔 공식 결과를 만들 수
    있다. 공식 실행에서는 동결 상수와 **정확히** 일치할 때만 통과시킨다.

    진단 실행은 다른 모델을 일부러 넣어보는 것이 목적이므로 형식만 본다.
    """
    tracker = cache.get("tracker")
    if not isinstance(tracker, dict):
        raise ZoneEvalError("캐시에 tracker 정보가 없습니다.")
    digest = str(tracker.get("model_sha256") or "")
    if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise ZoneEvalError(f"캐시의 tracker model_sha256 형식이 잘못됐습니다: {digest!r}")
    if tracker.get("confidence") is None:
        raise ZoneEvalError("캐시에 tracker confidence가 없습니다.")
    if not official:
        return tracker

    model = str(tracker.get("model") or "")
    if model != OFFICIAL_TRACKER_MODEL:
        raise ZoneEvalError(
            f"공식 캐시의 tracker model이 동결값과 다릅니다: "
            f"{model!r} != {OFFICIAL_TRACKER_MODEL!r}"
        )
    if digest != OFFICIAL_TRACKER_MODEL_SHA256:
        raise ZoneEvalError(
            f"공식 캐시의 tracker model_sha256이 동결값과 다릅니다: "
            f"{digest} != {OFFICIAL_TRACKER_MODEL_SHA256}"
        )
    confidence = float(tracker["confidence"])
    if abs(confidence - OFFICIAL_TRACKER_CONFIDENCE) > 1e-9:
        raise ZoneEvalError(
            f"공식 캐시의 tracker confidence가 동결값과 다릅니다: "
            f"{confidence} != {OFFICIAL_TRACKER_CONFIDENCE}"
        )
    return tracker


def load_input_checksums(path: Path) -> Dict[str, dict]:
    """영상별 calibration·Zone 파일의 동결 SHA-256을 읽는다."""
    rows = read_csv(path, INPUT_CHECKSUM_FIELDS)
    index: Dict[str, dict] = {}
    for row in rows:
        video_id = row["video_id"].strip()
        if video_id in index:
            raise ZoneEvalError(f"input checksum에 중복 video_id가 있습니다: {video_id}")
        entry = {}
        for field in INPUT_CHECKSUM_FIELDS[1:]:
            value = (row[field] or "").strip()
            if not value:
                raise ZoneEvalError(f"{video_id}: input checksum의 {field}가 비어 있습니다.")
            if field.endswith("_sha256") and (
                len(value) != 64 or any(c not in "0123456789abcdef" for c in value)
            ):
                raise ZoneEvalError(
                    f"{video_id}: input checksum의 {field} 형식이 잘못됐습니다: {value!r}"
                )
            entry[field] = value
        index[video_id] = entry
    return index


def verify_input_checksums(
    video_id: str, entry: dict, record: Optional[dict], official: bool
) -> dict:
    """판정에 실제로 쓰는 calibration·Zone 파일의 revision을 대조한다.

    review plan은 경로만 담고 있어서, 경로를 그대로 둔 채 calibration이나 Zone
    파일의 내용만 바꾸면 다른 입력으로 만든 결과가 공식값처럼 나온다. 동결
    manifest의 SHA-256과 대조해 그 경로를 막는다.

    공식 실행에서는 기록이 없으면 그 자체로 실패다. 기록이 없는 영상은
    변조 여부를 판단할 근거가 아예 없기 때문이다.
    """
    actual = {
        "calibration_version": entry["calibration_version"],
        "calibration_sha256": sha256_text(entry["calibration"]),
        "image_zone_sha256": sha256_text(entry["image_zone"]),
        "floor_zone_sha256": sha256_text(entry["floor_zone"]),
    }
    if record is None:
        if official:
            raise ZoneEvalError(
                f"{video_id}: 공식 실행인데 input checksum 기록이 없습니다. "
                "calibration·Zone 파일의 SHA-256을 동결 manifest에 추가하세요."
            )
        actual["verified"] = False
        return actual

    for field in INPUT_CHECKSUM_FIELDS[1:]:
        if actual[field] != record[field]:
            raise ZoneEvalError(
                f"{video_id}: {field}가 동결값과 다릅니다: "
                f"{actual[field]} != {record[field]}"
            )
    actual["verified"] = True
    return actual


def evaluate(args: argparse.Namespace) -> dict:
    root = Path(args.repo_root).resolve()
    is_official = resolve_officiality(args)

    cache_path = Path(args.cache)
    cache = json.loads(cache_path.read_text(encoding="utf-8"))
    if cache.get("schema_version") != CACHE_SCHEMA_VERSION:
        raise ZoneEvalError(f"지원하지 않는 캐시 schema입니다: {cache.get('schema_version')}")
    tracker = verify_tracker_provenance(cache, is_official)

    # 동결된 계약 검증을 그대로 쓴다. 여기서 직접 CSV를 읽어 필드 존재만 보면
    # enter<exit, frame 범위, interval index 연속성, manifest 대조 같은 계약이
    # 평가 경로에만 적용되지 않는 상태가 된다.
    manifest_path = Path(args.manifest)
    intervals_path = Path(args.intervals)
    manifest_rows = contract.load_recordings_manifest(manifest_path)
    interval_rows = contract.load_zone_intervals(
        intervals_path, manifest_rows, require_reviewed=True
    )
    manifest = {row["video_id"]: row for row in manifest_rows}
    intervals = list(interval_rows)

    plan_path = Path(args.review_plan)
    plan = read_csv(plan_path, ("contract_filename", "original_filename", "notes"))
    inputs = build_video_inputs(plan, root)

    identity_path = Path(
        args.track_identity
        or root / "data" / "annotations" / "phase4" / "zone_eval" / "track_identity.csv"
    )
    identities = load_track_identity(identity_path)
    unknown = sorted(set(identities) - set(manifest))
    if unknown:
        raise ZoneEvalError(f"track identity에 manifest에 없는 video_id가 있습니다: {unknown}")

    checksum_path = Path(
        args.input_checksums
        or root / "data" / "annotations" / "phase4" / "zone_eval" / "input_checksums.csv"
    )
    input_checksums = load_input_checksums(checksum_path)
    unknown = sorted(set(input_checksums) - set(manifest))
    if unknown:
        raise ZoneEvalError(f"input checksum에 manifest에 없는 video_id가 있습니다: {unknown}")

    # 커밋된 입력은 줄바꿈을 맞춰 해시한다. 원시 바이트로 적으면 Windows에서
    # 실행한 결과의 지문이 CRLF 기준이 되어, 저장소의 파일을 받아 대조해도
    # 값이 맞지 않는다. 감사하라고 남기는 값이므로 어느 OS에서 실행하든 같은
    # 값이 나와야 한다. 캐시는 커밋되지 않고 이 스크립트가 LF로 쓰므로 그대로
    # 스트리밍해 해시한다.
    artifacts = {
        "cache": sha256_file(cache_path),
        "manifest": sha256_text(manifest_path),
        "intervals": sha256_text(intervals_path),
        "review_plan": sha256_text(plan_path),
        "track_identity": sha256_text(identity_path),
        "input_checksums": sha256_text(checksum_path),
    }
    # 캐시가 적어둔 manifest 지문은 `cache_zone_foot_points.py`가 원시 바이트로
    # 계산한 값이다. 둘 다 같은 기계에서 만들어지므로 원시 바이트끼리 비교한다.
    manifest_raw_digest = sha256_file(manifest_path)
    cached_manifest_digest = cache.get("manifest_sha256")
    # 공식 실행에서는 필수다. 없으면 비교를 건너뛰게 되므로 캐시에서 이 필드만
    # 지우면 manifest 대조를 통째로 우회할 수 있다.
    if is_official and not cached_manifest_digest:
        raise ZoneEvalError(
            "공식 캐시에 manifest_sha256이 없습니다. 캐시를 다시 만드세요."
        )
    if cached_manifest_digest and cached_manifest_digest != manifest_raw_digest:
        raise ZoneEvalError(
            "캐시를 만들 때 쓴 manifest와 지금 manifest가 다릅니다: "
            f"{cached_manifest_digest} != {manifest_raw_digest}"
        )

    per_video: List[dict] = []
    totals = {p: {"frames": 0, "wrong": 0, "correct": 0, "event_errors": 0, "flips": 0}
              for p in PATHS}

    for row in intervals:
        video_id = row["video_id"]
        if video_id not in inputs:
            raise ZoneEvalError(f"{video_id}: 대응표에 없습니다.")
        if video_id not in cache["videos"]:
            raise ZoneEvalError(f"{video_id}: 캐시에 없습니다.")

        meta = manifest[video_id]
        cache_entry = cache["videos"][video_id]
        verify_cache_against_manifest(video_id, cache_entry, meta)

        fps = float(meta["fps"])
        width, height = int(meta["width"]), int(meta["height"])
        frame_count = int(meta["frame_count"])
        enter, exit_ = int(row["enter_frame"]), int(row["exit_frame"])
        zone_id = row["zone_id"]
        entry = inputs[video_id]
        input_revisions = verify_input_checksums(
            video_id, entry, input_checksums.get(video_id), is_official
        )

        calibration = load_calibration(str(entry["calibration"]))
        if (calibration.frame_width, calibration.frame_height) != (width, height):
            raise ZoneEvalError(f"{video_id}: calibration 해상도가 manifest와 다릅니다.")
        image_zones = load_zones(str(entry["image_zone"]))
        floor_config = load_floor_zones(str(entry["floor_zone"]))
        image_checker = ZoneChecker(image_zones, width, height)
        floor_checker = FloorZoneChecker(floor_config)
        transformer = FloorPlaneTransformer(calibration)
        zone_by_path = {
            "image": select_zone(image_zones, zone_id, f"{video_id} image Zone"),
            "homography": select_zone(
                floor_config.zones, zone_id, f"{video_id} floor Zone"
            ),
        }

        frames = cache_entry["frames"]
        track_id, selection = pick_track(frames, args.track_selection, enter, exit_)
        if track_id is None:
            raise ZoneEvalError(f"{video_id}: 평가할 Track을 고르지 못했습니다.")
        verified = verify_track_identity(
            video_id,
            track_id,
            identities.get(video_id),
            is_official,
            entry["target_actor"],
            parse_actor_ids(meta.get("actor_ids", "")),
            str(meta.get("primary_actor_id", "") or ""),
        )

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
            "zone_id": zone_id,
            "ground_truth": {"enter_frame": enter, "exit_frame": exit_},
            "track": selection,
            "track_identity": verified,
            "video_sha256": cache_entry["video_sha256"],
            "input_revisions": input_revisions,
        }
        for path in PATHS:
            events = run_events(
                judged, zone_by_path[path], fps, path, video_id, frame_count
            )
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
        "is_official": is_official,
        "tracker": tracker,
        "input_artifacts_sha256": artifacts,
        "settings": {
            "track_selection": args.track_selection,
            "event_tolerance_sec": args.event_tolerance_sec,
            "flip_window_sec": args.flip_window_sec,
            "official_event_tolerance_sec": OFFICIAL_EVENT_TOLERANCE_SEC,
            "official_flip_window_sec": OFFICIAL_FLIP_WINDOW_SEC,
            "flip_definition": "진입 계열(ENTER·ENTER_RESTRICTED)과 EXIT 사이의 전환만 센다",
            "event_scope": (
                "영상 전체 frame을 순회하며 runtime과 같이 flush_stale_tracks를 부른다. "
                "frame 정확도는 선택한 Track이 있는 frame만 채점한다."
            ),
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
