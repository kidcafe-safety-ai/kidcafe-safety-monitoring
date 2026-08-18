"""`scripts/verify_track_identity.py`의 입력 파싱과 조회 검증.

그리기 자체는 눈으로 보려고 만든 것이라 검사하지 않는다. 대신 **엉뚱한 것을
보고 판단하게 만드는 입력**을 막는지 본다. manifest에 없는 `video_id`나 캐시에
없는 영상을 조용히 통과시키면, 빈 이미지를 보고 Track이 없다고 결론 내리게
된다.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

vti = pytest.importorskip(
    "scripts.verify_track_identity",
    reason="cv2가 없으면 건너뛴다",
)


# --- frame 목록 ---


def test_frames_are_parsed_in_order():
    assert vti.parse_frames("450,250,350") == [250, 350, 450]


def test_duplicate_frames_collapse():
    assert vti.parse_frames("300, 300") == [300]


def test_blank_pieces_are_ignored():
    assert vti.parse_frames("100,,200") == [100, 200]


def test_non_numeric_frame_is_rejected():
    with pytest.raises(vti.VerifyError, match="숫자"):
        vti.parse_frames("100,abc")


def test_empty_frame_list_is_rejected():
    with pytest.raises(vti.VerifyError, match="확인할 frame"):
        vti.parse_frames(" , ")


# --- 색 ---


def test_same_track_id_always_gets_the_same_color():
    assert vti.color_for(2) == vti.color_for(2)


def test_different_track_ids_are_distinguishable():
    assert vti.color_for(2) != vti.color_for(3)


# --- manifest 조회 ---


def write_manifest(path: Path):
    with open(path, "w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file, lineterminator="\n")
        writer.writerow(["video_id", "video_path"])
        writer.writerow(["V1", "data/videos/a.mp4"])
    return path


def test_video_path_is_found(tmp_path):
    path = write_manifest(tmp_path / "m.csv")
    assert vti.find_video(path, "V1") == "data/videos/a.mp4"


def test_unknown_video_id_is_rejected(tmp_path):
    path = write_manifest(tmp_path / "m.csv")
    with pytest.raises(vti.VerifyError, match="V9"):
        vti.find_video(path, "V9")


def test_missing_manifest_is_rejected(tmp_path):
    with pytest.raises(vti.VerifyError, match="manifest"):
        vti.find_video(tmp_path / "nope.csv", "V1")


# --- 캐시 조회 ---


def write_cache(path: Path):
    payload = {"videos": {"V1": {"frames": {"10": [{"track_id": 2}]}}}}
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_cached_frames_are_read(tmp_path):
    path = write_cache(tmp_path / "cache.json")
    assert vti.load_cached_frames(path, "V1") == {"10": [{"track_id": 2}]}


def test_video_missing_from_cache_is_rejected(tmp_path):
    path = write_cache(tmp_path / "cache.json")
    with pytest.raises(vti.VerifyError, match="V9"):
        vti.load_cached_frames(path, "V9")


def test_missing_cache_is_rejected(tmp_path):
    with pytest.raises(vti.VerifyError, match="캐시"):
        vti.load_cached_frames(tmp_path / "nope.json", "V1")
