"""검수된 track_actor_segments.csv에서 track_id_switches.csv를 기계적으로 계산한다.

같은 actor에게 배정된 두 segment가 시간순으로 인접하고 track_id가 다르면 그
경계를 ID switch 후보로 계산한다. 짧은 연속 구간은 자동 확정하고, 긴 공백 뒤
재등장은 scene exit/re-entry일 수 있으므로 needs_review로 남긴다.
검수자가 짧은 연속 switch를 따로 표시할 필요는 없다 —
`review_phase4_track_actor_segments.py`에서 "이 track이 누구인지"만 판단하면
이 스크립트가 나머지를 계산한다.

입력 segment가 하나라도 reviewed가 아니면 결과를 만들지 않는다.
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path
from typing import Mapping, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

import phase4_recording_contract as contract  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--segments", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--max-continuity-gap-frames",
        type=int,
        default=5,
        help=(
            "두 actor segment 사이 공백이 이 값 이하면 ID switch로 자동 확정한다. "
            "더 길면 needs_review 후보로 기록한다 (기본 5)."
        ),
    )
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def derive_switch_rows(
    segment_rows: Sequence[Mapping[str, str]], *, max_continuity_gap_frames: int = 5
) -> list[dict[str, str]]:
    if max_continuity_gap_frames < 0:
        raise ValueError("max_continuity_gap_frames는 0 이상이어야 합니다.")
    incomplete = [row for row in segment_rows if row["review_status"] != "reviewed"]
    if incomplete:
        raise ValueError(
            "ID switch 산출 전 모든 Track segment가 reviewed여야 합니다: "
            f"미완료 {len(incomplete)}개"
        )
    invalid_unmapped = [
        row
        for row in segment_rows
        if not (row.get("actor_id") or "").strip()
        and contract.NON_ACTOR_TRACK_NOTE
        not in {
            part.strip()
            for part in (row.get("notes") or "").split(";")
            if part.strip()
        }
    ]
    if invalid_unmapped:
        raise ValueError(
            "reviewed Track segment는 actor_id 또는 명시적인 non-actor 판정이 "
            f"필요합니다: 미배정 {len(invalid_unmapped)}개"
        )
    reviewed = [row for row in segment_rows if (row.get("actor_id") or "").strip()]
    grouped: dict[tuple[str, str, str], list[Mapping[str, str]]] = defaultdict(list)
    for row in reviewed:
        key = (row["run_id"], row["video_id"], row["actor_id"])
        grouped[key].append(row)

    switches: list[dict[str, str]] = []
    for (run_id, video_id, actor_id), rows in grouped.items():
        ordered = sorted(rows, key=lambda row: int(row["start_frame"]))
        for previous, current in zip(ordered, ordered[1:]):
            from_track_id = previous["track_id"]
            to_track_id = current["track_id"]
            if from_track_id == to_track_id:
                continue
            switch_frame = current["start_frame"]
            gap_frames = int(current["start_frame"]) - int(previous["end_frame"]) - 1
            if gap_frames < 0:
                raise ValueError(
                    f"{video_id}/{actor_id}: reviewed actor segment가 겹칩니다."
                )
            is_continuous = gap_frames <= max_continuity_gap_frames
            switch_id = f"sw_{video_id}_{from_track_id}_{to_track_id}_{switch_frame}"
            switches.append(
                {
                    "run_id": run_id,
                    "switch_id": switch_id,
                    "video_id": video_id,
                    "actor_id": actor_id,
                    "from_track_id": from_track_id,
                    "to_track_id": to_track_id,
                    "switch_frame": switch_frame,
                    "review_status": "reviewed" if is_continuous else "needs_review",
                    "notes": (
                        "derived continuous actor transition; "
                        f"gap_frames={gap_frames}"
                        if is_continuous
                        else "possible exit/re-entry; manual review required; "
                        f"gap_frames={gap_frames}; "
                        f"max_continuity_gap_frames={max_continuity_gap_frames}"
                    ),
                }
            )
    return sorted(switches, key=lambda row: (row["video_id"], int(row["switch_frame"])))


def print_summary(rows: Sequence[Mapping[str, str]], output: Path) -> None:
    by_video: dict[str, int] = defaultdict(int)
    for row in rows:
        by_video[row["video_id"]] += 1
    print(f"Phase 4 Track ID switch: {len(rows)} rows -> {output}")
    for video_id, count in sorted(by_video.items()):
        print(f"  {video_id}: {count} switches")
    if not rows:
        print("  switch 없음 (모든 actor가 영상 내내 같은 track_id를 유지)")


def main() -> None:
    args = parse_args()
    output = Path(args.output)
    try:
        manifest_rows = contract.load_recordings_manifest(args.manifest)
        segment_rows = contract.load_track_actor_segments(args.segments, manifest_rows)
        rows = derive_switch_rows(
            segment_rows,
            max_continuity_gap_frames=args.max_continuity_gap_frames,
        )
        contract.validate_track_id_switches(rows, manifest_rows)
        contract.write_csv_atomic(
            output, contract.TRACK_ID_SWITCH_FIELDS, rows, force=args.force
        )
        written_rows = contract.load_track_id_switches(output, manifest_rows)
    except (FileExistsError, OSError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    print_summary(written_rows, output)


if __name__ == "__main__":
    main()
