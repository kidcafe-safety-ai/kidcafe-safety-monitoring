"""Phase 4 촬영 manifest에서 낙상·Cause annotation 검수 초안을 생성한다."""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path
from typing import Mapping, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

import phase4_recording_contract as contract  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def _seed_cause_fields(manifest: Mapping[str, str]) -> dict[str, str]:
    """사람이 확정한 scenario 이름으로 pending Cause 초안만 채운다."""
    scenario = manifest["scenario_type"]
    victim = manifest["primary_actor_id"] if manifest["label"] == "fall" else ""
    if scenario != "contact_fall":
        return {
            "victim_actor_id": victim,
            "contact_occurred": "false",
            "cause_candidate_exists": "false",
            "cause_actor_id": "",
        }

    actors = contract.split_actor_ids(manifest["actor_ids"])
    cause_actors = [actor for actor in actors if actor != victim]
    cause_actor = cause_actors[0] if len(cause_actors) == 1 else ""
    return {
        "victim_actor_id": victim,
        "contact_occurred": "true",
        "cause_candidate_exists": "true",
        "cause_actor_id": cause_actor,
    }


def build_annotation_rows(
    manifest_rows: Sequence[Mapping[str, str]],
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for manifest in manifest_rows:
        cause_fields = _seed_cause_fields(manifest)
        rows.append(
            {
                "video_id": manifest["video_id"],
                "label": manifest["label"],
                "fall_start_frame": "",
                "impact_frame": "",
                "lying_start_frame": "",
                "recovery_frame": "",
                **cause_fields,
                "contact_frame": "",
                "review_status": "pending",
                "reviewer_id": "",
                "second_reviewer_id": "",
                "notes": contract.SCENARIO_SEEDED_DRAFT_NOTE,
            }
        )
    return rows


def print_summary(rows: Sequence[Mapping[str, str]], output: Path) -> None:
    labels = Counter(row["label"] for row in rows)
    contact = sum(row["contact_occurred"] == "true" for row in rows)
    print(f"Phase 4 낙상·Cause annotation 초안: {len(rows)} rows -> {output}")
    print(f"  labels={dict(sorted(labels.items()))}")
    print(f"  contact_fall_seeded={contact}, review_status=pending")


def main() -> None:
    args = parse_args()
    output = Path(args.output)
    try:
        manifest_rows = contract.load_recordings_manifest(args.manifest)
        rows = build_annotation_rows(manifest_rows)
        contract.validate_fall_cause_annotations(rows, manifest_rows)
        contract.write_csv_atomic(
            output,
            contract.FALL_CAUSE_FIELDS,
            rows,
            force=args.force,
        )
        written_rows = contract.load_fall_cause_annotations(output, manifest_rows)
    except (FileExistsError, OSError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    print_summary(written_rows, output)


if __name__ == "__main__":
    main()
