"""검수된 Phase 4 촬영 영상에서 계약 manifest를 생성한다.

원본 영상은 복사하거나 수정하지 않는다. review plan의 계약 파일명과 실제
영상 metadata·SHA-256을 대조해 `phase4_recordings_manifest_v1` CSV만 만든다.
"""

from __future__ import annotations

import argparse
import csv
import math
import sys
from collections import Counter
from pathlib import Path
from typing import Mapping, Sequence

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent))

import phase4_recording_contract as contract  # noqa: E402


REVIEW_PLAN_FIELDS = (
    "review_index",
    "original_filename",
    "contract_filename",
    "actor_ids",
    "primary_actor_id",
    "scenario_type",
    "label",
    "visual_review_status",
    "notes",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review-plan", required=True, help="사람이 확인한 파일명 대응 CSV")
    parser.add_argument("--recordings-dir", required=True, help="계약 이름의 MP4 디렉터리")
    parser.add_argument("--output", required=True, help="생성할 recordings_manifest.csv")
    parser.add_argument("--repo-root", default=".", help="video_path 기준 저장소 루트")
    parser.add_argument(
        "--test-actor",
        action="append",
        default=[],
        help="test로 봉인할 actor ID. 여러 명이면 옵션을 반복한다.",
    )
    parser.add_argument("--lighting", default="indoor")
    parser.add_argument(
        "--consent-status",
        choices=sorted(contract.VALID_CONSENT_STATUSES),
        default="confirmed",
    )
    parser.add_argument(
        "--full-decode-check",
        action="store_true",
        help="모든 frame을 디코딩해 metadata frame_count와 일치하는지 확인한다.",
    )
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def load_review_plan(path: str | Path) -> list[dict[str, str]]:
    target = Path(path)
    with target.open(encoding="utf-8", newline="") as file:
        reader = csv.DictReader(file)
        actual_fields = tuple(reader.fieldnames or ())
        if actual_fields != REVIEW_PLAN_FIELDS:
            raise ValueError(
                f"{target}: review plan header가 다릅니다. "
                f"expected={list(REVIEW_PLAN_FIELDS)}, actual={list(actual_fields)}"
            )
        rows = [dict(row) for row in reader]
    if not rows:
        raise ValueError(f"{target}: review plan이 비어 있습니다.")
    return rows


def _inspect_video(path: Path, full_decode_check: bool) -> dict[str, object]:
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise ValueError(f"영상을 열 수 없습니다: {path}")
    try:
        fps = float(cap.get(cv2.CAP_PROP_FPS))
        frame_count = int(round(cap.get(cv2.CAP_PROP_FRAME_COUNT)))
        width = int(round(cap.get(cv2.CAP_PROP_FRAME_WIDTH)))
        height = int(round(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))
        if not math.isfinite(fps) or fps <= 0:
            raise ValueError(f"유효한 FPS를 읽지 못했습니다: {path}")
        if min(frame_count, width, height) <= 0:
            raise ValueError(f"유효한 영상 metadata를 읽지 못했습니다: {path}")

        if full_decode_check:
            decoded_frames = 0
            while True:
                ok, _ = cap.read()
                if not ok:
                    break
                decoded_frames += 1
            if decoded_frames != frame_count:
                raise ValueError(
                    f"{path}: metadata frame_count={frame_count}, "
                    f"decoded_frames={decoded_frames}"
                )
        else:
            ok, _ = cap.read()
            if not ok:
                raise ValueError(f"첫 frame을 디코딩할 수 없습니다: {path}")
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_count - 1)
            ok, _ = cap.read()
            if not ok:
                raise ValueError(f"마지막 frame을 디코딩할 수 없습니다: {path}")
    finally:
        cap.release()

    return {
        "fps": fps,
        "frame_count": frame_count,
        "width": width,
        "height": height,
    }


def _format_fps(value: float) -> str:
    return f"{value:.6f}".rstrip("0").rstrip(".")


def _split_role(actor_ids: Sequence[str], test_actors: set[str]) -> str:
    actor_set = set(actor_ids)
    test_members = actor_set & test_actors
    if test_members and test_members != actor_set:
        raise ValueError(
            "test actor와 diagnostic actor가 같은 영상에 있습니다: "
            f"actors={sorted(actor_set)}, test_actors={sorted(test_actors)}"
        )
    return "test" if actor_set and actor_set <= test_actors else "diagnostic"


def build_manifest_rows(
    review_rows: Sequence[Mapping[str, str]],
    *,
    recordings_dir: Path,
    repo_root: Path,
    test_actors: set[str],
    lighting: str,
    consent_status: str,
    full_decode_check: bool,
) -> list[dict[str, object]]:
    root = repo_root.resolve()
    recordings = recordings_dir.resolve()
    recordings.relative_to(root)
    if not recordings.is_dir():
        raise ValueError(f"촬영 디렉터리가 없습니다: {recordings_dir}")

    rows: list[dict[str, object]] = []
    seen_contract_names: set[str] = set()
    seen_targets: set[Path] = set()
    seen_checksums: dict[str, str] = {}
    for raw in review_rows:
        contract_filename = (raw.get("contract_filename") or "").strip()
        if contract_filename in seen_contract_names:
            raise ValueError(f"중복 contract_filename입니다: {contract_filename}")
        seen_contract_names.add(contract_filename)

        parsed = contract.parse_recording_name(contract_filename)
        if (raw.get("visual_review_status") or "").strip() != "human_confirmed":
            raise ValueError(f"{contract_filename}: 사람 검수가 완료되지 않았습니다.")
        actors = contract.split_actor_ids((raw.get("actor_ids") or "").strip())
        primary_actor = (raw.get("primary_actor_id") or "").strip()
        scenario = (raw.get("scenario_type") or "").strip()
        label = (raw.get("label") or "").strip()
        if primary_actor != parsed.primary_actor_id:
            raise ValueError(f"{contract_filename}: primary actor가 파일명과 다릅니다.")
        if scenario != parsed.scenario_type:
            raise ValueError(f"{contract_filename}: scenario가 파일명과 다릅니다.")
        if label not in contract.VALID_LABELS:
            raise ValueError(f"{contract_filename}: label={label!r}이 잘못됐습니다.")

        video_path = recordings_dir / contract_filename
        if not video_path.exists():
            raise ValueError(f"계약 영상이 없습니다: {video_path}")
        resolved_video = video_path.resolve(strict=True)
        resolved_video.relative_to(root)
        if resolved_video in seen_targets:
            raise ValueError(f"같은 원본 영상을 두 번 참조합니다: {resolved_video}")
        seen_targets.add(resolved_video)
        original_filename = (raw.get("original_filename") or "").strip()
        if (
            video_path.is_symlink()
            and original_filename
            and resolved_video.name != original_filename
        ):
            raise ValueError(
                f"{contract_filename}: symlink 원본({resolved_video.name})과 "
                f"review plan({original_filename})이 다릅니다."
            )

        metadata = _inspect_video(video_path, full_decode_check)
        checksum = contract.sha256_file(resolved_video)
        if checksum in seen_checksums:
            raise ValueError(
                f"{contract_filename}: {seen_checksums[checksum]}와 동일한 영상 내용입니다."
            )
        seen_checksums[checksum] = contract_filename
        relative_path = video_path.absolute().relative_to(root).as_posix()
        rows.append(
            {
                "video_id": parsed.video_id,
                "session_id": parsed.session_id,
                "actor_ids": "|".join(actors),
                "primary_actor_id": primary_actor,
                "camera_id": parsed.camera_id,
                "scenario_type": scenario,
                "label": label,
                "video_path": relative_path,
                "fps": _format_fps(float(metadata["fps"])),
                "frame_count": metadata["frame_count"],
                "width": metadata["width"],
                "height": metadata["height"],
                "lighting": lighting,
                "split_role": _split_role(actors, test_actors),
                "review_status": "reviewed",
                "consent_status": consent_status,
                "checksum_sha256": checksum,
            }
        )
    return sorted(rows, key=lambda row: str(row["video_id"]))


def print_summary(rows: Sequence[Mapping[str, object]], output: Path) -> None:
    labels = Counter(str(row["label"]) for row in rows)
    splits = Counter(str(row["split_role"]) for row in rows)
    scenarios = Counter(str(row["scenario_type"]) for row in rows)
    total_frames = sum(int(row["frame_count"]) for row in rows)
    total_duration = sum(int(row["frame_count"]) / float(row["fps"]) for row in rows)
    print(f"Phase 4 촬영 manifest: {len(rows)} videos -> {output}")
    print(f"  labels={dict(sorted(labels.items()))}")
    print(f"  splits={dict(sorted(splits.items()))}")
    print(f"  scenarios={dict(sorted(scenarios.items()))}")
    print(f"  frames={total_frames}, duration_sec={total_duration:.3f}")


def main() -> None:
    args = parse_args()
    repo_root = Path(args.repo_root)
    output = Path(args.output)
    try:
        test_actors = set(args.test_actor)
        for actor in test_actors:
            parsed_actors = contract.split_actor_ids(actor)
            if len(parsed_actors) != 1 or parsed_actors[0] != actor:
                raise ValueError(f"--test-actor는 단일 actor ID여야 합니다: {actor!r}")
        review_rows = load_review_plan(args.review_plan)
        rows = build_manifest_rows(
            review_rows,
            recordings_dir=Path(args.recordings_dir),
            repo_root=repo_root,
            test_actors=test_actors,
            lighting=args.lighting,
            consent_status=args.consent_status,
            full_decode_check=args.full_decode_check,
        )
        contract.validate_recordings_manifest(rows)
        contract.write_csv_atomic(
            output,
            contract.MANIFEST_FIELDS,
            rows,
            force=args.force,
        )
        written_rows = contract.load_recordings_manifest(
            output,
            repo_root=repo_root,
            verify_files=True,
            verify_checksums=True,
        )
    except (FileExistsError, OSError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    print_summary(written_rows, output)


if __name__ == "__main__":
    main()
