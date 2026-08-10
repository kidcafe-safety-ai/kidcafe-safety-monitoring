"""Phase 4 직접 촬영 manifest와 annotation을 공식 평가 전에 검증한다."""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import phase4_recording_contract as contract  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--annotations")
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
            verify_files=args.verify_files or args.verify_checksums,
            verify_checksums=args.verify_checksums,
        )
        annotation_rows = None
        if args.annotations:
            annotation_rows = contract.load_fall_cause_annotations(
                args.annotations,
                manifest_rows,
                require_reviewed=args.require_reviewed,
            )
    except (OSError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc

    labels = Counter(row["label"] for row in manifest_rows)
    splits = Counter(row["split_role"] for row in manifest_rows)
    print(f"manifest 검증 통과: {len(manifest_rows)} videos")
    print(f"  labels={dict(sorted(labels.items()))}")
    print(f"  splits={dict(sorted(splits.items()))}")
    if annotation_rows is not None:
        statuses = Counter(row["review_status"] for row in annotation_rows)
        print(f"annotation 검증 통과: {len(annotation_rows)} rows")
        print(f"  review_status={dict(sorted(statuses.items()))}")


if __name__ == "__main__":
    main()
