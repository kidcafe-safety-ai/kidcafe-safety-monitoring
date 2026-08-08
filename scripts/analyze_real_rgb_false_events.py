"""실제 RGB 외부 validation의 no-fall Event를 원인 경로별로 분류한다.

UP-Fall과 GMDCSA24의 공통 ``real_rgb_fall_cohort_v1`` manifest를 읽는다.
출력은 수동 검수와 후속 실험 routing용이며 학습 데이터로 자동 채택하지 않는다.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import tempfile
from collections import Counter
from pathlib import Path
from typing import Mapping, Sequence

from real_rgb_cohort import COHORT_SCHEMA_VERSION, sha256_file


ANALYSIS_SCHEMA_VERSION = "real_rgb_false_event_analysis_v1"
OUTPUT_CSV = "false_events.csv"
OUTPUT_JSON = "false_event_analysis.json"
VALID_CONFIRM_PATHS = {"bbox", "pose", "model"}
VALID_ENTRY_REASONS = {"dynamic", "model", "handoff"}


class AnalysisError(ValueError):
    """평가·cohort·cache provenance가 서로 맞지 않을 때 발생한다."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evaluation", required=True)
    parser.add_argument("--cohort-manifest", required=True)
    parser.add_argument("--cache-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--window-sec", type=float, default=2.5)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def _load_json(path: Path, description: str) -> dict:
    if not path.is_file():
        raise AnalysisError(f"{description} 파일이 없습니다: {path}")
    try:
        with open(path, "r", encoding="utf-8") as file:
            payload = json.load(file)
    except (OSError, json.JSONDecodeError) as exc:
        raise AnalysisError(f"{description} JSON을 읽을 수 없습니다: {exc}") from exc
    if not isinstance(payload, dict):
        raise AnalysisError(f"{description} JSON root는 객체여야 합니다.")
    return payload


def load_evaluation(path: Path) -> list[dict]:
    payload = _load_json(path, "evaluation")
    if payload.get("evaluation_valid") is not True:
        raise AnalysisError("evaluation_valid=true인 결과만 분석할 수 있습니다.")
    videos = payload.get("videos")
    if not isinstance(videos, list) or not videos:
        raise AnalysisError("evaluation videos가 비어 있습니다.")
    seen = set()
    for video in videos:
        if not isinstance(video, dict):
            raise AnalysisError("evaluation video 항목이 객체가 아닙니다.")
        video_id = video.get("video_id")
        if not isinstance(video_id, str) or not video_id or video_id in seen:
            raise AnalysisError(f"evaluation video_id가 비었거나 중복됩니다: {video_id!r}")
        seen.add(video_id)
        if video.get("label") not in {"fall", "no_fall"}:
            raise AnalysisError(f"evaluation label이 올바르지 않습니다: {video_id}")
        if video.get("error") is not None:
            raise AnalysisError(f"오류 영상이 포함돼 있습니다: {video_id}")
        event_frames = video.get("event_frames")
        diagnostics = video.get("event_diagnostics")
        if not isinstance(event_frames, list) or not isinstance(diagnostics, list):
            raise AnalysisError(f"Event 배열 형식이 잘못됐습니다: {video_id}")
        if video.get("event_count") != len(event_frames):
            raise AnalysisError(f"event_count와 event_frames 수가 다릅니다: {video_id}")
        diagnostic_frames = [item.get("frame_number") for item in diagnostics]
        if sorted(diagnostic_frames) != sorted(event_frames):
            raise AnalysisError(
                f"event_frames와 event_diagnostics가 대응하지 않습니다: {video_id}"
            )
    return videos


def load_cohort(path: Path) -> tuple[dict, dict[str, dict]]:
    manifest = _load_json(path, "cohort manifest")
    if manifest.get("schema_version") != COHORT_SCHEMA_VERSION:
        raise AnalysisError("cohort manifest schema_version이 다릅니다.")
    source_dataset = manifest.get("source_dataset")
    if not isinstance(source_dataset, str) or not source_dataset:
        raise AnalysisError("cohort source_dataset이 비어 있습니다.")
    videos = manifest.get("videos")
    if not isinstance(videos, list) or manifest.get("video_count") != len(videos):
        raise AnalysisError("cohort videos/video_count가 올바르지 않습니다.")
    by_id = {}
    for video in videos:
        if not isinstance(video, dict):
            raise AnalysisError("cohort video record가 객체가 아닙니다.")
        video_id = video.get("video_id")
        if not isinstance(video_id, str) or not video_id or video_id in by_id:
            raise AnalysisError(f"cohort video_id가 비었거나 중복됩니다: {video_id!r}")
        probe = video.get("output_probe")
        if not isinstance(probe, dict):
            raise AnalysisError(f"cohort output_probe가 없습니다: {video_id}")
        fps = probe.get("fps")
        duration = probe.get("duration_sec")
        frame_count = probe.get("frame_count")
        if (
            not isinstance(fps, (int, float))
            or not math.isfinite(fps)
            or fps <= 0
            or not isinstance(duration, (int, float))
            or not math.isfinite(duration)
            or duration <= 0
            or not isinstance(frame_count, int)
            or frame_count <= 0
        ):
            raise AnalysisError(f"cohort probe가 올바르지 않습니다: {video_id}")
        by_id[video_id] = video
    return manifest, by_id


def load_cache_metadata(cache_dir: Path, video_id: str) -> dict:
    payload = _load_json(cache_dir / f"{video_id}.json", f"cache {video_id}")
    if payload.get("video_id") != video_id:
        raise AnalysisError(f"cache video_id가 파일명과 다릅니다: {video_id}")
    fps = payload.get("fps")
    frame_count = payload.get("frame_count")
    if (
        not isinstance(fps, (int, float))
        or not math.isfinite(fps)
        or fps <= 0
        or not isinstance(frame_count, int)
        or frame_count <= 0
    ):
        raise AnalysisError(f"cache metadata가 올바르지 않습니다: {video_id}")
    return {"fps": float(fps), "frame_count": frame_count}


def validate_cache_matches_cohort(
    cache: Mapping[str, object], cohort_probe: Mapping[str, object], video_id: str
) -> None:
    """Container 평균 FPS 차이 대신 frame count와 duration으로 동일 영상을 확인한다."""
    if cache["frame_count"] != cohort_probe["frame_count"]:
        raise AnalysisError(f"cohort/cache frame_count가 다릅니다: {video_id}")
    cache_duration_sec = float(cache["frame_count"]) / float(cache["fps"])
    probe_duration_sec = float(cohort_probe["duration_sec"])
    # GMDCSA24의 ffprobe container duration과 OpenCV timestamp는 동일 frame 수에도
    # 최대 약 0.20초 차이가 난다. 0.25초/4%는 이를 허용하되 다른 영상을 막는다.
    duration_tolerance_sec = max(0.25, probe_duration_sec * 0.04)
    if abs(cache_duration_sec - probe_duration_sec) > duration_tolerance_sec:
        raise AnalysisError(
            f"cohort/cache duration이 다릅니다: {video_id}: "
            f"cache={cache_duration_sec:.6f}, probe={probe_duration_sec:.6f}"
        )


def _active_labels(cohort_video: Mapping[str, object], event_sec: float) -> list[str]:
    temporal = cohort_video.get("temporal_labels")
    if isinstance(temporal, list) and temporal:
        labels = sorted(
            {
                item.get("label")
                for item in temporal
                if isinstance(item, dict)
                and isinstance(item.get("label"), str)
                and isinstance(item.get("start_sec"), (int, float))
                and isinstance(item.get("end_sec"), (int, float))
                and float(item["start_sec"]) <= event_sec <= float(item["end_sec"])
            }
        )
        if labels:
            return labels
    activity = cohort_video.get("activity_name")
    return [str(activity)] if isinstance(activity, str) and activity else ["unlabeled"]


def analyze(
    evaluation_videos: Sequence[dict],
    cohort_manifest: Mapping[str, object],
    cohort_by_id: Mapping[str, dict],
    cache_dir: Path,
    window_sec: float,
) -> tuple[list[dict], dict]:
    if not math.isfinite(window_sec) or window_sec <= 0:
        raise AnalysisError("--window-sec은 0보다 큰 유한한 값이어야 합니다.")
    records = []
    for video in evaluation_videos:
        video_id = video["video_id"]
        cohort_video = cohort_by_id.get(video_id)
        if cohort_video is None:
            raise AnalysisError(f"cohort manifest에 video_id가 없습니다: {video_id}")
        if cohort_video.get("label") != video["label"]:
            raise AnalysisError(f"cohort/evaluation label이 다릅니다: {video_id}")
        if video["label"] != "no_fall" or video["event_count"] == 0:
            continue
        cache = load_cache_metadata(cache_dir, video_id)
        probe = cohort_video["output_probe"]
        validate_cache_matches_cohort(cache, probe, video_id)
        diagnostics = {
            item["frame_number"]: item for item in video["event_diagnostics"]
        }
        duration_sec = min(float(video["duration_sec"]), float(probe["duration_sec"]))
        for event_index, frame_number in enumerate(video["event_frames"], start=1):
            if not isinstance(frame_number, int) or not 0 <= frame_number < cache["frame_count"]:
                raise AnalysisError(f"Event frame이 cache 범위를 벗어납니다: {video_id}")
            event_sec = frame_number / cache["fps"]
            diagnostic = diagnostics[frame_number]
            confirm_path = diagnostic.get("confirm_path")
            reason = diagnostic.get("candidate_entry_reason")
            if confirm_path not in VALID_CONFIRM_PATHS:
                raise AnalysisError(
                    f"알 수 없는 confirm_path입니다: {video_id}: {confirm_path!r}"
                )
            if reason not in VALID_ENTRY_REASONS:
                raise AnalysisError(
                    f"알 수 없는 candidate_entry_reason입니다: {video_id}: {reason!r}"
                )
            model_involved = confirm_path == "model" or reason == "model"
            records.append(
                {
                    "review_id": f"{video_id}_event_{event_index:02d}",
                    "source_dataset": cohort_manifest["source_dataset"],
                    "video_id": video_id,
                    "video_path": cohort_video["video_path"],
                    "subject_id": cohort_video.get("subject_id"),
                    "split_role": cohort_video.get("split_role"),
                    "activity_name": cohort_video.get("activity_name"),
                    "active_labels": _active_labels(cohort_video, event_sec),
                    "event_index": event_index,
                    "event_frame": frame_number,
                    "event_sec": event_sec,
                    "fps": cache["fps"],
                    "confirm_path": confirm_path,
                    "candidate_entry_reason": reason,
                    "track_id": diagnostic.get("track_id"),
                    "review_start_sec": max(0.0, event_sec - window_sec),
                    "review_end_sec": min(duration_sec, event_sec + window_sec),
                    "diagnostic_route": (
                        "aux_model_involved" if model_involved else "rule_only"
                    ),
                    "review_status": "pending",
                    "review_decision": "",
                    "selected_for_training": False,
                }
            )

    summary = {
        "false_event_count": len(records),
        "false_event_video_count": len({record["video_id"] for record in records}),
        "by_confirm_path": dict(
            sorted(Counter(record["confirm_path"] for record in records).items())
        ),
        "by_candidate_entry_reason": dict(
            sorted(
                Counter(record["candidate_entry_reason"] for record in records).items()
            )
        ),
        "by_activity": dict(
            sorted(
                Counter("|".join(record["active_labels"]) for record in records).items()
            )
        ),
        "diagnostic_route": {
            "aux_model_involved": sum(
                record["diagnostic_route"] == "aux_model_involved" for record in records
            ),
            "rule_only": sum(
                record["diagnostic_route"] == "rule_only" for record in records
            ),
        },
    }
    return records, summary


def _csv_text(records: Sequence[dict]) -> str:
    fields = [
        "review_id",
        "source_dataset",
        "video_id",
        "video_path",
        "subject_id",
        "split_role",
        "activity_name",
        "active_labels",
        "event_index",
        "event_frame",
        "event_sec",
        "fps",
        "confirm_path",
        "candidate_entry_reason",
        "track_id",
        "review_start_sec",
        "review_end_sec",
        "diagnostic_route",
        "review_status",
        "review_decision",
        "selected_for_training",
    ]
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for record in records:
        row = dict(record)
        row["active_labels"] = "|".join(record["active_labels"])
        writer.writerow({field: row.get(field, "") for field in fields})
    return output.getvalue()


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as file:
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def write_outputs(
    output_dir: Path,
    records: Sequence[dict],
    summary: Mapping[str, object],
    sources: Mapping[str, Path],
    window_sec: float,
    force: bool,
) -> dict:
    csv_path = output_dir / OUTPUT_CSV
    json_path = output_dir / OUTPUT_JSON
    if not force and (csv_path.exists() or json_path.exists()):
        raise AnalysisError(f"{output_dir}에 분석 결과가 이미 있습니다 (--force로 교체).")
    for description, path in sources.items():
        if not path.is_file():
            raise AnalysisError(f"{description} provenance 파일이 없습니다: {path}")
    csv_content = _csv_text(records)
    payload = {
        "schema_version": ANALYSIS_SCHEMA_VERSION,
        "purpose": "manual review and E1 routing; not direct training input",
        "window_sec": window_sec,
        "sources": {
            name: {"path": str(path), "sha256": sha256_file(path)}
            for name, path in sources.items()
        },
        "summary": summary,
        "false_events_csv_sha256": hashlib.sha256(
            csv_content.encode("utf-8")
        ).hexdigest(),
    }
    _atomic_write(csv_path, csv_content)
    _atomic_write(json_path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return payload


def main() -> None:
    args = parse_args()
    evaluation_path = Path(args.evaluation)
    cohort_manifest_path = Path(args.cohort_manifest)
    cache_dir = Path(args.cache_dir)
    try:
        evaluation_videos = load_evaluation(evaluation_path)
        cohort_manifest, cohort_by_id = load_cohort(cohort_manifest_path)
        records, summary = analyze(
            evaluation_videos,
            cohort_manifest,
            cohort_by_id,
            cache_dir,
            args.window_sec,
        )
        write_outputs(
            Path(args.output_dir),
            records,
            summary,
            {
                "evaluation": evaluation_path,
                "cohort_manifest": cohort_manifest_path,
                "cache_manifest": cache_dir / "manifest.json",
            },
            args.window_sec,
            args.force,
        )
    except AnalysisError as exc:
        raise SystemExit(str(exc)) from exc
    print(
        f"실제 RGB false Event 분석: {summary['false_event_count']} events / "
        f"{summary['false_event_video_count']} videos -> {args.output_dir}"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
