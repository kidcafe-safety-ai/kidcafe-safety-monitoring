"""`scripts/pick_zone_polygon.py`의 CLI·설정 생성 검증.

GUI 클릭 부분은 자동화하지 않고, 클릭 결과를 파일로 바꾸는 경로만 검증한다.
이 경계에서 나온 결함이 실제로 있었다. `--enter-alert`가 `store_true`와
`default=True`로 선언돼 있어 옵션을 줘도 안 줘도 항상 True였고, CLI에서
`enter_alert=False`인 Zone을 만들 방법이 없었다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts import pick_zone_polygon as pzp  # noqa: E402
from src.common.types import VALID_ZONE_TYPES  # noqa: E402
from src.geofencing.floor_zone import parse_floor_zones  # noqa: E402
from src.geofencing.zone_loader import load_zones  # noqa: E402

BASE_ARGV = [
    "--video", "v.mov",
    "--calibration", "c.json",
    "--zone-id", "play_floor",
    "--zone-name", "놀이 구역",
    "--floor-output", "f.json",
    "--image-output", "i.json",
]
SQUARE = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]


def parse(extra):
    argv = ["pick_zone_polygon.py"] + BASE_ARGV + list(extra)
    original = sys.argv
    sys.argv = argv
    try:
        return pzp.parse_args()
    finally:
        sys.argv = original


def test_enter_alert_defaults_to_true():
    assert parse([]).enter_alert is True


def test_enter_alert_can_be_disabled():
    """--no-enter-alert가 실제로 False를 만든다."""
    assert parse(["--no-enter-alert"]).enter_alert is False


def test_enter_alert_flag_still_sets_true():
    assert parse(["--enter-alert"]).enter_alert is True


@pytest.mark.parametrize("extra,expected", [([], True), (["--no-enter-alert"], False)])
def test_enter_alert_reaches_both_configs(extra, expected):
    """CLI 값이 floor·image 두 형식 모두에 그대로 실린다."""
    args = parse(extra)
    floor = pzp.build_floor_config(args, "cam01", SQUARE)
    image = pzp.build_image_config(args, SQUARE)
    assert floor["zones"][0]["rules"]["enter_alert"] is expected
    assert image[0]["rules"]["enter_alert"] is expected


def test_zone_type_choices_match_the_contract():
    """스크립트가 받는 zone_type 집합이 common/types와 어긋나면 저장 뒤에야 걸린다."""
    assert set(pzp.ZONE_TYPES) == set(VALID_ZONE_TYPES)


def test_unit_unverified_marks_the_floor_zone_diagnostic():
    """단위 미확인 상태의 floor Zone이 runtime용으로 보이면 안 된다."""
    config = pzp.build_floor_config(parse([]), "cam01", SQUARE)
    assert config["diagnostic_only"] is True
    assert "unit_note" in config


def test_unit_verified_drops_the_diagnostic_marker():
    config = pzp.build_floor_config(parse(["--unit-verified"]), "cam01", SQUARE)
    assert "diagnostic_only" not in config
    assert "unit_note" not in config


def test_generated_configs_pass_their_loaders(tmp_path):
    """두 형식 모두 각자의 계약 로더를 통과해야 한다."""
    args = parse([])
    floor = pzp.build_floor_config(args, "cam01", SQUARE)
    parsed = parse_floor_zones(floor)
    assert parsed.zones[0].zone_id == "play_floor"

    normalized = [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9]]
    image_path = tmp_path / "image.json"
    pzp.write_json_atomic(image_path, pzp.build_image_config(args, normalized))
    zones = load_zones(str(image_path))
    assert zones[0].zone_id == "play_floor"


def test_corner_slots_rejects_degenerate_polygons():
    with pytest.raises(pzp.PickerError):
        pzp.corner_slots(2)
    assert len(pzp.corner_slots(4)) == 4


def test_corner_slots_are_all_fit_role():
    """Zone 꼭짓점은 실측 좌표가 없어 holdout 평가에 쓰이지 않는다."""
    assert {slot.role for slot in pzp.corner_slots(5)} == {"fit"}


def test_image_points_are_clamped_to_the_frame():
    """클릭이 프레임 밖으로 나가도 정규화 좌표는 0~1을 벗어나지 않는다."""
    points = pzp.to_image_points([(-5.0, -5.0), (2000.0, 1200.0)], 1920, 1080)
    for x, y in points:
        assert 0.0 <= x <= 1.0
        assert 0.0 <= y <= 1.0


def test_written_json_is_readable(tmp_path):
    target = tmp_path / "nested" / "floor.json"
    payload = pzp.build_floor_config(parse([]), "cam01", SQUARE)
    pzp.write_json_atomic(target, payload)
    assert json.loads(target.read_text(encoding="utf-8")) == payload
    assert not list(target.parent.glob("*.tmp"))


def test_dwell_threshold_is_carried_through():
    args = parse(["--dwell-threshold-sec", "12"])
    floor = pzp.build_floor_config(args, "cam01", SQUARE)
    image = pzp.build_image_config(args, SQUARE)
    assert floor["zones"][0]["rules"]["dwell_threshold_sec"] == 12
    assert image[0]["rules"]["dwell_threshold_sec"] == 12
