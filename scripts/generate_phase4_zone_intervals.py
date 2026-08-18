"""Phase 4 촬영 manifest에서 Zone 진입·이탈 interval 검수 초안을 생성한다."""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path
from typing import Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

import phase4_recording_contract as contract  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--zone-id", default="play_floor")
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def build_interval_rows(
    manifest_rows: Sequence[dict[str, str]],
    *,
    zone_id: str,
) -> list[dict[str, str]]:
    if not zone_id.strip():
        raise ValueError("zone_id가 비어 있습니다.")
    rows: list[dict[str, str]] = []
    for manifest in manifest_rows:
        rows.append(
            {
                "video_id": manifest["video_id"],
                "zone_id": zone_id,
                "interval_index": "1",
                "enter_frame": "",
                "exit_frame": "",
                "dwell_start_frame": "",
                "review_status": "pending",
                "notes": contract.SCENARIO_SEEDED_DRAFT_NOTE,
            }
        )
    return rows


def print_summary(rows: Sequence[dict[str, str]], output: Path) -> None:
    zones = Counter(row["zone_id"] for row in rows)
    print(f"Phase 4 Zone interval 초안: {len(rows)} rows -> {output}")
    print(f"  zones={dict(sorted(zones.items()))}")
    print("  review_status=pending (전체, review_phase4_zone_intervals.py로 확정)")


def main() -> None:
    args = parse_args()
    output = Path(args.output)
    try:
        manifest_rows = contract.load_recordings_manifest(args.manifest)
        rows = build_interval_rows(manifest_rows, zone_id=args.zone_id)
        contract.validate_zone_intervals(rows, manifest_rows)
        contract.write_csv_atomic(
            output,
            contract.ZONE_INTERVAL_FIELDS,
            rows,
            force=args.force,
        )
        written_rows = contract.load_zone_intervals(output, manifest_rows)
    except (FileExistsError, OSError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    print_summary(written_rows, output)


if __name__ == "__main__":
    main()
