"""scripts/export_fall_model.py 테스트."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import export_fall_model as export  # noqa: E402


def _make_run_dir(tmp_path: Path, weights_content: bytes, manifest_sha256: str = None) -> Path:
    run_dir = tmp_path / "run"
    weights_dir = run_dir / "weights"
    weights_dir.mkdir(parents=True)
    best_pt = weights_dir / "best.pt"
    best_pt.write_bytes(weights_content)

    if manifest_sha256 is None:
        manifest_sha256 = hashlib.sha256(weights_content).hexdigest()
    manifest = {"best_pt_sha256": manifest_sha256, "config": {"model": "yolo26n.pt"}}
    (run_dir / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return run_dir


class TestVerifyAndExport:
    def test_copies_file_when_sha256_matches(self, tmp_path):
        run_dir = _make_run_dir(tmp_path, b"real weights")
        dest = tmp_path / "models" / "fall_detector_v1.pt"

        result = export.verify_and_export(run_dir, dest, force=False)

        assert dest.is_file()
        assert dest.read_bytes() == b"real weights"
        assert result["sha256"] == hashlib.sha256(b"real weights").hexdigest()

    def test_sha256_mismatch_raises(self, tmp_path):
        run_dir = _make_run_dir(tmp_path, b"real weights", manifest_sha256="deadbeef")
        dest = tmp_path / "models" / "fall_detector_v1.pt"

        with pytest.raises(export.ExportError, match="SHA-256"):
            export.verify_and_export(run_dir, dest, force=False)

    def test_missing_best_pt_raises(self, tmp_path):
        run_dir = tmp_path / "run"
        run_dir.mkdir()

        with pytest.raises(export.ExportError, match="best.pt"):
            export.verify_and_export(run_dir, tmp_path / "dest.pt", force=False)

    def test_refuses_to_overwrite_without_force(self, tmp_path):
        run_dir = _make_run_dir(tmp_path, b"real weights")
        dest = tmp_path / "models" / "fall_detector_v1.pt"
        dest.parent.mkdir(parents=True)
        dest.write_bytes(b"existing")

        with pytest.raises(export.ExportError, match="force"):
            export.verify_and_export(run_dir, dest, force=False)

    def test_force_allows_overwrite(self, tmp_path):
        run_dir = _make_run_dir(tmp_path, b"real weights")
        dest = tmp_path / "models" / "fall_detector_v1.pt"
        dest.parent.mkdir(parents=True)
        dest.write_bytes(b"existing")

        result = export.verify_and_export(run_dir, dest, force=True)

        assert dest.read_bytes() == b"real weights"
        assert result["dest"] == str(dest)

    def test_final_metrics_none_when_no_results_csv(self, tmp_path):
        run_dir = _make_run_dir(tmp_path, b"real weights")
        dest = tmp_path / "models" / "fall_detector_v1.pt"

        result = export.verify_and_export(run_dir, dest, force=False)

        assert result["final_metrics"] is None

    def test_final_metrics_read_from_results_csv(self, tmp_path):
        run_dir = _make_run_dir(tmp_path, b"real weights")
        (run_dir / "results.csv").write_text(
            "epoch,metrics/precision(B),metrics/recall(B),metrics/mAP50(B),"
            "metrics/mAP50-95(B)\n"
            "1,0.5,0.4,0.3,0.2\n"
            "2,0.9,0.8,0.7,0.6\n"
        )
        dest = tmp_path / "models" / "fall_detector_v1.pt"

        result = export.verify_and_export(run_dir, dest, force=False)

        assert result["final_metrics"] == {
            "precision": 0.9,
            "recall": 0.8,
            "mAP50": 0.7,
            "mAP50_95": 0.6,
        }


class TestReadFinalMetrics:
    def test_returns_none_for_empty_csv(self, tmp_path):
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        (run_dir / "results.csv").write_text("epoch,metrics/precision(B)\n")

        assert export._read_final_metrics(run_dir) is None

    def test_ignores_unknown_columns(self, tmp_path):
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        (run_dir / "results.csv").write_text(
            "epoch,some/other/metric\n1,42\n"
        )

        assert export._read_final_metrics(run_dir) is None
