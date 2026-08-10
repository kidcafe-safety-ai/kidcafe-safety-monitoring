"""기존 Signal Cache의 Track은 유지하고 보조 낙상 모델 신호만 갱신한다.

동일한 PoseTracker 결과에서 E0와 E1 보조 모델을 비교하기 위한 실험 도구다.
원본 영상을 다시 디코딩해 새 모델 detection을 만들되, Track·Pose·timestamp는
source cache 값을 그대로 복사한다. 전체 출력은 staging 디렉터리에서 만든 뒤
교체해 중단된 cache를 완성본으로 오인하지 않게 한다.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import fall_signal_cache as cache  # noqa: E402
from scripts import fall_evaluation_protocol as evaluation_protocol  # noqa: E402
from src.safety.auxiliary_fall_model import AuxiliaryFallModel  # noqa: E402


class AuxiliaryCacheRefreshError(ValueError):
    """source cache나 원본 영상이 갱신 계약을 만족하지 않을 때 발생한다."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-cache", required=True)
    parser.add_argument("--output-cache", required=True)
    parser.add_argument("--fall-model-path", required=True)
    parser.add_argument("--fall-model-conf", type=float, default=0.5)
    parser.add_argument("--fall-model-device", default="auto")
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def _replace_output(staging: Path, output: Path, force: bool) -> None:
    if output.exists() and not force:
        raise AuxiliaryCacheRefreshError(f"출력 cache가 이미 있습니다: {output}")
    backup = output.with_name(f".{output.name}.backup-{os.getpid()}")
    if output.exists():
        output.rename(backup)
    try:
        staging.rename(output)
    except Exception:
        if backup.exists() and not output.exists():
            backup.rename(output)
        raise
    shutil.rmtree(backup, ignore_errors=True)


def _video_cache_paths(source_cache: Path) -> list[Path]:
    paths = sorted(
        path
        for path in source_cache.glob("*.json")
        if path.name not in {"manifest.json", "timing_report.json"}
    )
    if not paths:
        raise AuxiliaryCacheRefreshError(f"영상 cache가 없습니다: {source_cache}")
    return paths


def _refresh_video(
    source_path: Path,
    output_path: Path,
    source_manifest: dict,
    auxiliary_model: AuxiliaryFallModel,
    auxiliary_meta: dict,
) -> dict:
    metadata, cached_frames = cache.read_video_cache(source_path)
    video_id = metadata["video_id"]
    if metadata.get("tracker") != source_manifest.get("tracker"):
        raise AuxiliaryCacheRefreshError(
            f"{video_id}: 개별 cache와 source manifest의 tracker가 다릅니다."
        )
    video_path_text = metadata.get("video_path")
    if not isinstance(video_path_text, str) or not video_path_text:
        raise AuxiliaryCacheRefreshError(f"{video_id}: 원본 video_path가 없습니다.")
    video_path = Path(video_path_text)
    if not video_path.is_file():
        raise AuxiliaryCacheRefreshError(f"{video_id}: 원본 영상이 없습니다: {video_path}")
    expected_size = metadata.get("video_size_bytes")
    if expected_size is not None and video_path.stat().st_size != expected_size:
        raise AuxiliaryCacheRefreshError(f"{video_id}: 원본 영상 크기가 cache와 다릅니다.")

    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise AuxiliaryCacheRefreshError(f"{video_id}: 원본 영상을 열 수 없습니다.")
    refreshed_frames = []
    started = time.perf_counter()
    try:
        for cached_frame in cached_frames:
            ok, frame = capture.read()
            if not ok:
                raise AuxiliaryCacheRefreshError(
                    f"{video_id}: frame {cached_frame.frame_number} 디코딩에 실패했습니다."
                )
            detections = (
                auxiliary_model.infer(frame) if cached_frame.tracks else []
            )
            refreshed_frames.append(
                cache.CachedFrame(
                    frame_number=cached_frame.frame_number,
                    timestamp=cached_frame.timestamp,
                    tracks=cached_frame.tracks,
                    raw_detections=detections,
                )
            )
        has_extra_frame, _ = capture.read()
        if has_extra_frame:
            raise AuxiliaryCacheRefreshError(
                f"{video_id}: 원본 영상 frame 수가 source cache보다 많습니다."
            )
    finally:
        capture.release()
    elapsed_sec = time.perf_counter() - started

    cache.write_video_cache(
        output_path,
        video_id=video_id,
        fps=float(metadata["fps"]),
        tracker_meta=metadata["tracker"],
        auxiliary_meta=auxiliary_meta,
        frames=refreshed_frames,
        video_path=str(video_path.resolve()),
        video_size_bytes=video_path.stat().st_size,
    )
    return {
        "video_id": video_id,
        "frame_count": len(refreshed_frames),
        "elapsed_sec": elapsed_sec,
    }


def refresh_cache(
    source_cache: Path,
    output_cache: Path,
    model_path: Path,
    model_conf: float,
    model_device: str,
    force: bool,
) -> dict:
    if source_cache.resolve() == output_cache.resolve():
        raise AuxiliaryCacheRefreshError("source와 output cache는 달라야 합니다.")
    source_manifest = cache.read_manifest(source_cache)
    if source_manifest is None:
        raise AuxiliaryCacheRefreshError(f"source manifest가 없습니다: {source_cache}")
    model_sha256 = cache.sha256_file(str(model_path))
    if model_sha256 is None:
        raise AuxiliaryCacheRefreshError(f"보조 모델 파일이 없습니다: {model_path}")
    auxiliary_model = AuxiliaryFallModel(
        model_path=str(model_path),
        conf=model_conf,
        device=model_device,
        enabled=True,
    )
    resolved_device = evaluation_protocol.normalize_resolved_device(
        auxiliary_model._device,
        "auxiliary model",
    )
    auxiliary_meta = {
        "model_path": str(model_path),
        "model_sha256": model_sha256,
        "conf": model_conf,
        "requested_device": model_device,
        "resolved_device": resolved_device,
    }
    output_manifest = dict(source_manifest)
    output_manifest["auxiliary_model"] = auxiliary_meta

    paths = _video_cache_paths(source_cache)
    expected_count = (source_manifest.get("dataset") or {}).get("video_count")
    if expected_count is not None and expected_count != len(paths):
        raise AuxiliaryCacheRefreshError(
            f"source cache 영상 수가 dataset provenance와 다릅니다: "
            f"{len(paths)}/{expected_count}"
        )

    output_cache.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(prefix=f".{output_cache.name}.build-", dir=output_cache.parent)
    )
    timings = []
    try:
        for index, source_path in enumerate(paths, start=1):
            print(f"  ({index}/{len(paths)}) {source_path.stem}: auxiliary 갱신 중...")
            timings.append(
                _refresh_video(
                    source_path,
                    staging / source_path.name,
                    source_manifest,
                    auxiliary_model,
                    auxiliary_meta,
                )
            )
        cache.write_manifest(staging, output_manifest)
        total_frames = sum(item["frame_count"] for item in timings)
        total_elapsed_sec = sum(item["elapsed_sec"] for item in timings)
        timing_report = {
            "operation": "auxiliary-only cache refresh",
            "video_count": len(timings),
            "total_frames": total_frames,
            "total_elapsed_sec": total_elapsed_sec,
            "fps_avg": total_frames / total_elapsed_sec if total_elapsed_sec else None,
            "source_cache_manifest_sha256": cache.sha256_file(
                str(cache.manifest_path_for(source_cache))
            ),
        }
        (staging / "timing_report.json").write_text(
            json.dumps(timing_report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        _replace_output(staging, output_cache, force)
        return timing_report
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def main() -> None:
    args = parse_args()
    try:
        report = refresh_cache(
            Path(args.source_cache),
            Path(args.output_cache),
            Path(args.fall_model_path),
            args.fall_model_conf,
            args.fall_model_device,
            args.force,
        )
    except (AuxiliaryCacheRefreshError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    print(
        "Auxiliary cache 갱신 완료: "
        f"{report['video_count']} videos, {report['total_frames']} frames, "
        f"{report['fps_avg']:.2f} FPS -> {args.output_cache}"
    )


if __name__ == "__main__":
    main()
