"""Phase 4 Zone manifest와 interval ground truth를 공식 측정 전에 검증한다."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import phase4_recording_contract as contract  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--intervals", required=True)
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--verify-files", action="store_true")
    parser.add_argument("--verify-checksums", action="store_true")
    parser.add_argument("--require-reviewed", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        manifest_rows = contract.load_recordings_manifest(
            args.manifest,
            repo_root=args.repo_root,
            verify_files=args.verify_files,
            verify_checksums=args.verify_checksums,
        )
        interval_rows = contract.load_zone_intervals(
            args.intervals,
            manifest_rows,
            require_reviewed=args.require_reviewed,
        )
    except (OSError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc

    reviewed = sum(row["review_status"] == "reviewed" for row in interval_rows)
    print(f"Zone manifest 검증 통과: {len(manifest_rows)} videos")
    print(f"Zone interval 검증 통과: {len(interval_rows)} rows, reviewed={reviewed}")


if __name__ == "__main__":
    main()
