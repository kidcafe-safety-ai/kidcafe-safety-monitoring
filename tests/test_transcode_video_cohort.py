"""영상 cohort H.264 변환 도구 테스트."""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import transcode_video_cohort as transcoder  # noqa: E402


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source_cohort(tmp_path: Path) -> Path:
    root = tmp_path / "source"
    video = root / "videos/sit_down/example.mp4"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"av1-video")
    annotations = root / transcoder.ANNOTATIONS_CSV
    annotations.write_text(
        "video_id,label,video_path,fall_start_frame,impact_frame,"
        "lying_start_frame,review_status\n"
        "ofsyn_sit_down_example,no_fall,videos/sit_down/example.mp4,,,,reviewed\n",
        encoding="utf-8",
    )
    manifest = {
        "schema_version": transcoder.SOURCE_SCHEMA_VERSION,
        "video_count": 1,
        "annotations_sha256": _sha256(annotations),
        "videos": [
            {
                "video_id": "ofsyn_sit_down_example",
                "video_path": "videos/sit_down/example.mp4",
                "size_bytes": video.stat().st_size,
                "sha256": _sha256(video),
            }
        ],
    }
    (root / transcoder.SOURCE_MANIFEST).write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    return root


def _probe(codec: str) -> dict:
    return {
        "codec_name": codec,
        "width": 640,
        "height": 480,
        "fps": 20.0,
        "duration_sec": 5.0,
        "frame_count": "100",
    }


def _fake_tools(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda value: f"/usr/bin/{value}")

    def fake_transcode(source, destination, ffmpeg, crf, preset):
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"h264-video")

    monkeypatch.setattr(transcoder, "_run_transcode", fake_transcode)
    monkeypatch.setattr(
        transcoder,
        "_probe_video",
        lambda path, ffprobe: _probe("h264" if "build-" in str(path) else "av1"),
    )


def test_transcodes_verified_cohort_and_writes_manifest(tmp_path, monkeypatch):
    source = _source_cohort(tmp_path)
    output = tmp_path / "h264"
    _fake_tools(monkeypatch)

    manifest = transcoder.transcode_cohort(
        source, output, "ffmpeg", "ffprobe", 18, "veryfast", False
    )

    assert manifest["schema_version"] == transcoder.TRANSCODE_SCHEMA_VERSION
    assert manifest["video_count"] == 1
    assert manifest["videos"][0]["output_probe"]["codec_name"] == "h264"
    assert (output / "videos/sit_down/example.mp4").read_bytes() == b"h264-video"
    assert (output / transcoder.ANNOTATIONS_CSV).read_bytes() == (
        source / transcoder.ANNOTATIONS_CSV
    ).read_bytes()
    assert (output / transcoder.TRANSCODE_MANIFEST).is_file()


def test_rejects_tampered_source_before_transcoding(tmp_path, monkeypatch):
    source = _source_cohort(tmp_path)
    (source / "videos/sit_down/example.mp4").write_bytes(b"tampered")
    _fake_tools(monkeypatch)

    with pytest.raises(transcoder.TranscodeError, match="크기가 manifest와"):
        transcoder.transcode_cohort(
            source, tmp_path / "h264", "ffmpeg", "ffprobe", 18, "veryfast", False
        )


def test_existing_output_requires_force(tmp_path, monkeypatch):
    source = _source_cohort(tmp_path)
    output = tmp_path / "h264"
    output.mkdir()
    _fake_tools(monkeypatch)

    with pytest.raises(transcoder.TranscodeError, match="force"):
        transcoder.transcode_cohort(
            source, output, "ffmpeg", "ffprobe", 18, "veryfast", False
        )


def test_failed_transcode_keeps_existing_output(tmp_path, monkeypatch):
    source = _source_cohort(tmp_path)
    output = tmp_path / "h264"
    output.mkdir()
    marker = output / "old.txt"
    marker.write_text("old", encoding="utf-8")
    monkeypatch.setattr(shutil, "which", lambda value: f"/usr/bin/{value}")
    monkeypatch.setattr(transcoder, "_probe_video", lambda path, tool: _probe("av1"))

    def fail(*args, **kwargs):
        raise transcoder.TranscodeError("failed")

    monkeypatch.setattr(transcoder, "_run_transcode", fail)

    with pytest.raises(transcoder.TranscodeError, match="failed"):
        transcoder.transcode_cohort(
            source, output, "ffmpeg", "ffprobe", 18, "veryfast", True
        )

    assert marker.read_text(encoding="utf-8") == "old"


@pytest.mark.parametrize(
    "video_path",
    ["../escape.mp4", "/absolute.mp4", "video.mp4", "videos/example.avi"],
)
def test_rejects_unsafe_video_path(tmp_path, video_path):
    source = _source_cohort(tmp_path)
    manifest_path = source / transcoder.SOURCE_MANIFEST
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["videos"][0]["video_path"] = video_path
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(transcoder.TranscodeError, match="video_path"):
        transcoder._load_and_validate_source(source)


def test_rejects_changed_video_properties():
    source = _probe("av1")
    output = _probe("h264")
    output["width"] = 320

    with pytest.raises(transcoder.TranscodeError, match="해상도"):
        transcoder._validate_equivalence(source, output)
