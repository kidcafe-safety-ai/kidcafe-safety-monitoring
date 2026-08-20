"""Event별 victim·predicted cause를 ground truth와 대조해 검수 초안을 만든다.

입력 네 가지를 결합한다:

- `replay_phase4_multiperson_events.py`가 만든 Event(track_id·predicted cause)
- 검수 완료된 `track_actor_segments.csv`(Track -> actor)
- 검수 완료된 `track_id_switches.csv`(관련 ID switch)
- R01·R02가 검수한 `fall_cause_annotations.csv`(victim·cause 정답)와
  `evaluate_fall_from_cache.py` 공식 결과(timely·late·duplicate 판정)

기계적으로 판단 가능한 `event_error_type`을 미리 채운다. no_fall 영상은
Event가 없으면 true_negative sentinel 행, Event가 있으면 false_alarm 행으로
남겨 대상 영상 전체의 audit coverage를 보존한다. 모든 행은
`review_status=pending`으로 시작한다 — 기계 판단도 검수자가 확인해야 확정된다.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Mapping, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

import phase4_recording_contract as contract  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--annotations", required=True)
    parser.add_argument("--events", required=True, help="replay_phase4_multiperson_events.py 출력")
    parser.add_argument("--official-eval", required=True, help="evaluate_fall_from_cache.py 출력")
    parser.add_argument("--segments", required=True)
    parser.add_argument("--switches", required=True)
    parser.add_argument("--selected-profile", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def resolve_actor(
    segment_rows: Sequence[Mapping[str, str]],
    *,
    video_id: str,
    track_id: int,
    frame_number: int,
) -> Optional[str]:
    """frame_number의 actor_id를 찾는다.

    그 frame을 정확히 덮는 segment가 있으면(non-actor 포함) 그 판정을 그대로
    쓴다 — 검수자가 명시적으로 판단한 결과이므로 덮어쓰지 않는다.
    덮는 segment가 아예 없으면(Track이 event_frame 전에 끝난 경우 등,
    predicted_cause처럼 attribution이 과거 시점 근접도로 후보를 고르는
    경우 흔하다) frame_number 이전에 끝난 segment 중 가장 늦게 끝난 것으로
    대체한다. 그 track_id의 segment가 전혀 없으면 None.
    """
    track_id_text = str(track_id)
    candidates = [
        row
        for row in segment_rows
        if row["video_id"] == video_id and row["track_id"] == track_id_text
    ]
    if not candidates:
        return None
    for row in candidates:
        if int(row["start_frame"]) <= frame_number <= int(row["end_frame"]):
            return row["actor_id"]
    preceding = [row for row in candidates if int(row["end_frame"]) < frame_number]
    if not preceding:
        return None
    nearest = max(preceding, key=lambda row: int(row["end_frame"]))
    return nearest["actor_id"]


def related_switches(
    switch_rows: Sequence[Mapping[str, str]],
    *,
    video_id: str,
    actor_ids: Sequence[str],
    event_frame: int,
) -> list[str]:
    """event_frame 이전(포함)에 일어난, 관련 actor의 switch만 후보로 남긴다.

    switch_frame이 event_frame보다 뒤면 그 switch는 이 Event의 판정 당시
    이력에 아직 없었으므로 원인이 될 수 없다(낙상 후 회복해 걸어 나가며
    생기는 switch 등과 착각하지 않게 한다).
    """
    actor_set = {a for a in actor_ids if a}
    if not actor_set:
        return []
    return [
        row["switch_id"]
        for row in switch_rows
        if row["video_id"] == video_id
        and row["actor_id"] in actor_set
        and int(row["switch_frame"]) <= event_frame
    ]


def classify_error_type(
    *,
    label: str,
    event_index: int,
    late_detection: bool,
    victim_actor_id: Optional[str],
    expected_victim_actor_id: str,
    contact_occurred: str,
    predicted_cause_actor_id: Optional[str],
    expected_cause_actor_id: str,
) -> str:
    """기계적으로 확실한 경우만 분류하고, 애매하면 빈 문자열(검수자 판단)을 돌려준다."""
    if label != "fall":
        return "false_alarm"
    if event_index > 0:
        return "duplicate_fall"
    if late_detection:
        return "late_fall"
    if victim_actor_id != expected_victim_actor_id:
        # victim_actor_id가 ""(non-actor로 판정된 Track이 낙상을 확정한 경우
        # 포함)이거나 다른 actor면 전부 victim 식별 문제로 본다.
        return "victim_mismatch"
    if contact_occurred == "true":
        if not predicted_cause_actor_id:
            return "missed_cause"
        if predicted_cause_actor_id != expected_cause_actor_id:
            return "false_attribution"
        return "none"
    if predicted_cause_actor_id:
        return "false_attribution"
    return "none"


def build_rows(
    *,
    run_id: str,
    replay_results: Sequence[Mapping],
    official_videos_by_id: Mapping[str, Mapping],
    annotation_by_video: Mapping[str, Mapping[str, str]],
    segment_rows: Sequence[Mapping[str, str]],
    switch_rows: Sequence[Mapping[str, str]],
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for video_result in replay_results:
        video_id = video_result["video_id"]
        annotation = annotation_by_video[video_id]
        official = official_videos_by_id[video_id]
        events = video_result["events"]

        if annotation["label"] == "no_fall" and not events:
            rows.append(
                {
                    "run_id": run_id,
                    "video_id": video_id,
                    "event_frame": "",
                    "victim_track_id": "",
                    "victim_actor_id": "",
                    "predicted_cause_track_id": "",
                    "predicted_cause_actor_id": "",
                    "related_switch_ids": "",
                    "id_switch_relation": "none",
                    "event_error_type": "true_negative",
                    "review_status": "pending",
                    "notes": "scenario-seeded draft; Event 0건 확인 필요",
                }
            )
            continue

        if annotation["label"] == "fall" and not events:
            rows.append(
                {
                    "run_id": run_id,
                    "video_id": video_id,
                    "event_frame": "",
                    "victim_track_id": "",
                    "victim_actor_id": "",
                    "predicted_cause_track_id": "",
                    "predicted_cause_actor_id": "",
                    "related_switch_ids": "",
                    "id_switch_relation": "none",
                    "event_error_type": "missed_fall",
                    "review_status": "pending",
                    "notes": "scenario-seeded draft; frame review required",
                }
            )
            continue

        for index, event in enumerate(events):
            event_frame = event["frame_number"]
            victim_track_id = event["track_id"]
            victim_actor_id = resolve_actor(
                segment_rows, video_id=video_id, track_id=victim_track_id, frame_number=event_frame
            )
            cause = event["cause"]
            predicted_cause_track_id = cause["track_id"] if cause else None
            predicted_cause_actor_id = (
                resolve_actor(
                    segment_rows,
                    video_id=video_id,
                    track_id=predicted_cause_track_id,
                    frame_number=event_frame,
                )
                if predicted_cause_track_id is not None
                else None
            )

            switches = related_switches(
                switch_rows,
                video_id=video_id,
                actor_ids=[victim_actor_id or "", predicted_cause_actor_id or ""],
                event_frame=event_frame,
            )
            error_type = classify_error_type(
                label=annotation["label"],
                event_index=index,
                late_detection=bool(official["late_detection"]),
                victim_actor_id=victim_actor_id,
                expected_victim_actor_id=annotation["victim_actor_id"],
                contact_occurred=annotation["contact_occurred"],
                predicted_cause_actor_id=predicted_cause_actor_id,
                expected_cause_actor_id=annotation["cause_actor_id"],
            )
            notes = "scenario-seeded draft; frame review required"
            if annotation["label"] != "fall":
                notes += "; no_fall 영상의 false alarm 확인 필요"

            rows.append(
                {
                    "run_id": run_id,
                    "video_id": video_id,
                    "event_frame": str(event_frame),
                    "victim_track_id": str(victim_track_id),
                    "victim_actor_id": victim_actor_id or "",
                    "predicted_cause_track_id": (
                        str(predicted_cause_track_id)
                        if predicted_cause_track_id is not None
                        else ""
                    ),
                    "predicted_cause_actor_id": predicted_cause_actor_id or "",
                    "related_switch_ids": "|".join(switches),
                    "id_switch_relation": "none" if not switches else "",
                    "event_error_type": error_type,
                    "review_status": "pending",
                    "notes": notes,
                }
            )
    return rows


def main() -> None:
    args = parse_args()
    output = Path(args.output)
    try:
        manifest_rows = contract.load_recordings_manifest(args.manifest)
        annotation_rows = contract.load_fall_cause_annotations(args.annotations, manifest_rows)
        annotation_by_video = {row["video_id"]: row for row in annotation_rows}
        segment_rows = contract.load_track_actor_segments(args.segments, manifest_rows)
        switch_rows = contract.load_track_id_switches(args.switches, manifest_rows)

        replay = json.loads(Path(args.events).read_text(encoding="utf-8"))
        official = json.loads(Path(args.official_eval).read_text(encoding="utf-8"))
        selected_profile = json.loads(
            Path(args.selected_profile).read_text(encoding="utf-8")
        )
        contract.validate_official_eval_provenance(
            official,
            replay=replay,
            selected_profile=selected_profile,
            selected_execution_profile_sha256=(
                contract.selected_execution_profile_sha256(selected_profile)
            ),
            recordings_manifest_sha256=contract.sha256_file(args.manifest),
            annotations_sha256=contract.sha256_file(args.annotations),
            config_sha256=contract.sha256_file(
                selected_profile["inference"]["fall_detector_config_path"]
            ),
        )
        official_videos_by_id = {v["video_id"]: v for v in official["videos"]}

        missing = [
            v["video_id"] for v in replay["videos"] if v["video_id"] not in official_videos_by_id
        ]
        if missing:
            raise ValueError(f"공식 평가 결과에 없는 video_id: {missing}")

        rows = build_rows(
            run_id=args.run_id,
            replay_results=replay["videos"],
            official_videos_by_id=official_videos_by_id,
            annotation_by_video=annotation_by_video,
            segment_rows=segment_rows,
            switch_rows=switch_rows,
        )
        contract.validate_event_attribution_review(rows, manifest_rows)
        contract.write_csv_atomic(
            output, contract.EVENT_ATTRIBUTION_REVIEW_FIELDS, rows, force=args.force
        )
        written_rows = contract.load_event_attribution_review(output, manifest_rows)
    except (FileExistsError, OSError, ValueError, KeyError) as exc:
        raise SystemExit(str(exc)) from exc

    print(f"{len(written_rows)}개 행 -> {output}")
    error_counts = Counter(row["event_error_type"] or "(미분류)" for row in written_rows)
    print("event_error_type:", dict(error_counts))


if __name__ == "__main__":
    main()
