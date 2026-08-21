"""E1 selected profile cache에서 Track segment 검수 초안을 생성한다.

다중 인원 영상(기본: contact_fall·near_pass·occluded_cross, A01/A02)의 캐시된
Track ID를 frame 단위로 모아 연속 구간(segment)으로 묶는다. YOLO·Pose를 다시
돌리지 않고 캐시된 bbox·Track만 읽는다.

무결성 검증(fail-closed):
- cache manifest의 tracker·auxiliary model 설정이 selected profile의 동결
  inference 설정과 같아야 한다.
- 현재 `--manifest`·`--annotations` 파일의 SHA-256이 selected profile의
  `recorded_dataset.recordings_manifest_sha256`·`fall_cause_annotations_sha256`와
  같아야 한다.
- cache manifest가 현재 파일보다 이전 revision을 가리키면, cache 생성 당시
  source manifest·annotation의 SHA-256을 확인하고 대상 영상 행이 현재 revision과
  완전히 같은 경우에만 사용한다.
- 대상 영상마다 cache의 frame_count가 현재 manifest와 같아야 하고,
  annotations에서 review_status=reviewed여야 한다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Mapping, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

import phase4_recording_contract as contract  # noqa: E402


DEFAULT_CACHE_DIR = "outputs/phase4_recorded_eval/cache/e1_diagnostic_pose_conf05_recorded_mps"
DEFAULT_MANIFEST = "data/annotations/phase4/recordings_manifest.csv"
DEFAULT_ANNOTATIONS = "data/annotations/phase4/fall_cause_annotations.csv"
DEFAULT_SELECTED_PROFILE = "configs/fall_e1_selected.json"
DEFAULT_CACHE_SOURCE_MANIFEST = (
    "data/annotations/phase4/history/a03_pre_label_correction/recordings_manifest.csv"
)
DEFAULT_CACHE_SOURCE_ANNOTATIONS = (
    "data/annotations/phase4/history/a03_pre_label_correction/fall_cause_annotations.csv"
)
DEFAULT_SCENARIOS = ("contact_fall", "near_pass", "occluded_cross")
_TARGET_ACTORS = {"A01", "A02"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--cache-dir", default=DEFAULT_CACHE_DIR)
    parser.add_argument("--manifest", default=DEFAULT_MANIFEST)
    parser.add_argument("--annotations", default=DEFAULT_ANNOTATIONS)
    parser.add_argument("--selected-profile", default=DEFAULT_SELECTED_PROFILE)
    parser.add_argument("--cache-source-manifest", default=DEFAULT_CACHE_SOURCE_MANIFEST)
    parser.add_argument("--cache-source-annotations", default=DEFAULT_CACHE_SOURCE_ANNOTATIONS)
    parser.add_argument(
        "--scenario",
        action="append",
        default=None,
        help=f"기본값: {','.join(DEFAULT_SCENARIOS)}",
    )
    parser.add_argument(
        "--video-id",
        action="append",
        default=None,
        help="명시하면 --scenario 필터 대신 이 목록만 사용한다.",
    )
    parser.add_argument("--run-id", default=None, help="기본값: --cache-dir 디렉터리 이름")
    parser.add_argument(
        "--merge-gap-frames",
        type=int,
        default=5,
        help=(
            "같은 track_id가 이 frame 수 이하로 끊겼다 다시 잡히면 한 구간으로 합친다"
            "(일시적 confidence 저하 흡수용, 기본 5)."
        ),
    )
    parser.add_argument("--output", required=True)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_cache_source_rows(
    *,
    cache_manifest: Mapping,
    current_manifest_rows: Sequence[Mapping[str, str]],
    current_annotation_rows: Sequence[Mapping[str, str]],
    cache_source_manifest_path: Path | None,
    cache_source_annotations_path: Path | None,
    video_ids: Sequence[str],
) -> list[str]:
    """Cache 생성 revision과 현재 revision의 대상 행이 같은지 검증한다."""
    errors: list[str] = []
    dataset = cache_manifest.get("dataset", {})
    expected_manifest_sha = dataset.get("recordings_manifest_sha256")
    expected_annotations_sha = dataset.get("annotations_sha256")
    if not expected_manifest_sha or not expected_annotations_sha:
        return ["cache manifest에 dataset SHA-256이 없습니다."]
    if cache_source_manifest_path is None or cache_source_annotations_path is None:
        return [
            "cache 생성 revision이 현재와 다른데 source manifest·annotation이 없습니다."
        ]
    if not cache_source_manifest_path.is_file():
        errors.append(f"cache source manifest가 없습니다: {cache_source_manifest_path}")
    if not cache_source_annotations_path.is_file():
        errors.append(
            f"cache source annotations가 없습니다: {cache_source_annotations_path}"
        )
    if errors:
        return errors

    actual_manifest_sha = _sha256_file(cache_source_manifest_path)
    if actual_manifest_sha != expected_manifest_sha:
        errors.append(
            "cache source manifest SHA-256이 cache manifest와 다릅니다: "
            f"actual={actual_manifest_sha}, cache={expected_manifest_sha}"
        )
    actual_annotations_sha = _sha256_file(cache_source_annotations_path)
    if actual_annotations_sha != expected_annotations_sha:
        errors.append(
            "cache source annotations SHA-256이 cache manifest와 다릅니다: "
            f"actual={actual_annotations_sha}, cache={expected_annotations_sha}"
        )
    if errors:
        return errors

    source_manifest_rows = contract.load_recordings_manifest(cache_source_manifest_path)
    source_manifest_by_video = {row["video_id"]: row for row in source_manifest_rows}
    source_annotation_rows = contract.load_fall_cause_annotations(
        cache_source_annotations_path, source_manifest_rows
    )
    source_annotation_by_video = {row["video_id"]: row for row in source_annotation_rows}
    current_manifest_by_video = {row["video_id"]: row for row in current_manifest_rows}
    current_annotation_by_video = {row["video_id"]: row for row in current_annotation_rows}

    for video_id in video_ids:
        if source_manifest_by_video.get(video_id) != current_manifest_by_video.get(video_id):
            errors.append(
                f"{video_id}: cache 생성 당시 manifest 행이 현재 revision과 다릅니다."
            )
        if source_annotation_by_video.get(video_id) != current_annotation_by_video.get(
            video_id
        ):
            errors.append(
                f"{video_id}: cache 생성 당시 annotation 행이 현재 revision과 다릅니다."
            )
    return errors


def select_target_video_ids(
    manifest_rows: Sequence[Mapping[str, str]],
    *,
    scenarios: Sequence[str],
    explicit_video_ids: Sequence[str] | None,
) -> list[str]:
    if explicit_video_ids:
        return list(explicit_video_ids)
    scenario_set = set(scenarios)
    return [
        row["video_id"]
        for row in manifest_rows
        if row["scenario_type"] in scenario_set and row["primary_actor_id"] in _TARGET_ACTORS
    ]


def verify_cache_integrity(
    *,
    cache_dir: Path,
    manifest_path: Path,
    annotations_path: Path,
    selected_profile_path: Path,
    manifest_by_video: Mapping[str, Mapping[str, str]],
    annotation_by_video: Mapping[str, Mapping[str, str]],
    video_ids: Sequence[str],
    cache_source_manifest_path: Path | None = None,
    cache_source_annotations_path: Path | None = None,
) -> None:
    selected = json.loads(selected_profile_path.read_text(encoding="utf-8"))
    cache_manifest = json.loads((cache_dir / "manifest.json").read_text(encoding="utf-8"))

    errors: list[str] = []

    expected_model_sha = selected["model"]["sha256"]
    actual_model_sha = cache_manifest.get("auxiliary_model", {}).get("model_sha256")
    if actual_model_sha != expected_model_sha:
        errors.append(
            "cache의 auxiliary model SHA-256이 selected profile과 다릅니다: "
            f"cache={actual_model_sha}, selected={expected_model_sha}"
        )

    inference = selected["inference"]
    cache_tracker = cache_manifest.get("tracker", {})
    tracker_checks = (
        ("tracker_type", cache_tracker.get("tracker_type"), inference["tracker"]),
        (
            "tracker model SHA-256",
            cache_tracker.get("model_sha256"),
            inference["tracker_model_sha256"],
        ),
        ("tracker confidence", cache_tracker.get("conf"), inference["tracker_confidence"]),
        (
            "fall model confidence",
            cache_manifest.get("auxiliary_model", {}).get("conf"),
            inference["fall_model_confidence"],
        ),
    )
    for name, actual, expected in tracker_checks:
        if actual != expected:
            errors.append(
                f"cache의 {name}가 selected profile과 다릅니다: "
                f"cache={actual}, selected={expected}"
            )

    recorded_dataset = selected["recorded_dataset"]
    manifest_sha = _sha256_file(manifest_path)
    if manifest_sha != recorded_dataset["recordings_manifest_sha256"]:
        errors.append(
            f"{manifest_path}의 SHA-256이 selected profile과 다릅니다: "
            f"actual={manifest_sha}, selected={recorded_dataset['recordings_manifest_sha256']}"
        )
    annotations_sha = _sha256_file(annotations_path)
    if annotations_sha != recorded_dataset["fall_cause_annotations_sha256"]:
        errors.append(
            f"{annotations_path}의 SHA-256이 selected profile과 다릅니다: "
            f"actual={annotations_sha}, "
            f"selected={recorded_dataset['fall_cause_annotations_sha256']}"
        )

    cache_dataset = cache_manifest.get("dataset", {})
    if (
        cache_dataset.get("recordings_manifest_sha256") != manifest_sha
        or cache_dataset.get("annotations_sha256") != annotations_sha
    ):
        errors.extend(
            _verify_cache_source_rows(
                cache_manifest=cache_manifest,
                current_manifest_rows=list(manifest_by_video.values()),
                current_annotation_rows=list(annotation_by_video.values()),
                cache_source_manifest_path=cache_source_manifest_path,
                cache_source_annotations_path=cache_source_annotations_path,
                video_ids=video_ids,
            )
        )
    if errors:
        raise ValueError("cache 무결성 검증 실패:\n  - " + "\n  - ".join(errors))

    for video_id in video_ids:
        manifest_row = manifest_by_video.get(video_id)
        if manifest_row is None:
            errors.append(f"{video_id}: {manifest_path}에 없습니다.")
            continue
        annotation_row = annotation_by_video.get(video_id)
        if annotation_row is None:
            errors.append(f"{video_id}: {annotations_path}에 없습니다.")
        elif annotation_row["review_status"] != "reviewed":
            errors.append(f"{video_id}: annotation review_status가 reviewed가 아닙니다.")
        cache_path = cache_dir / f"{video_id}.json"
        if not cache_path.is_file():
            errors.append(f"{video_id}: cache 파일이 없습니다: {cache_path}")
            continue
        cache_video = json.loads(cache_path.read_text(encoding="utf-8"))
        if cache_video.get("video_id") != video_id:
            errors.append(
                f"{video_id}: cache 내부 video_id={cache_video.get('video_id')!r}가 다릅니다."
            )
        if int(cache_video["frame_count"]) != int(manifest_row["frame_count"]):
            errors.append(
                f"{video_id}: cache frame_count={cache_video['frame_count']}, "
                f"manifest frame_count={manifest_row['frame_count']}"
            )

    if errors:
        raise ValueError("cache 무결성 검증 실패:\n  - " + "\n  - ".join(errors))


def extract_track_segments(
    cache_video: Mapping, *, merge_gap_frames: int = 0
) -> list[tuple[int, int, int]]:
    """(track_id, start_frame, end_frame) 목록.

    같은 track_id 안에서 `merge_gap_frames` 이하의 detection gap은 한 구간으로
    합친다. 그보다 큰 gap은 별도 구간으로 남겨 재검토 대상이 되게 한다.
    """
    if merge_gap_frames < 0:
        raise ValueError("merge_gap_frames는 0 이상이어야 합니다.")
    frames_by_track: dict[int, list[int]] = {}
    for frame in cache_video["frames"]:
        frame_number = frame["frame_number"]
        for track in frame["tracks"]:
            frames_by_track.setdefault(track["track_id"], []).append(frame_number)

    segments: list[tuple[int, int, int]] = []
    for track_id, frame_numbers in frames_by_track.items():
        ordered = sorted(frame_numbers)
        start = ordered[0]
        previous = ordered[0]
        for current in ordered[1:]:
            if current - previous > merge_gap_frames + 1:
                segments.append((track_id, start, previous))
                start = current
            previous = current
        segments.append((track_id, start, previous))
    return sorted(segments, key=lambda item: (item[1], item[0]))


def build_segment_rows(
    *,
    cache_dir: Path,
    video_ids: Sequence[str],
    run_id: str,
    merge_gap_frames: int = 0,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for video_id in video_ids:
        cache_video = json.loads((cache_dir / f"{video_id}.json").read_text(encoding="utf-8"))
        segments = extract_track_segments(cache_video, merge_gap_frames=merge_gap_frames)
        for track_id, start_frame, end_frame in segments:
            rows.append(
                {
                    "run_id": run_id,
                    "video_id": video_id,
                    "start_frame": str(start_frame),
                    "end_frame": str(end_frame),
                    "track_id": str(track_id),
                    "actor_id": "",
                    "review_status": "pending",
                    "notes": contract.SCENARIO_SEEDED_DRAFT_NOTE,
                }
            )
    return rows


def print_summary(rows: Sequence[Mapping[str, str]], output: Path) -> None:
    videos = Counter(row["video_id"] for row in rows)
    print(f"Phase 4 Track segment 초안: {len(rows)} rows / {len(videos)} videos -> {output}")
    for video_id, count in sorted(videos.items()):
        print(f"  {video_id}: {count} segments")
    print("  review_status=pending (전체, 검수 UI로 actor 배정 필요)")


def main() -> None:
    args = parse_args()
    output = Path(args.output)
    try:
        cache_dir = Path(args.cache_dir)
        manifest_path = Path(args.manifest)
        annotations_path = Path(args.annotations)
        selected_profile_path = Path(args.selected_profile)
        cache_source_manifest_path = Path(args.cache_source_manifest)
        cache_source_annotations_path = Path(args.cache_source_annotations)

        manifest_rows = contract.load_recordings_manifest(manifest_path)
        manifest_by_video = {row["video_id"]: row for row in manifest_rows}
        annotation_rows = contract.load_fall_cause_annotations(annotations_path, manifest_rows)
        annotation_by_video = {row["video_id"]: row for row in annotation_rows}

        video_ids = select_target_video_ids(
            manifest_rows,
            scenarios=args.scenario or DEFAULT_SCENARIOS,
            explicit_video_ids=args.video_id,
        )
        if not video_ids:
            raise ValueError("대상 video_id가 없습니다.")

        verify_cache_integrity(
            cache_dir=cache_dir,
            manifest_path=manifest_path,
            annotations_path=annotations_path,
            selected_profile_path=selected_profile_path,
            cache_source_manifest_path=cache_source_manifest_path,
            cache_source_annotations_path=cache_source_annotations_path,
            manifest_by_video=manifest_by_video,
            annotation_by_video=annotation_by_video,
            video_ids=video_ids,
        )

        run_id = args.run_id or cache_dir.name
        rows = build_segment_rows(
            cache_dir=cache_dir,
            video_ids=video_ids,
            run_id=run_id,
            merge_gap_frames=args.merge_gap_frames,
        )
        contract.validate_track_actor_segments(rows, manifest_rows)
        contract.write_csv_atomic(
            output, contract.TRACK_ACTOR_SEGMENT_FIELDS, rows, force=args.force
        )
        written_rows = contract.load_track_actor_segments(output, manifest_rows)
    except (FileExistsError, OSError, ValueError, KeyError) as exc:
        raise SystemExit(str(exc)) from exc
    print_summary(written_rows, output)


if __name__ == "__main__":
    main()
