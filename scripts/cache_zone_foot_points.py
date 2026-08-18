"""Zone 평가용 foot point를 영상마다 캐시한다.

채택 기준 2~5번은 같은 Track·같은 foot point를 두 좌표 경로에 넣고 판정 차이만
본다. 그런데 tracking은 모델과 영상이 있어야 돌고 시간도 오래 걸린다. 판정
비교를 할 때마다 다시 돌리면 두 경로가 서로 다른 Track을 보게 될 위험도 있다.

그래서 tracking을 한 번만 돌려 frame별 foot point를 캐시하고, 판정 비교는
`evaluate_zone_paths.py`가 그 캐시만 읽어 수행한다. 두 경로가 문자 그대로
같은 입력을 받는다는 것이 이 분리로 보장된다.

캐시에는 tracker 모델의 SHA-256과 영상 SHA-256을 함께 적는다. 다른 모델이나
다른 영상으로 만든 캐시를 나중에 섞어 쓰면 비교가 무효가 되기 때문이다.

사용 예:

    python scripts/cache_zone_foot_points.py \\
        --manifest data/annotations/phase4/recordings_manifest.csv \\
        --repo-root . \\
        --output outputs/phase4_zone_eval/foot_points.json
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Dict, List

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.tracking.bytetrack_wrapper import ByteTracker  # noqa: E402

CACHE_SCHEMA_VERSION = "phase4_zone_foot_points_v1"
MANIFEST_FIELDS = ("video_id", "video_path", "fps", "frame_count", "width", "height")


class CacheError(RuntimeError):
    """캐시를 만들 수 없는 입력 상태."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--model", default="yolo26n.pt", help="tracker 가중치 경로")
    parser.add_argument("--confidence", type=float, default=0.5)
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--video-id",
        action="append",
        default=None,
        help="지정하면 해당 video_id만 처리한다. 반복 지정할 수 있다.",
    )
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_manifest(path: Path, wanted: List[str] | None) -> List[dict]:
    if not path.is_file():
        raise CacheError(f"manifest가 없습니다: {path}")
    with open(path, "r", encoding="utf-8", newline="") as file:
        rows = list(csv.DictReader(file))
    missing = [f for f in MANIFEST_FIELDS if rows and f not in rows[0]]
    if missing:
        raise CacheError(f"manifest에 필드가 없습니다: {missing}")
    if wanted:
        rows = [r for r in rows if r["video_id"] in set(wanted)]
        unknown = set(wanted) - {r["video_id"] for r in rows}
        if unknown:
            raise CacheError(f"manifest에 없는 video_id: {sorted(unknown)}")
    if not rows:
        raise CacheError("처리할 영상이 없습니다.")
    return rows


def cache_video(video_path: Path, model: str, confidence: float, expected) -> dict:
    """영상 하나의 frame별 Track foot point를 모은다.

    `expected`는 manifest가 기록한 (fps, frame_count, width, height)다. 실제
    영상과 다르면 ground truth의 frame 번호가 다른 영상을 가리키게 되므로
    fail-fast한다.
    """
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise CacheError(f"영상을 열 수 없습니다: {video_path}")
    try:
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = float(capture.get(cv2.CAP_PROP_FPS))
        if (width, height) != (expected["width"], expected["height"]):
            raise CacheError(
                f"{video_path.name} 해상도가 manifest와 다릅니다: "
                f"{width}x{height} != {expected['width']}x{expected['height']}"
            )
        if abs(fps - expected["fps"]) > 0.01:
            raise CacheError(
                f"{video_path.name} fps가 manifest와 다릅니다: {fps} != {expected['fps']}"
            )

        tracker = ByteTracker(model_path=model, confidence=confidence)
        frames: Dict[str, List[dict]] = {}
        frame_number = 0
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            result = tracker.update(frame, frame_number, str(video_path))
            if result.tracks:
                frames[str(frame_number)] = [
                    {
                        "track_id": t.track_id,
                        "bbox": [round(v, 3) for v in t.bbox],
                        "foot_point": [round(v, 3) for v in t.foot_point],
                        "confidence": round(float(t.confidence), 4),
                    }
                    for t in result.tracks
                ]
            frame_number += 1
    finally:
        capture.release()

    if frame_number != expected["frame_count"]:
        raise CacheError(
            f"{video_path.name} frame 수가 manifest와 다릅니다: "
            f"{frame_number} != {expected['frame_count']}"
        )
    return {"frame_count": frame_number, "frames": frames}


def write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as file:
            json.dump(payload, file, ensure_ascii=False, indent=2, sort_keys=True)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(temp_name, path)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise


def main() -> None:
    args = parse_args()
    root = Path(args.repo_root).resolve()
    try:
        rows = load_manifest(Path(args.manifest), args.video_id)
        model_path = Path(args.model)
        if not model_path.is_file():
            raise CacheError(f"tracker 가중치가 없습니다: {model_path}")
        videos = {}
        for row in rows:
            video_path = (root / row["video_path"]).resolve()
            if not video_path.is_file():
                raise CacheError(f"영상이 없습니다: {row['video_path']}")
            expected = {
                "fps": float(row["fps"]),
                "frame_count": int(row["frame_count"]),
                "width": int(row["width"]),
                "height": int(row["height"]),
            }
            print(f"tracking {row['video_id']} ...", flush=True)
            entry = cache_video(video_path, args.model, args.confidence, expected)
            entry["video_sha256"] = sha256_file(video_path)
            entry["fps"] = expected["fps"]
            videos[row["video_id"]] = entry
    except CacheError as exc:
        raise SystemExit(str(exc)) from exc

    payload = {
        "schema_version": CACHE_SCHEMA_VERSION,
        "tracker": {
            "model": args.model,
            "model_sha256": sha256_file(model_path),
            "confidence": args.confidence,
        },
        "videos": videos,
    }
    write_json_atomic(Path(args.output), payload)
    total = sum(len(v["frames"]) for v in videos.values())
    print(f"영상 {len(videos)}개, Track이 있는 frame {total}개 -> {args.output}")


if __name__ == "__main__":
    main()
