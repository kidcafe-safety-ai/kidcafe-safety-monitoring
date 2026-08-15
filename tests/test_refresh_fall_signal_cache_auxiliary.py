from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import fall_signal_cache as cache  # noqa: E402
import refresh_fall_signal_cache_auxiliary as refresh  # noqa: E402
from src.common.types import Track  # noqa: E402
from src.safety.auxiliary_fall_model import FallDetection  # noqa: E402


def _write_video(path: Path, frame_count: int = 2) -> None:
    writer = cv2.VideoWriter(
        str(path),
        cv2.VideoWriter_fourcc(*"mp4v"),
        10.0,
        (32, 32),
    )
    assert writer.isOpened()
    for value in range(frame_count):
        writer.write(np.full((32, 32, 3), value * 50, dtype=np.uint8))
    writer.release()


def _source_cache(tmp_path: Path) -> tuple[Path, Path]:
    video = tmp_path / "video.mp4"
    _write_video(video)
    source = tmp_path / "source"
    tracker = {
        "tracker_type": "pose",
        "model_sha256": "a" * 64,
        "resolved_device": "mps",
    }
    old_aux = {
        "model_sha256": "b" * 64,
        "resolved_device": "mps",
    }
    frames = [
        cache.CachedFrame(
            frame_number=0,
            timestamp="00:00:00.000",
            tracks=[
                Track(
                    track_id=1,
                    bbox=[1, 1, 20, 20],
                    foot_point=[10.5, 20],
                    confidence=0.9,
                )
            ],
            raw_detections=[FallDetection([1, 1, 20, 20], "nofall", 0.8)],
        ),
        cache.CachedFrame(
            frame_number=1,
            timestamp="00:00:00.100",
            tracks=[],
            raw_detections=[],
        ),
    ]
    cache.write_video_cache(
        source / "video_1.json",
        "video_1",
        10.0,
        tracker,
        old_aux,
        frames,
        video_path=str(video),
        video_size_bytes=video.stat().st_size,
    )
    cache.write_manifest(
        source,
        cache.build_manifest(
            split="diagnostic",
            videos_dir=str(tmp_path),
            tracker_meta=tracker,
            auxiliary_meta=old_aux,
            dataset_provenance={"video_count": 1},
        ),
    )
    return source, video


def test_refresh_preserves_tracks_and_replaces_auxiliary_detections(
    tmp_path, monkeypatch
):
    source, _ = _source_cache(tmp_path)
    model = tmp_path / "e1.pt"
    model.write_bytes(b"e1 model")

    class DummyAuxiliaryModel:
        def __init__(self, **_kwargs):
            self._device = "mps"
            self.calls = 0

        def infer(self, _frame):
            self.calls += 1
            return [FallDetection([2, 2, 21, 21], "fall", 0.95)]

    monkeypatch.setattr(refresh, "AuxiliaryFallModel", DummyAuxiliaryModel)
    output = tmp_path / "output"

    report = refresh.refresh_cache(source, output, model, 0.5, "mps", False)

    source_metadata, source_frames = cache.read_video_cache(source / "video_1.json")
    metadata, frames = cache.read_video_cache(output / "video_1.json")
    assert report["video_count"] == 1
    assert metadata["tracker"] == source_metadata["tracker"]
    assert frames[0].tracks == source_frames[0].tracks
    assert frames[0].raw_detections[0].label == "fall"
    assert frames[1].raw_detections == []
    assert cache.read_manifest(output)["auxiliary_model"]["model_sha256"] == (
        cache.sha256_file(str(model))
    )


def test_refresh_rejects_same_source_and_output(tmp_path):
    source, _ = _source_cache(tmp_path)
    model = tmp_path / "e1.pt"
    model.write_bytes(b"e1 model")

    with pytest.raises(refresh.AuxiliaryCacheRefreshError, match="달라야"):
        refresh.refresh_cache(source, source, model, 0.5, "mps", False)
