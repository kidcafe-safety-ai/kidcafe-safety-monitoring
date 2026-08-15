"""Phase 4 직접 촬영 diagnostic의 A01 단독 영상으로 E1 frame을 만든다.

낙상 영상은 onset 직전 nofall과 onset부터 lying 직후까지의 fall frame을,
일상 동작 영상은 전체 구간의 nofall frame을 시간 간격으로 선별한다. 다중
인원 영상은 victim Track을 자동 추정하지 않고 제외한다. A02는 subject-disjoint
diagnostic 비교, A03 test는 최종 동결 평가에 남겨 학습 누수를 막는다.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import fall_signal_cache as signal_cache  # noqa: E402
import phase4_recording_contract as contract  # noqa: E402


SCHEMA_VERSION = "phase4_recorded_e1_frame_supplement_v1"
FRAME_FIELDS = (
    "sample_id",
    "video_id",
    "actor_id",
    "scenario_type",
    "frame_number",
    "class_id",
    "class_name",
    "track_id",
    "image_path",
    "label_path",
    "image_sha256",
    "label_sha256",
)


class RecordedE1FrameError(ValueError):
    """직접 촬영 E1 frame 생성 계약 위반."""


@dataclass(frozen=True)
class SelectedFrame:
    video_id: str
    actor_id: str
    scenario_type: str
    frame_number: int
    class_id: int
    track_id: int
    bbox: tuple[float, float, float, float]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recordings-manifest", required=True)
    parser.add_argument("--annotations", required=True)
    parser.add_argument("--cache-dir", required=True)
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--training-actors", default="A01")
    parser.add_argument("--sample-fps", type=float, default=3.0)
    parser.add_argument("--pre-fall-nofall-sec", type=float, default=1.0)
    parser.add_argument("--post-lying-fall-sec", type=float, default=0.5)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def _parse_actors(value: str) -> tuple[str, ...]:
    actors = tuple(part.strip() for part in value.split(",") if part.strip())
    if not actors or len(set(actors)) != len(actors):
        raise RecordedE1FrameError("training-actors가 비었거나 중복됩니다.")
    if actors != ("A01",):
        raise RecordedE1FrameError("현재 E1 정책은 A01만 학습 actor로 허용합니다.")
    return actors


def _best_track(tracks) -> object | None:
    if not tracks:
        return None

    def score(track) -> tuple[float, float]:
        x1, y1, x2, y2 = track.bbox
        area = max(0.0, x2 - x1) * max(0.0, y2 - y1)
        return area * max(0.0, track.confidence), track.confidence

    return max(tracks, key=score)


def _sample_range(start: int, end: int, stride: int) -> list[int]:
    if end < start:
        return []
    values = list(range(start, end + 1, stride))
    if values and values[-1] != end:
        values.append(end)
    return values


def select_video_frames(
    manifest: dict,
    annotation: dict,
    cached_frames: Sequence[signal_cache.CachedFrame],
    sample_fps: float,
    pre_fall_nofall_sec: float,
    post_lying_fall_sec: float,
) -> tuple[list[SelectedFrame], int]:
    video_id = manifest["video_id"]
    fps = float(manifest["fps"])
    if not math.isfinite(sample_fps) or sample_fps <= 0 or sample_fps > fps:
        raise RecordedE1FrameError(f"sample_fps는 0보다 크고 원본 FPS 이하여야 합니다: {video_id}")
    for name, value in (
        ("pre_fall_nofall_sec", pre_fall_nofall_sec),
        ("post_lying_fall_sec", post_lying_fall_sec),
    ):
        if not math.isfinite(value) or value < 0:
            raise RecordedE1FrameError(f"{name}은 0 이상의 유한한 값이어야 합니다.")

    stride = max(1, round(fps / sample_fps))
    frame_count = int(manifest["frame_count"])
    requests: dict[int, int] = {}
    if manifest["label"] == "fall":
        fall_start = int(annotation["fall_start_frame"])
        lying_start = int(annotation["lying_start_frame"])
        nofall_start = max(0, fall_start - round(pre_fall_nofall_sec * fps))
        for frame_number in _sample_range(nofall_start, fall_start - 1, stride):
            requests[frame_number] = 0
        fall_end = min(
            frame_count - 1,
            lying_start + round(post_lying_fall_sec * fps),
        )
        for frame_number in _sample_range(fall_start, fall_end, stride):
            requests[frame_number] = 1
    else:
        for frame_number in _sample_range(0, frame_count - 1, stride):
            requests[frame_number] = 0

    selected = []
    skipped_without_track = 0
    actor_id = manifest["primary_actor_id"]
    for frame_number, class_id in sorted(requests.items()):
        track = _best_track(cached_frames[frame_number].tracks)
        if track is None:
            skipped_without_track += 1
            continue
        selected.append(
            SelectedFrame(
                video_id=video_id,
                actor_id=actor_id,
                scenario_type=manifest["scenario_type"],
                frame_number=frame_number,
                class_id=class_id,
                track_id=track.track_id,
                bbox=tuple(float(value) for value in track.bbox),
            )
        )
    has_fall_frame = any(item.class_id == 1 for item in selected)
    if not selected or (manifest["label"] == "fall" and not has_fall_frame):
        raise RecordedE1FrameError(f"{video_id}: 학습 frame을 만들 수 없습니다.")
    return selected, skipped_without_track


def _yolo_label(class_id: int, bbox: Sequence[float], width: int, height: int) -> str:
    x1, y1, x2, y2 = (float(value) for value in bbox)
    x1 = min(max(x1, 0.0), float(width))
    x2 = min(max(x2, 0.0), float(width))
    y1 = min(max(y1, 0.0), float(height))
    y2 = min(max(y2, 0.0), float(height))
    if x2 <= x1 or y2 <= y1:
        raise RecordedE1FrameError(f"bbox가 이미지 범위에서 유효하지 않습니다: {bbox}")
    center_x = ((x1 + x2) / 2.0) / width
    center_y = ((y1 + y2) / 2.0) / height
    box_width = (x2 - x1) / width
    box_height = (y2 - y1) / height
    return (
        f"{class_id} {center_x:.8f} {center_y:.8f} "
        f"{box_width:.8f} {box_height:.8f}\n"
    )


def _decode_selected_frames(
    video_path: Path, selected: Sequence[SelectedFrame]
) -> dict[int, object]:
    requested = {item.frame_number for item in selected}
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise RecordedE1FrameError(f"영상을 열 수 없습니다: {video_path}")
    decoded = {}
    try:
        frame_number = 0
        last_requested = max(requested)
        while frame_number <= last_requested:
            ok, frame = capture.read()
            if not ok:
                break
            if frame_number in requested:
                decoded[frame_number] = frame
            frame_number += 1
    finally:
        capture.release()
    missing = sorted(requested - set(decoded))
    if missing:
        raise RecordedE1FrameError(f"선택 frame 디코딩에 실패했습니다: {video_path}: {missing}")
    return decoded


def _replace_output(staging: Path, output: Path, force: bool) -> None:
    if output.exists() and not force:
        raise RecordedE1FrameError(f"출력 경로가 이미 있습니다: {output} (--force 필요)")
    backup = output.with_name(f".{output.name}.backup-{os.getpid()}")
    if output.exists():
        output.rename(backup)
    try:
        staging.rename(output)
    except Exception:
        if backup.exists() and not output.exists():
            backup.rename(output)
        raise
    shutil.rmtree(backup, ignore_errors=True)


def select_training_manifests(
    manifest_rows: Sequence[dict], training_actors: tuple[str, ...]
) -> tuple[list[dict], list[str]]:
    selected = []
    excluded_multi_actor = []
    for row in manifest_rows:
        actors = contract.split_actor_ids(row["actor_ids"])
        if (
            row["split_role"] != "diagnostic"
            or row["primary_actor_id"] not in training_actors
        ):
            continue
        if actors != (row["primary_actor_id"],):
            excluded_multi_actor.append(row["video_id"])
            continue
        selected.append(row)
    if not selected:
        raise RecordedE1FrameError("조건을 만족하는 단독 diagnostic 학습 영상이 없습니다.")
    return selected, excluded_multi_actor


def materialize(
    recordings_manifest_path: Path,
    annotations_path: Path,
    cache_dir: Path,
    repo_root: Path,
    output_dir: Path,
    training_actors: tuple[str, ...],
    sample_fps: float,
    pre_fall_nofall_sec: float,
    post_lying_fall_sec: float,
    force: bool,
) -> dict:
    manifest_rows = contract.load_recordings_manifest(
        recordings_manifest_path,
        repo_root=repo_root,
        verify_files=True,
        verify_checksums=True,
    )
    annotation_rows = contract.load_fall_cause_annotations(
        annotations_path, manifest_rows, require_reviewed=True
    )
    annotations = {row["video_id"]: row for row in annotation_rows}
    cache_manifest_path = signal_cache.manifest_path_for(cache_dir)
    if not cache_manifest_path.is_file():
        raise RecordedE1FrameError(f"cache manifest가 없습니다: {cache_manifest_path}")
    cache_manifest = json.loads(cache_manifest_path.read_text(encoding="utf-8"))
    dataset = cache_manifest.get("dataset") or {}
    if dataset.get("split") != "diagnostic":
        raise RecordedE1FrameError("E1 frame은 diagnostic Cache에서만 만들 수 있습니다.")
    if dataset.get("annotations_sha256") != contract.sha256_file(annotations_path):
        raise RecordedE1FrameError("Cache annotation SHA-256이 실제 파일과 다릅니다.")
    if dataset.get("recordings_manifest_sha256") != contract.sha256_file(
        recordings_manifest_path
    ):
        raise RecordedE1FrameError("Cache recordings manifest SHA-256이 실제 파일과 다릅니다.")

    selected_manifests, excluded_multi_actor = select_training_manifests(
        manifest_rows, training_actors
    )

    output_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.build-", dir=output_dir.parent))
    try:
        images_dir = staging / "images/train"
        labels_dir = staging / "labels/train"
        images_dir.mkdir(parents=True)
        labels_dir.mkdir(parents=True)
        frame_rows = []
        skipped_without_track = 0
        selected_video_ids = []
        for manifest in selected_manifests:
            video_id = manifest["video_id"]
            metadata, cached_frames = signal_cache.read_video_cache(
                signal_cache.cache_path_for(cache_dir, video_id),
                expected_video_id=video_id,
            )
            if int(metadata["frame_count"]) != int(manifest["frame_count"]):
                raise RecordedE1FrameError(f"{video_id}: Cache frame_count가 manifest와 다릅니다.")
            selected, skipped = select_video_frames(
                manifest,
                annotations[video_id],
                cached_frames,
                sample_fps,
                pre_fall_nofall_sec,
                post_lying_fall_sec,
            )
            skipped_without_track += skipped
            video_path = (repo_root / manifest["video_path"]).resolve()
            decoded = _decode_selected_frames(video_path, selected)
            width = int(manifest["width"])
            height = int(manifest["height"])
            for item in selected:
                sample_id = f"p4_{item.actor_id}_{item.video_id}_f{item.frame_number:05d}"
                image_path = images_dir / f"{sample_id}.png"
                label_path = labels_dir / f"{sample_id}.txt"
                if not cv2.imwrite(str(image_path), decoded[item.frame_number]):
                    raise RecordedE1FrameError(f"PNG 저장에 실패했습니다: {image_path}")
                label_path.write_text(
                    _yolo_label(item.class_id, item.bbox, width, height),
                    encoding="ascii",
                )
                frame_rows.append(
                    {
                        "sample_id": sample_id,
                        "video_id": item.video_id,
                        "actor_id": item.actor_id,
                        "scenario_type": item.scenario_type,
                        "frame_number": item.frame_number,
                        "class_id": item.class_id,
                        "class_name": "fall" if item.class_id == 1 else "nofall",
                        "track_id": item.track_id,
                        "image_path": f"images/train/{sample_id}.png",
                        "label_path": f"labels/train/{sample_id}.txt",
                        "image_sha256": contract.sha256_file(image_path),
                        "label_sha256": contract.sha256_file(label_path),
                    }
                )
            selected_video_ids.append(video_id)

        frames_path = staging / "frames.csv"
        with open(frames_path, "w", encoding="utf-8", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=FRAME_FIELDS, lineterminator="\n")
            writer.writeheader()
            writer.writerows(frame_rows)
        class_counts = {
            "nofall": sum(row["class_id"] == 0 for row in frame_rows),
            "fall": sum(row["class_id"] == 1 for row in frame_rows),
        }
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "purpose": "train-only Phase 4 recorded E1 supplement",
            "source_split_role": "diagnostic",
            "training_actor_ids": list(training_actors),
            "class_mapping": {"0": "nofall", "1": "fall"},
            "class_counts": class_counts,
            "frame_count": len(frame_rows),
            "video_count": len(selected_video_ids),
            "selected_video_ids": selected_video_ids,
            "excluded_multi_actor_video_ids": excluded_multi_actor,
            "skipped_without_track": skipped_without_track,
            "selection_policy": {
                "sample_fps": sample_fps,
                "pre_fall_nofall_sec": pre_fall_nofall_sec,
                "post_lying_fall_sec": post_lying_fall_sec,
                "single_actor_only": True,
                "victim_bbox": "largest area multiplied by Track confidence",
            },
            "sources": {
                "source_dataset": "phase4_recorded_2026_08_07",
                "recordings_manifest_sha256": contract.sha256_file(
                    recordings_manifest_path
                ),
                "annotations_sha256": contract.sha256_file(annotations_path),
                "cache_manifest_sha256": contract.sha256_file(cache_manifest_path),
            },
            "frames_csv_sha256": contract.sha256_file(frames_path),
        }
        (staging / "supplement_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        _replace_output(staging, output_dir, force)
        return manifest
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def main() -> None:
    args = parse_args()
    try:
        manifest = materialize(
            Path(args.recordings_manifest),
            Path(args.annotations),
            Path(args.cache_dir),
            Path(args.repo_root).resolve(),
            Path(args.output_dir),
            _parse_actors(args.training_actors),
            args.sample_fps,
            args.pre_fall_nofall_sec,
            args.post_lying_fall_sec,
            args.force,
        )
    except (RecordedE1FrameError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    print(
        "Phase 4 recorded E1 supplement: "
        f"{manifest['frame_count']} frames "
        f"({manifest['class_counts']}) -> {args.output_dir}"
    )


if __name__ == "__main__":
    main()
