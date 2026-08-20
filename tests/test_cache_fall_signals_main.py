"""scripts/cache_fall_signals.py의 main() 순서 보장 테스트.

실제 YOLO 로딩 없이 PoseTracker/_cache_one_video를 더미로 바꿔치기해서,
"manifest는 전체 영상이 성공한 뒤에만 쓴다"는 계약을 회귀 테스트로 고정한다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import cache_fall_signals as cfs  # noqa: E402
import fall_signal_cache as cache  # noqa: E402


class _DummyTracker:
    def __init__(
        self,
        model_path=None,
        conf=None,
        tracker_config=None,
        fps=None,
        device=None,
    ):
        self._device = "mps" if device == "auto" else device


class _DummyAuxiliaryModel:
    def __init__(self, model_path=None, conf=None, device=None, enabled=None):
        self._device = "mps" if device == "auto" else device


class _UnresolvedDeviceProvider:
    def __init__(self, **_kwargs):
        pass


def _write_annotations_csv(path: Path, video_ids) -> None:
    path.write_text(
        "video_id,label,video_path,fall_start_frame,impact_frame,lying_start_frame,"
        "review_status\n"
        + "".join(f"{vid},no_fall,{vid}.avi,,,,reviewed\n" for vid in video_ids)
    )


@pytest.fixture(autouse=True)
def _no_real_tracker(monkeypatch):
    monkeypatch.setattr(cfs, "PoseTracker", _DummyTracker)
    monkeypatch.setattr(cfs, "ByteTracker", _DummyTracker)


class TestManifestWrittenOnlyAfterFullSuccess:
    def test_unresolved_tracker_device_fails_before_caching(
        self, tmp_path, monkeypatch
    ):
        annotations = tmp_path / "annotations.csv"
        _write_annotations_csv(annotations, ["v1"])
        videos_dir = tmp_path / "videos"
        videos_dir.mkdir()
        cache_dir = tmp_path / "cache"
        cache_called = False

        def _unexpected_cache(*_args, **_kwargs):
            nonlocal cache_called
            cache_called = True

        monkeypatch.setattr(cfs, "PoseTracker", _UnresolvedDeviceProvider)
        monkeypatch.setattr(cfs, "_cache_one_video", _unexpected_cache)
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "cache_fall_signals.py",
                "--annotations", str(annotations),
                "--videos-dir", str(videos_dir),
                "--split", "development",
                "--cache-dir", str(cache_dir),
            ],
        )

        with pytest.raises(SystemExit, match="tracker의 실제 inference device"):
            cfs.main()

        assert cache_called is False
        assert not cache_dir.exists()

    def test_unresolved_auxiliary_device_fails_before_caching(
        self, tmp_path, monkeypatch
    ):
        annotations = tmp_path / "annotations.csv"
        _write_annotations_csv(annotations, ["v1"])
        videos_dir = tmp_path / "videos"
        videos_dir.mkdir()
        cache_dir = tmp_path / "cache"
        fall_model = tmp_path / "fall.pt"
        fall_model.write_bytes(b"fall")
        cache_called = False

        def _unexpected_cache(*_args, **_kwargs):
            nonlocal cache_called
            cache_called = True

        monkeypatch.setattr(cfs, "AuxiliaryFallModel", _UnresolvedDeviceProvider)
        monkeypatch.setattr(cfs, "_cache_one_video", _unexpected_cache)
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "cache_fall_signals.py",
                "--annotations", str(annotations),
                "--videos-dir", str(videos_dir),
                "--split", "development",
                "--cache-dir", str(cache_dir),
                "--fall-model-path", str(fall_model),
            ],
        )

        with pytest.raises(SystemExit, match="auxiliary model의 실제 inference device"):
            cfs.main()

        assert cache_called is False
        assert not cache_dir.exists()

    def test_manifest_absent_if_caching_raises_partway(self, tmp_path, monkeypatch):
        annotations = tmp_path / "annotations.csv"
        _write_annotations_csv(annotations, ["v1", "v2", "v3"])
        videos_dir = tmp_path / "videos"
        videos_dir.mkdir()
        cache_dir = tmp_path / "cache"

        call_count = {"n": 0}

        def _fake_cache_one_video(
            video_id, video_path, tracker, auxiliary_model, cache_dir_arg,
            tracker_meta, auxiliary_meta,
        ):
            call_count["n"] += 1
            if call_count["n"] == 2:
                raise RuntimeError("시뮬레이션된 캐싱 실패(예: 영상 손상)")
            cache.write_video_cache(
                cache.cache_path_for(cache_dir_arg, video_id),
                video_id=video_id,
                fps=10.0,
                tracker_meta=tracker_meta,
                auxiliary_meta=auxiliary_meta,
                frames=[cache.CachedFrame(0, "00:00:00.000", [], None)],
            )
            return {"frame_count": 1, "elapsed_sec": 0.01}

        monkeypatch.setattr(cfs, "_cache_one_video", _fake_cache_one_video)
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "cache_fall_signals.py",
                "--annotations", str(annotations),
                "--videos-dir", str(videos_dir),
                "--split", "development",
                "--cache-dir", str(cache_dir),
            ],
        )

        with pytest.raises(RuntimeError, match="시뮬레이션된"):
            cfs.main()

        assert cache.read_manifest(cache_dir) is None
        assert call_count["n"] == 2  # v3는 아예 시도되지 않음(중단 시점 그대로)

    def test_manifest_written_when_all_videos_succeed(self, tmp_path, monkeypatch):
        annotations = tmp_path / "annotations.csv"
        _write_annotations_csv(annotations, ["v1", "v2"])
        videos_dir = tmp_path / "videos"
        videos_dir.mkdir()
        cache_dir = tmp_path / "cache"
        fall_model = tmp_path / "fall.pt"
        fall_model.write_bytes(b"fall")

        def _fake_cache_one_video(
            video_id, video_path, tracker, auxiliary_model, cache_dir_arg,
            tracker_meta, auxiliary_meta,
        ):
            cache.write_video_cache(
                cache.cache_path_for(cache_dir_arg, video_id),
                video_id=video_id,
                fps=10.0,
                tracker_meta=tracker_meta,
                auxiliary_meta=auxiliary_meta,
                frames=[cache.CachedFrame(0, "00:00:00.000", [], None)],
            )
            return {"frame_count": 1, "elapsed_sec": 0.01}

        monkeypatch.setattr(cfs, "_cache_one_video", _fake_cache_one_video)
        monkeypatch.setattr(cfs, "AuxiliaryFallModel", _DummyAuxiliaryModel)
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "cache_fall_signals.py",
                "--annotations", str(annotations),
                "--videos-dir", str(videos_dir),
                "--split", "development",
                "--cache-dir", str(cache_dir),
                "--fall-model-path", str(fall_model),
            ],
        )

        cfs.main()

        manifest = cache.read_manifest(cache_dir)
        assert manifest is not None
        assert manifest["tracker"]["requested_device"] == "auto"
        assert manifest["tracker"]["resolved_device"] == "mps"
        assert manifest["auxiliary_model"]["requested_device"] == "auto"
        assert manifest["auxiliary_model"]["resolved_device"] == "mps"
        assert manifest["auxiliary_model"]["model_sha256"] == cache.sha256_file(
            fall_model
        )

    def test_timing_report_written_for_newly_cached_videos(self, tmp_path, monkeypatch):
        """Tracker Sweep이 conf별 처리 FPS를 비교하려면

        cache_dir에 timing_report.json이 남아야 한다.
        """
        annotations = tmp_path / "annotations.csv"
        _write_annotations_csv(annotations, ["v1", "v2"])
        videos_dir = tmp_path / "videos"
        videos_dir.mkdir()
        cache_dir = tmp_path / "cache"

        def _fake_cache_one_video(
            video_id, video_path, tracker, auxiliary_model, cache_dir_arg,
            tracker_meta, auxiliary_meta,
        ):
            cache.write_video_cache(
                cache.cache_path_for(cache_dir_arg, video_id),
                video_id=video_id,
                fps=10.0,
                tracker_meta=tracker_meta,
                auxiliary_meta=auxiliary_meta,
                frames=[cache.CachedFrame(0, "00:00:00.000", [], None)],
            )
            return {"frame_count": 100, "elapsed_sec": 2.0}  # 50 FPS

        monkeypatch.setattr(cfs, "_cache_one_video", _fake_cache_one_video)
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "cache_fall_signals.py",
                "--annotations", str(annotations),
                "--videos-dir", str(videos_dir),
                "--split", "development",
                "--cache-dir", str(cache_dir),
            ],
        )

        cfs.main()

        report = json.loads((cache_dir / "timing_report.json").read_text())
        assert report["videos_timed"] == 2
        assert report["total_frames"] == 200
        assert report["fps_avg"] == pytest.approx(50.0)
        assert set(report["per_video_fps"]) == {"v1", "v2"}

    def test_rerun_after_interruption_without_force_is_rejected(self, tmp_path, monkeypatch):
        """중단 후(manifest 없음 + 캐시 파일 일부 존재) --force 없이 재실행하면

        조용히 이어서 캐싱하지 않고 명확히 거부해야 한다.
        """
        annotations = tmp_path / "annotations.csv"
        _write_annotations_csv(annotations, ["v1", "v2"])
        videos_dir = tmp_path / "videos"
        videos_dir.mkdir()
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        # v1만 캐싱된 채 manifest 없이 중단된 상태를 흉내낸다.
        cache.write_video_cache(
            cache.cache_path_for(cache_dir, "v1"),
            video_id="v1",
            fps=10.0,
            tracker_meta={},
            auxiliary_meta=None,
            frames=[cache.CachedFrame(0, "00:00:00.000", [], None)],
        )

        monkeypatch.setattr(
            sys,
            "argv",
            [
                "cache_fall_signals.py",
                "--annotations", str(annotations),
                "--videos-dir", str(videos_dir),
                "--split", "development",
                "--cache-dir", str(cache_dir),
            ],
        )

        with pytest.raises(SystemExit, match="manifest.json 없이"):
            cfs.main()

    def test_force_rerun_invalidates_existing_manifest_before_regenerating(
        self, tmp_path, monkeypatch
    ):
        """--force 재생성이 중단되면 기존 manifest도 무효화되는지 확인한다."""
        annotations = tmp_path / "annotations.csv"
        _write_annotations_csv(annotations, ["v1", "v2", "v3"])
        videos_dir = tmp_path / "videos"
        videos_dir.mkdir()
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        # 이전에 성공적으로 끝난 실행이 남긴 manifest + 캐시 파일.
        old_tracker_meta = {"tracker_type": "pose", "model_path": "old.pt", "conf": 0.4}
        old_manifest = cache.build_manifest(
            split="development",
            videos_dir=str(videos_dir.resolve()),
            tracker_meta=old_tracker_meta,
            auxiliary_meta=None,
        )
        cache.write_manifest(cache_dir, old_manifest)
        for video_id in ["v1", "v2", "v3"]:
            cache.write_video_cache(
                cache.cache_path_for(cache_dir, video_id),
                video_id=video_id,
                fps=10.0,
                tracker_meta=old_tracker_meta,
                auxiliary_meta=None,
                frames=[cache.CachedFrame(0, "00:00:00.000", [], None)],
            )

        call_count = {"n": 0}

        def _fake_cache_one_video(
            video_id, video_path, tracker, auxiliary_model, cache_dir_arg,
            tracker_meta, auxiliary_meta,
        ):
            call_count["n"] += 1
            if call_count["n"] == 2:
                raise RuntimeError("시뮬레이션된 캐싱 실패(예: 영상 손상)")
            cache.write_video_cache(
                cache.cache_path_for(cache_dir_arg, video_id),
                video_id=video_id,
                fps=10.0,
                tracker_meta=tracker_meta,
                auxiliary_meta=auxiliary_meta,
                frames=[cache.CachedFrame(0, "00:00:00.000", [], None)],
            )
            return {"frame_count": 1, "elapsed_sec": 0.01}

        monkeypatch.setattr(cfs, "_cache_one_video", _fake_cache_one_video)
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "cache_fall_signals.py",
                "--annotations", str(annotations),
                "--videos-dir", str(videos_dir),
                "--split", "development",
                "--cache-dir", str(cache_dir),
                "--force",
            ],
        )

        with pytest.raises(RuntimeError, match="시뮬레이션된"):
            cfs.main()

        # 옛 manifest가 그대로 남아있으면 안 된다 — 지금 v1은 이미 새 설정으로
        # 덮어써졌고 v3는 옛 설정 그대로인 채 섞인 상태이므로, 다음 실행이
        # (같은 옛 설정으로 --force 없이 재시도해도) 이 상태를 조용히
        # 신뢰하면 안 된다.
        assert cache.read_manifest(cache_dir) is None


class TestTrackerConfigMetadata:
    def _args(self, tracker_config, config_sha=None, reid_sha=None):
        return type(
            "Args",
            (),
            {
                "tracker_config": str(tracker_config),
                "tracker_config_sha256": config_sha,
                "reid_model_sha256": reid_sha,
            },
        )()

    def test_records_explicit_botsort_without_reid(self, tmp_path):
        config = tmp_path / "botsort.yaml"
        config.write_text(
            "tracker_type: botsort\nwith_reid: false\nmodel: auto\n",
            encoding="utf-8",
        )
        config_sha = cache.sha256_file(config)

        metadata = cfs._tracker_config_metadata(
            self._args(config, config_sha=config_sha)
        )

        assert metadata["tracker_backend"] == "botsort"
        assert metadata["with_reid"] is False
        assert metadata["tracker_config_sha256"] == config_sha
        assert metadata["reid_model_sha256"] is None

    def test_reid_auto_is_rejected_before_tracker_initialization(self, tmp_path):
        config = tmp_path / "botsort.yaml"
        config.write_text(
            "tracker_type: botsort\nwith_reid: true\nmodel: auto\n",
            encoding="utf-8",
        )

        with pytest.raises(ValueError, match="auto/URL"):
            cfs._tracker_config_metadata(
                self._args(config, config_sha=cache.sha256_file(config))
            )

    def test_reid_model_sha_mismatch_is_rejected(self, tmp_path):
        model = tmp_path / "reid.pt"
        model.write_bytes(b"model")
        config = tmp_path / "botsort.yaml"
        config.write_text(
            f"tracker_type: botsort\nwith_reid: true\nmodel: {model}\n",
            encoding="utf-8",
        )

        with pytest.raises(ValueError, match="ReID 모델 SHA-256 불일치"):
            cfs._tracker_config_metadata(
                self._args(
                    config,
                    config_sha=cache.sha256_file(config),
                    reid_sha="0" * 64,
                )
            )
