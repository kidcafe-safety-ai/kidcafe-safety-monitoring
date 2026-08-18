"""ID switch 후보의 전·후 frame을 나란히 이미지로 뽑아 눈으로 확인하게 한다.

`derive_phase4_track_id_switches.py`가 만든 switch는 같은 actor의 두
segment가 시간순으로 인접하고 track_id가 다르다는 것만 안다 — 실제로 같은
사람이 재등장한 건지, 다른 사람이거나 오검출인지는 사람이 봐야 한다.

switch 하나당 두 frame을 겹쳐 그려 한 PNG로 저장한다: from_track이 마지막으로
잡힌 frame(왼쪽)과 to_track이 처음 잡힌 frame(오른쪽, = switch_frame).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Mapping, Optional, Sequence

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import phase4_recording_contract as contract  # noqa: E402
from pick_calibration_points import PickerError, read_frame  # noqa: E402

_LABEL_COLOR = (0, 255, 0)
_BOX_COLOR = (0, 0, 255)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--segments", required=True)
    parser.add_argument("--switches", required=True)
    parser.add_argument("--cache-dir", required=True)
    parser.add_argument("--repo-root", default=".")
    parser.add_argument(
        "--status",
        default="needs_review",
        help="이 review_status인 switch만 뽑는다. 빈 문자열이면 전부.",
    )
    parser.add_argument("--output-dir", required=True)
    return parser.parse_args()


def find_previous_segment_end_frame(
    segment_rows: Sequence[Mapping[str, str]],
    *,
    video_id: str,
    actor_id: str,
    track_id: str,
    before_frame: int,
) -> Optional[int]:
    """같은 (video_id, actor_id, track_id)에서 before_frame 이전에 끝난 segment 중 가장 늦은 end_frame."""
    candidates = [
        int(row["end_frame"])
        for row in segment_rows
        if row["video_id"] == video_id
        and row["actor_id"] == actor_id
        and row["track_id"] == track_id
        and int(row["end_frame"]) < before_frame
    ]
    return max(candidates) if candidates else None


def _bbox_at(cache_video: Mapping, frame_number: int, track_id: int) -> Optional[list]:
    for frame in cache_video["frames"]:
        if frame["frame_number"] != frame_number:
            continue
        for track in frame["tracks"]:
            if track["track_id"] == track_id:
                return track["bbox"]
    return None


def _annotate(frame: np.ndarray, bbox: Optional[list], label: str) -> np.ndarray:
    annotated = frame.copy()
    if bbox is not None:
        x1, y1, x2, y2 = (round(v) for v in bbox)
        cv2.rectangle(annotated, (x1, y1), (x2, y2), _BOX_COLOR, 3)
    cv2.putText(
        annotated, label, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, _LABEL_COLOR, 2, cv2.LINE_AA
    )
    return annotated


def build_snapshot(
    *,
    cache_video: Mapping,
    video_path: Path,
    from_track_id: int,
    to_track_id: int,
    before_frame: int,
    after_frame: int,
    label_prefix: str,
) -> np.ndarray:
    left = read_frame(video_path, before_frame)
    right = read_frame(video_path, after_frame)
    height = max(left.shape[0], right.shape[0])
    width = max(left.shape[1], right.shape[1])
    left = cv2.resize(left, (width, height))
    right = cv2.resize(right, (width, height))
    left_bbox = _bbox_at(cache_video, before_frame, from_track_id)
    right_bbox = _bbox_at(cache_video, after_frame, to_track_id)
    left = _annotate(
        left, left_bbox, f"{label_prefix} BEFORE track={from_track_id} frame={before_frame}"
    )
    right = _annotate(
        right, right_bbox, f"{label_prefix} AFTER track={to_track_id} frame={after_frame}"
    )
    return np.hstack([left, right])


def main() -> None:
    args = parse_args()
    try:
        repo_root = Path(args.repo_root).resolve()
        manifest_rows = contract.load_recordings_manifest(args.manifest)
        manifest_by_video = {row["video_id"]: row for row in manifest_rows}
        segment_rows = contract.load_track_actor_segments(args.segments, manifest_rows)
        switch_rows = contract.load_track_id_switches(args.switches, manifest_rows)

        target_switches = [
            row
            for row in switch_rows
            if not args.status or row["review_status"] == args.status
        ]
        if not target_switches:
            raise ValueError(f"status={args.status!r}인 switch가 없습니다.")

        output_dir = Path(args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        cache_dir = Path(args.cache_dir)

        cache_video_by_video_id: dict[str, Mapping] = {}
        written = []
        for row in target_switches:
            video_id = row["video_id"]
            manifest_row = manifest_by_video[video_id]
            video_path = (repo_root / manifest_row["video_path"]).resolve(strict=True)
            switch_frame = int(row["switch_frame"])
            before_frame = find_previous_segment_end_frame(
                segment_rows,
                video_id=video_id,
                actor_id=row["actor_id"],
                track_id=row["from_track_id"],
                before_frame=switch_frame,
            )
            if before_frame is None:
                raise ValueError(
                    f"{row['switch_id']}: from_track_id={row['from_track_id']}의 "
                    "이전 segment를 찾을 수 없습니다."
                )
            if video_id not in cache_video_by_video_id:
                cache_path = cache_dir / f"{video_id}.json"
                if not cache_path.is_file():
                    raise ValueError(f"cache 파일이 없습니다: {cache_path}")
                cache_video_by_video_id[video_id] = json.loads(
                    cache_path.read_text(encoding="utf-8")
                )
            label_prefix = f"{video_id} actor={row['actor_id']}"
            image = build_snapshot(
                cache_video=cache_video_by_video_id[video_id],
                video_path=video_path,
                from_track_id=int(row["from_track_id"]),
                to_track_id=int(row["to_track_id"]),
                before_frame=before_frame,
                after_frame=switch_frame,
                label_prefix=label_prefix,
            )
            output_path = output_dir / f"{row['switch_id']}.png"
            if not cv2.imwrite(str(output_path), image):
                raise ValueError(f"이미지를 저장하지 못했습니다: {output_path}")
            written.append((row["switch_id"], output_path))
    except (PickerError, OSError, ValueError, KeyError) as exc:
        raise SystemExit(str(exc)) from exc

    print(f"{len(written)}개 switch snapshot 저장 -> {output_dir}")
    for switch_id, path in written:
        print(f"  {switch_id} -> {path}")


if __name__ == "__main__":
    main()
