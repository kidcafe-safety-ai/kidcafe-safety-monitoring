"""OmniFall E0 false Event를 원본 temporal label과 조인해 분류한다.

영상 디렉터리 이름은 대표 행동일 뿐 Event frame의 실제 행동을 보장하지
않는다. 이 도구는 평가 JSON, cohort manifest, Signal Cache FPS, OmniFall 공식
label을 함께 검증하고 Event 시각에 활성화된 행동과 confirm 경로를 기록한다.
출력은 review 대상이며 자동으로 학습 데이터로 채택하지 않는다.
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
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Sequence

from select_omnifall_hard_negatives import LABEL_NAMES, POSITIVE_LABELS


ANALYSIS_SCHEMA_VERSION = "omnifall_false_event_analysis_v1"
COHORT_SCHEMA_VERSION = "omnifall_e0_mining_cohort_v1"
OUTPUT_CSV = "false_events.csv"
OUTPUT_JSON = "false_event_analysis.json"
REQUIRED_LABEL_COLUMNS = {"path", "label", "start", "end"}


class AnalysisError(ValueError):
    """입력 provenance나 Event/label 정합성이 깨졌을 때 발생한다."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evaluation", required=True)
    parser.add_argument("--cohort-manifest", required=True)
    parser.add_argument("--labels", required=True)
    parser.add_argument("--cache-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--window-sec", type=float, default=1.0)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as file:
        for chunk in iter(lambda: file.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def _load_evaluation(path: Path) -> List[dict]:
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
        if not isinstance(video_id, str) or not video_id:
            raise AnalysisError("evaluation video_id가 비어 있습니다.")
        if video_id in seen:
            raise AnalysisError(f"evaluation video_id가 중복됩니다: {video_id}")
        seen.add(video_id)
        if video.get("label") != "no_fall" or video.get("error") is not None:
            raise AnalysisError(
                f"정상 no_fall 결과만 분석할 수 있습니다: {video_id}"
            )
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


def _load_cohort_paths(path: Path) -> Dict[str, dict]:
    payload = _load_json(path, "cohort manifest")
    if payload.get("schema_version") != COHORT_SCHEMA_VERSION:
        raise AnalysisError("cohort manifest schema_version이 다릅니다.")
    videos = payload.get("videos")
    if not isinstance(videos, list) or payload.get("video_count") != len(videos):
        raise AnalysisError("cohort manifest videos/video_count가 올바르지 않습니다.")
    result = {}
    for video in videos:
        video_id = video.get("video_id")
        source_path = video.get("source_path")
        if not isinstance(video_id, str) or not isinstance(source_path, str):
            raise AnalysisError("cohort video_id/source_path가 문자열이 아닙니다.")
        if video_id in result:
            raise AnalysisError(f"cohort video_id가 중복됩니다: {video_id}")
        result[video_id] = video
    return result


def _load_labels(path: Path) -> Dict[str, List[dict]]:
    if not path.is_file():
        raise AnalysisError(f"OmniFall label CSV가 없습니다: {path}")
    by_path: Dict[str, List[dict]] = defaultdict(list)
    with open(path, "r", encoding="utf-8", newline="") as file:
        reader = csv.DictReader(file)
        missing = REQUIRED_LABEL_COLUMNS - set(reader.fieldnames or [])
        if missing:
            raise AnalysisError(f"OmniFall label 필수 컬럼이 없습니다: {sorted(missing)}")
        for row_number, row in enumerate(reader, start=2):
            source_path = (row.get("path") or "").strip()
            try:
                label = int(row["label"])
                start = float(row["start"])
                end = float(row["end"])
            except (TypeError, ValueError) as exc:
                raise AnalysisError(
                    f"OmniFall label {row_number}행의 값이 올바르지 않습니다."
                ) from exc
            if not source_path or label not in LABEL_NAMES:
                raise AnalysisError(
                    f"OmniFall label {row_number}행의 path/label이 올바르지 않습니다."
                )
            if not all(math.isfinite(value) for value in (start, end)) or start > end:
                raise AnalysisError(
                    f"OmniFall label {row_number}행의 구간이 올바르지 않습니다."
                )
            by_path[source_path].append(
                {"label": label, "start_sec": start, "end_sec": end}
            )
    return dict(by_path)


def _cache_fps(cache_dir: Path, video_id: str) -> float:
    payload = _load_json(cache_dir / f"{video_id}.json", f"cache {video_id}")
    if payload.get("video_id") != video_id:
        raise AnalysisError(f"cache video_id가 파일명과 다릅니다: {video_id}")
    fps = payload.get("fps")
    if not isinstance(fps, (int, float)) or not math.isfinite(fps) or fps <= 0:
        raise AnalysisError(f"cache FPS가 올바르지 않습니다: {video_id}: {fps!r}")
    return float(fps)


def _active_labels(label_rows: Iterable[dict], event_sec: float) -> List[int]:
    return sorted(
        {
            row["label"]
            for row in label_rows
            if row["start_sec"] <= event_sec < row["end_sec"]
        }
    )


def analyze(
    evaluation_videos: Sequence[dict],
    cohort_paths: Mapping[str, dict],
    labels_by_path: Mapping[str, List[dict]],
    cache_dir: Path,
    window_sec: float,
) -> tuple[List[dict], dict]:
    if not math.isfinite(window_sec) or window_sec <= 0:
        raise AnalysisError("--window-sec은 0보다 큰 유한한 값이어야 합니다.")
    records = []
    for video in evaluation_videos:
        if video["event_count"] == 0:
            continue
        video_id = video["video_id"]
        cohort = cohort_paths.get(video_id)
        if cohort is None:
            raise AnalysisError(f"cohort manifest에 video_id가 없습니다: {video_id}")
        source_path = cohort["source_path"]
        if source_path not in labels_by_path:
            raise AnalysisError(f"공식 label에 source path가 없습니다: {source_path}")
        fps = _cache_fps(cache_dir, video_id)
        diagnostics = {
            item["frame_number"]: item for item in video["event_diagnostics"]
        }
        duration_sec = float(video["duration_sec"])
        for event_index, frame_number in enumerate(video["event_frames"], start=1):
            event_sec = frame_number / fps
            labels = _active_labels(labels_by_path[source_path], event_sec)
            if any(label in POSITIVE_LABELS for label in labels):
                raise AnalysisError(
                    f"false Event가 positive label 구간과 겹칩니다: "
                    f"{video_id} frame={frame_number}, labels={labels}"
                )
            diagnostic = diagnostics[frame_number]
            confirm_path = diagnostic.get("confirm_path")
            if confirm_path not in {"bbox", "pose", "model"}:
                raise AnalysisError(
                    f"알 수 없는 confirm_path입니다: {video_id}: {confirm_path!r}"
                )
            reason = diagnostic.get("candidate_entry_reason")
            if reason not in {"dynamic", "model", "handoff"}:
                raise AnalysisError(
                    f"알 수 없는 candidate_entry_reason입니다: {video_id}: {reason!r}"
                )
            label_names = [LABEL_NAMES[label] for label in labels]
            records.append(
                {
                    "review_id": f"{video_id}_event_{event_index:02d}",
                    "video_id": video_id,
                    "source_path": source_path,
                    "primary_category": source_path.split("/", 1)[0],
                    "event_index": event_index,
                    "event_frame": frame_number,
                    "event_sec": event_sec,
                    "fps": fps,
                    "active_label_ids": labels,
                    "active_labels": label_names,
                    "confirm_path": confirm_path,
                    "candidate_entry_reason": reason,
                    "track_id": diagnostic.get("track_id"),
                    "review_start_sec": max(0.0, event_sec - window_sec),
                    "review_end_sec": min(duration_sec, event_sec + window_sec),
                    "diagnostic_route": (
                        "aux_model" if confirm_path == "model" else "rule_or_temporal"
                    ),
                    "review_status": "pending",
                    "selected_for_training": False,
                }
            )

    confirm_counts = Counter(record["confirm_path"] for record in records)
    reason_counts = Counter(record["candidate_entry_reason"] for record in records)
    activity_counts = Counter(
        "|".join(record["active_labels"]) or "unlabeled" for record in records
    )
    primary_counts = Counter(record["primary_category"] for record in records)
    summary = {
        "false_event_count": len(records),
        "false_event_video_count": len({record["video_id"] for record in records}),
        "by_confirm_path": dict(sorted(confirm_counts.items())),
        "by_candidate_entry_reason": dict(sorted(reason_counts.items())),
        "by_active_labels": dict(sorted(activity_counts.items())),
        "by_primary_category": dict(sorted(primary_counts.items())),
        "diagnostic_route": {
            "aux_model": sum(
                record["diagnostic_route"] == "aux_model" for record in records
            ),
            "rule_or_temporal": sum(
                record["diagnostic_route"] == "rule_or_temporal"
                for record in records
            ),
        },
    }
    return records, summary


def _csv_text(records: Sequence[dict]) -> str:
    fields = [
        "review_id",
        "video_id",
        "source_path",
        "primary_category",
        "event_index",
        "event_frame",
        "event_sec",
        "fps",
        "active_label_ids",
        "active_labels",
        "confirm_path",
        "candidate_entry_reason",
        "track_id",
        "review_start_sec",
        "review_end_sec",
        "diagnostic_route",
        "review_status",
        "selected_for_training",
    ]
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for record in records:
        row = dict(record)
        row["active_label_ids"] = "|".join(map(str, record["active_label_ids"]))
        row["active_labels"] = "|".join(record["active_labels"])
        writer.writerow({field: row[field] for field in fields})
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
    summary: dict,
    sources: Mapping[str, Path],
    window_sec: float,
    force: bool,
) -> dict:
    csv_path = output_dir / OUTPUT_CSV
    json_path = output_dir / OUTPUT_JSON
    if not force and (csv_path.exists() or json_path.exists()):
        raise AnalysisError(f"{output_dir}에 분석 결과가 이미 있습니다 (--force로 교체).")
    csv_content = _csv_text(records)
    payload = {
        "schema_version": ANALYSIS_SCHEMA_VERSION,
        "purpose": "manual review and E1 routing; not direct training input",
        "window_sec": window_sec,
        "sources": {
            name: {"path": str(path), "sha256": _sha256(path)}
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
    labels_path = Path(args.labels)
    cache_dir = Path(args.cache_dir)
    try:
        evaluation_videos = _load_evaluation(evaluation_path)
        cohort_paths = _load_cohort_paths(cohort_manifest_path)
        labels_by_path = _load_labels(labels_path)
        records, summary = analyze(
            evaluation_videos,
            cohort_paths,
            labels_by_path,
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
                "labels": labels_path,
                "cache_manifest": cache_dir / "manifest.json",
            },
            args.window_sec,
            args.force,
        )
    except AnalysisError as exc:
        raise SystemExit(str(exc)) from exc
    print(
        f"OmniFall false Event 분석: {summary['false_event_count']} events / "
        f"{summary['false_event_video_count']} videos -> {args.output_dir}"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
