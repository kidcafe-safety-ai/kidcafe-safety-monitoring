"""Phase 4 Tracker arm의 추론·공식 평가·검수 초안을 순서대로 생성한다.

사람 검수가 필요한 Track→Actor와 Event attribution을 자동 확정하지 않는다.
이 도구는 전체 diagnostic cache, 공식 낙상 평가, 다중 인원/Cause-null replay,
Track segment pending 초안까지만 만든다.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import phase4_recording_contract as recording_contract  # noqa: E402
import phase4_tracker_comparison_contract as comparison_contract  # noqa: E402


SCRIPTS_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG = "configs/phase4_tracker_comparison.json"
DEFAULT_OUTPUT_ROOT = "outputs/phase4_tracker_comparison"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--comparison-config", default=DEFAULT_CONFIG)
    parser.add_argument("--arm-id", required=True, choices=comparison_contract.ARM_IDS)
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--output-root", default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--device", default="auto")
    parser.add_argument("--fall-model-device", default="auto")
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help="파일·SHA·cohort·명령만 검증하고 추론은 시작하지 않는다.",
    )
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def _run(command: list[str], *, cwd: Path) -> None:
    print("\n$ " + " ".join(command), flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def _append_flag(command: list[str], enabled: bool, flag: str) -> None:
    if enabled:
        command.append(flag)


def git_state(repo_root: Path) -> tuple[str, bool]:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return commit, bool(status.strip())


def build_commands(
    *,
    config: dict,
    arm: dict,
    repo_root: Path,
    output_root: Path,
    device: str,
    fall_model_device: str,
    force: bool,
) -> tuple[dict[str, Path], list[list[str]]]:
    dataset = config["dataset"]
    fixed = config["fixed_inference"]
    selected_profile = config["selected_profile"]["path"]
    arm_root = output_root / "arms" / arm["arm_id"]
    cache_dir = arm_root / "cache"
    artifacts = {
        "arm_root": arm_root,
        "cache_dir": cache_dir,
        "official_eval": arm_root / "official_eval.json",
        "multiperson_events": arm_root / "multiperson_events.json",
        "cause_null_events": arm_root / "cause_null_events.json",
        "track_actor_segments": arm_root / "track_actor_segments.csv",
        "timing_report": cache_dir / "timing_report.json",
        "run_manifest": arm_root / "arm_run_manifest.json",
    }

    common_cache = [
        sys.executable,
        str(SCRIPTS_DIR / "cache_fall_signals.py"),
        "--annotations",
        dataset["annotations_path"],
        "--recordings-manifest",
        dataset["manifest_path"],
        "--videos-dir",
        ".",
        "--split",
        dataset["split"],
        "--tracker",
        fixed["tracker_type"],
        "--model",
        fixed["tracker_model_path"],
        "--conf",
        str(fixed["tracker_confidence"]),
        "--device",
        device,
        "--tracker-config",
        arm["tracker_config_path"],
        "--tracker-config-sha256",
        arm["tracker_config_sha256"],
        "--fall-model-path",
        fixed["fall_model_path"],
        "--fall-model-conf",
        str(fixed["fall_model_confidence"]),
        "--fall-model-device",
        fall_model_device,
        "--cache-dir",
        str(cache_dir),
        "--evaluation-protocol-version",
        fixed["evaluation_protocol_version"],
    ]
    if arm["with_reid"]:
        common_cache.extend(["--reid-model-sha256", arm["reid_model_sha256"]])
    _append_flag(common_cache, force, "--force")

    official = [
        sys.executable,
        str(SCRIPTS_DIR / "evaluate_fall_from_cache.py"),
        "--annotations",
        dataset["annotations_path"],
        "--recordings-manifest",
        dataset["manifest_path"],
        "--cache-dir",
        str(cache_dir),
        "--split",
        dataset["split"],
        "--config",
        fixed["fall_detector_config_path"],
        "--fall-model-iou-threshold",
        str(fixed["fall_model_iou_threshold"]),
        "--fall-model-interval-frames",
        str(fixed["fall_model_interval_frames"]),
        "--evaluation-protocol-version",
        fixed["evaluation_protocol_version"],
        "--selected-profile",
        selected_profile,
        "--output",
        str(artifacts["official_eval"]),
    ]
    _append_flag(
        official,
        fixed["fall_pose_normal_gate_enabled"],
        "--fall-pose-normal-gate-enabled",
    )

    replay_common = [
        "--manifest",
        dataset["manifest_path"],
        "--annotations",
        dataset["annotations_path"],
        "--cache-dir",
        str(cache_dir),
        "--selected-profile",
        selected_profile,
        "--config",
        fixed["fall_detector_config_path"],
        "--fall-model-iou-threshold",
        str(fixed["fall_model_iou_threshold"]),
        "--fall-model-interval-frames",
        str(fixed["fall_model_interval_frames"]),
        "--fall-pose-normal-gate-enabled",
        str(fixed["fall_pose_normal_gate_enabled"]).lower(),
        "--tracker-comparison-config",
        str(Path(config["_config_path"])),
        "--tracker-arm-id",
        arm["arm_id"],
    ]
    multiperson = [
        sys.executable,
        str(SCRIPTS_DIR / "replay_phase4_multiperson_events.py"),
        *replay_common,
        "--output",
        str(artifacts["multiperson_events"]),
    ]
    cause_null = [
        sys.executable,
        str(SCRIPTS_DIR / "replay_phase4_multiperson_events.py"),
        *replay_common,
        "--scenario",
        "fall_backward",
        "--scenario",
        "fall_forward",
        "--scenario",
        "fall_forward_knees",
        "--scenario",
        "fall_side",
        "--output",
        str(artifacts["cause_null_events"]),
    ]
    segments = [
        sys.executable,
        str(SCRIPTS_DIR / "generate_phase4_track_actor_segments.py"),
        "--cache-dir",
        str(cache_dir),
        "--manifest",
        dataset["manifest_path"],
        "--annotations",
        dataset["annotations_path"],
        "--selected-profile",
        selected_profile,
        "--run-id",
        arm["arm_id"],
        "--output",
        str(artifacts["track_actor_segments"]),
    ]
    _append_flag(segments, force, "--force")
    return artifacts, [common_cache, official, multiperson, cause_null, segments]


def main() -> None:
    args = parse_args()
    repo_root = Path(args.repo_root).resolve()
    config_path = (repo_root / args.comparison_config).resolve()
    output_root = Path(args.output_root)
    if not output_root.is_absolute():
        output_root = repo_root / output_root
    try:
        config = comparison_contract.load_config(
            config_path,
            repo_root=repo_root,
            require_model_artifacts=True,
        )
        config["_config_path"] = str(config_path.relative_to(repo_root))
        manifest_rows = recording_contract.load_recordings_manifest(
            repo_root / config["dataset"]["manifest_path"]
        )
        annotation_rows = recording_contract.load_fall_cause_annotations(
            repo_root / config["dataset"]["annotations_path"], manifest_rows
        )
        comparison_contract.validate_cohort(config, manifest_rows, annotation_rows)
        arm = dict(comparison_contract.arm_by_id(config, args.arm_id))
    except (OSError, ValueError, KeyError) as exc:
        raise SystemExit(str(exc)) from exc

    artifacts, commands = build_commands(
        config=config,
        arm=arm,
        repo_root=repo_root,
        output_root=output_root,
        device=args.device,
        fall_model_device=args.fall_model_device,
        force=args.force,
    )
    if args.preflight_only:
        print(f"preflight 통과: {args.arm_id}")
        print(json.dumps(comparison_contract.arm_provenance(arm), indent=2))
        for command in commands:
            print("$ " + " ".join(command))
        return
    try:
        evaluator_git_commit, evaluator_git_dirty = git_state(repo_root)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SystemExit("evaluator Git revision을 확인할 수 없습니다.") from exc
    if evaluator_git_dirty:
        raise SystemExit(
            "최종 Tracker 비교는 깨끗한 Git commit에서만 실행합니다. "
            "코드 검증·커밋 후 다시 실행하세요."
        )
    if artifacts["run_manifest"].exists() and not args.force:
        raise SystemExit(
            f"완료된 arm 결과가 이미 있습니다: {artifacts['run_manifest']} "
            "(--force로 전체 재생성)"
        )

    artifacts["arm_root"].mkdir(parents=True, exist_ok=True)
    for index, command in enumerate(commands, start=1):
        print(f"\n[{index}/{len(commands)}] {args.arm_id}", flush=True)
        _run(command, cwd=repo_root)

    timing = json.loads(artifacts["timing_report"].read_text(encoding="utf-8"))
    run_manifest = {
        "schema_version": "phase4_tracker_arm_run_v1",
        "comparison_config_sha256": comparison_contract.sha256_file(config_path),
        "selected_execution_profile_sha256": config["selected_profile"][
            "execution_profile_sha256"
        ],
        "evaluator_git_commit": evaluator_git_commit,
        "evaluator_git_dirty": evaluator_git_dirty,
        "arm": comparison_contract.arm_provenance(arm),
        "device": args.device,
        "fall_model_device": args.fall_model_device,
        "artifacts": {
            key: str(path.relative_to(repo_root))
            for key, path in artifacts.items()
            if key not in {"arm_root", "run_manifest"}
        },
        "artifact_sha256": {
            key: comparison_contract.sha256_file(path)
            for key, path in artifacts.items()
            if key
            in {
                "official_eval",
                "multiperson_events",
                "cause_null_events",
                "track_actor_segments",
                "timing_report",
            }
        },
        "timing": {
            "videos_timed": timing["videos_timed"],
            "skipped_count": timing["skipped_count"],
            "fps_avg": timing["fps_avg"],
        },
    }
    artifacts["run_manifest"].write_text(
        json.dumps(run_manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"\narm 추론 준비 완료: {artifacts['arm_root']}")
    print("다음 단계: track_actor_segments.csv를 영상 검수로 reviewed 처리합니다.")


if __name__ == "__main__":
    main()
