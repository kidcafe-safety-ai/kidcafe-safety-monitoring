"""Signal Cache 저장/재생 공통 I/O.

상태머신(candidate handoff, model-only 제한, temporal vote 등)을 실험할 때마다
YOLO pose/보조 모델 추론을 다시 돌리면 한 사이클에 수 분이 든다. 이 모듈은
영상 하나를 한 번만 추론해서 프레임별 Track과 보조 모델의 원본 detection을
JSON으로 저장하고, 나중에 그 값을 그대로 다시 읽어 재생할 수 있게 한다 —
추론 결과 자체는 바뀌지 않으므로, 이후 실험은 FallDetector 설정/코드만
바꿔가며 캐시를 재생하면 된다(`scripts/evaluate_fall_from_cache.py`).

원본 detection(FallModelEvidence로 IoU 매칭되기 전의 FallDetection)을
저장하는 이유: 매칭된 결과만 저장하면 iou_threshold를 바꾸는 실험을 할 수
없다. 원본을 저장해두면 재생 시점에 `scripts/evaluate_fall.py`의
`score_video_from_frame_source()`가 매번 새 iou_threshold로 다시 매칭한다.

캐시 파일은 영상당 하나이며 `outputs/fall_eval/cache/` 아래에 둔다 — 이
디렉터리는 `.gitignore`의 `outputs/fall_eval/`에 이미 포함되어 있어 Git에
잡히지 않는다. Tracker 설정(모델·conf·tracker_config)이 바뀌면 Track ID
할당 자체가 달라지므로, 캐시를 재사용하려면 저장 시점의 tracker 설정과
재생 시점의 기대값이 같은지 반드시 확인해야 한다 — 이 모듈은 tracker/
보조 모델 파일의 SHA-256과 conf 값을 메타데이터로 함께 저장해, 재생
스크립트가 이 확인을 강제할 수 있게 한다.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from src.common.types import Track
from src.safety.auxiliary_fall_model import FallDetection

CACHE_SCHEMA_VERSION = 1


@dataclass
class CachedFrame:
    frame_number: int
    timestamp: str
    tracks: List[Track]
    # 보조 모델을 안 쓴 캐시(--fall-model-path 없이 생성)면 None. 썼는데 이
    # 프레임에 Track이 없어 추론 자체를 건너뛴 경우는 빈 리스트 — None과
    # 의미가 다르다(src/safety/fall_pipeline.py _compute_model_evidence()와
    # 동일한 구분, evaluate_fall.py score_video_from_frame_source() 참고).
    raw_detections: Optional[List[FallDetection]]


def sha256_file(path: str) -> Optional[str]:
    """path가 실제로 존재하는 파일이면 SHA-256을, 아니면 None을 반환한다.

    ultralytics 내장 tracker 프리셋(예: "bytetrack.yaml")처럼 로컬 파일이
    아닌 경로는 조용히 잘못된 해시를 만들지 않고 None으로 남긴다 — 호출자가
    "확인 안 됨"과 "확인했고 이 값"을 구분할 수 있어야 한다.
    """
    resolved = Path(path)
    if not resolved.is_file():
        return None
    digest = hashlib.sha256()
    with open(resolved, "rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _track_to_dict(track: Track) -> dict:
    return {
        "track_id": track.track_id,
        "bbox": track.bbox,
        "foot_point": track.foot_point,
        "confidence": track.confidence,
        "keypoints": track.keypoints,
        "keypoints_conf": track.keypoints_conf,
    }


def _track_from_dict(data: dict) -> Track:
    return Track(
        track_id=data["track_id"],
        bbox=data["bbox"],
        foot_point=data["foot_point"],
        confidence=data["confidence"],
        keypoints=data.get("keypoints"),
        keypoints_conf=data.get("keypoints_conf"),
    )


def _detection_to_dict(detection: FallDetection) -> dict:
    return {
        "bbox": detection.bbox,
        "label": detection.label,
        "confidence": detection.confidence,
    }


def _detection_from_dict(data: dict) -> FallDetection:
    return FallDetection(bbox=data["bbox"], label=data["label"], confidence=data["confidence"])


def write_video_cache(
    path: Path,
    video_id: str,
    fps: float,
    tracker_meta: dict,
    auxiliary_meta: Optional[dict],
    frames: List[CachedFrame],
    video_path: Optional[str] = None,
    video_size_bytes: Optional[int] = None,
) -> None:
    """캐시 파일 하나(영상 하나)를 쓴다.

    tracker_meta 예시: {"model_path", "model_sha256", "conf", "tracker_config",
        "tracker_config_sha256"(파일로 확인 못 하면 None), "tracker_type",
        "requested_device", "resolved_device"}.
    auxiliary_meta: 보조 모델을 안 썼으면 None, 썼으면
        {"model_path", "model_sha256", "conf", "requested_device",
        "resolved_device"}.
    video_path: 원본 영상의 resolve()된 경로 문자열(선택) — 재생 시점에
        holdout 여부를 다시 확인하거나(scripts/evaluate_fall_from_cache.py)
        캐시가 어느 영상에서 왔는지 감사하는 데 쓴다.
    video_size_bytes: 원본 영상 파일 크기(선택) — 재생 시점에 원본이 그
        사이 바뀌었는지(크기가 다르면 최소한 다른 파일) 값싸게 확인하는 데
        쓴다. 영상 전체 SHA-256은 캐싱 때마다 큰 파일을 다시 읽어야 해서
        비용이 크므로 크기만 기록한다.
    """
    if fps <= 0:
        raise ValueError(f"{video_id}: fps는 0보다 커야 합니다: {fps}")
    if not frames:
        raise ValueError(f"{video_id}: frames가 비어 있습니다 (영상 디코딩 실패 가능성).")
    for index, frame in enumerate(frames):
        if frame.frame_number != index:
            raise ValueError(
                f"{video_id}: frames[{index}].frame_number={frame.frame_number}는 "
                f"{index}여야 합니다 (0부터 순서대로, 누락/중복 없이)."
            )

    payload = {
        "cache_schema_version": CACHE_SCHEMA_VERSION,
        "video_id": video_id,
        "video_path": video_path,
        "video_size_bytes": video_size_bytes,
        "fps": fps,
        "frame_count": len(frames),
        "tracker": tracker_meta,
        "auxiliary_model": auxiliary_meta,
        "frames": [
            {
                "frame_number": frame.frame_number,
                "timestamp": frame.timestamp,
                "tracks": [_track_to_dict(track) for track in frame.tracks],
                "raw_detections": (
                    None
                    if frame.raw_detections is None
                    else [_detection_to_dict(d) for d in frame.raw_detections]
                ),
            }
            for frame in frames
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as file:
        json.dump(payload, file)
    tmp_path.replace(path)  # POSIX에서 원자적 rename — 쓰다 중단돼도 원본 캐시 보존


def read_video_cache(
    path: Path, expected_video_id: Optional[str] = None
) -> Tuple[dict, List[CachedFrame]]:
    """캐시 파일을 읽어 (메타데이터, 프레임 목록)을 반환한다.

    metadata에는 cache_schema_version/video_id/video_path/fps/frame_count/
    tracker/auxiliary_model이 담긴다("frames"는 제외 — 호출자가 메타데이터만
    빠르게 확인하고 싶을 때 큰 배열을 굳이 함께 들고 있지 않게 하기 위함).

    expected_video_id를 넘기면 캐시 안의 video_id와 다를 때 즉시 거부한다 —
    잘못 놓이거나 복사된 캐시 파일이 엉뚱한 video_id로 조용히 평가되는 걸
    막기 위함이다.

    구조도 함께 검증한다: fps>0, frame_count==len(frames)(선언값과 실제
    저장된 개수 불일치), frame_number가 0..N-1 순서인지, 빈 캐시인지.
    """
    with open(path, "r", encoding="utf-8") as file:
        payload = json.load(file)

    schema_version = payload.get("cache_schema_version")
    if schema_version != CACHE_SCHEMA_VERSION:
        raise ValueError(
            f"{path}: cache_schema_version={schema_version}는 지원하지 않습니다 "
            f"(현재 지원: {CACHE_SCHEMA_VERSION}). scripts/cache_fall_signals.py로 "
            "다시 생성하세요."
        )

    cached_video_id = payload.get("video_id")
    if expected_video_id is not None and cached_video_id != expected_video_id:
        raise ValueError(
            f"{path}: 캐시의 video_id='{cached_video_id}'가 요청한 "
            f"'{expected_video_id}'와 다릅니다 — 잘못 놓인 캐시 파일일 수 있습니다."
        )

    fps = payload.get("fps")
    if not isinstance(fps, (int, float)) or fps <= 0:
        raise ValueError(f"{path}: fps는 0보다 커야 합니다: {fps}")

    raw_frames = payload.get("frames") or []
    if not raw_frames:
        raise ValueError(f"{path}: frames가 비어 있습니다.")

    declared_count = payload.get("frame_count")
    if declared_count != len(raw_frames):
        raise ValueError(
            f"{path}: frame_count={declared_count}가 실제 frames 개수"
            f"({len(raw_frames)})와 다릅니다 — 손상됐을 수 있습니다."
        )

    frames = []
    for index, raw in enumerate(raw_frames):
        if raw["frame_number"] != index:
            raise ValueError(
                f"{path}: frames[{index}].frame_number={raw['frame_number']}는 "
                f"{index}여야 합니다(0부터 순서대로) — 손상됐을 수 있습니다."
            )
        frames.append(
            CachedFrame(
                frame_number=raw["frame_number"],
                timestamp=raw["timestamp"],
                tracks=[_track_from_dict(t) for t in raw["tracks"]],
                raw_detections=(
                    None
                    if raw["raw_detections"] is None
                    else [_detection_from_dict(d) for d in raw["raw_detections"]]
                ),
            )
        )

    metadata = {k: v for k, v in payload.items() if k != "frames"}
    return metadata, frames


def cache_path_for(cache_dir: Path, video_id: str) -> Path:
    return cache_dir / f"{video_id}.json"


def has_existing_video_caches(cache_dir: Path) -> bool:
    """manifest.json을 제외한 영상 캐시(*.json)가 하나라도 있으면 True.

    manifest 없이(예: manifest 도입 이전 실행, 또는 손상) 개별 캐시 파일만
    남아 있는 디렉터리를 --force 없이 조용히 신뢰하지 않기 위해 쓴다.
    """
    if not cache_dir.exists():
        return False
    return any(
        path.name != manifest_path_for(cache_dir).name for path in cache_dir.glob("*.json")
    )


def manifest_path_for(cache_dir: Path) -> Path:
    return cache_dir / "manifest.json"


def build_manifest(
    split: str, videos_dir: str, tracker_meta: dict, auxiliary_meta: Optional[dict]
) -> dict:
    """캐시 디렉터리 하나 전체에 적용되는 설정 — 개별 영상 캐시가 아니라

    디렉터리 단위로 한 번만 기록한다. Pose/bbox tracker 혼용, conf 혼용,
    다른 모델 파일, 보조 모델 사용/미사용 혼합을 조용히 섞어 평가하는 걸
    막기 위함이다.
    """
    return {
        "cache_schema_version": CACHE_SCHEMA_VERSION,
        "split": split,
        "videos_dir": videos_dir,
        "tracker": tracker_meta,
        "auxiliary_model": auxiliary_meta,
    }


def write_manifest(cache_dir: Path, manifest: dict) -> None:
    path = manifest_path_for(cache_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as file:
        json.dump(manifest, file, indent=2)
    tmp_path.replace(path)


def read_manifest(cache_dir: Path) -> Optional[dict]:
    path = manifest_path_for(cache_dir)
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)
