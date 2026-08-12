"""Zone 경계 테이프를 영상에서 클릭해 floor·image 두 형식으로 저장한다.

Homography PoC는 같은 물리적 Zone을 두 경로로 판정해 비교한다. 두 Zone을 따로
정의하면 경계가 미세하게 달라져 판정 차이가 변환 성능인지 정의 차이인지
구분할 수 없다. 그래서 꼭짓점을 한 번만 찍고 여기서 두 형식을 함께 만든다.

- floor 좌표 Zone: `docs/homography_calibration.md` 좌표계. `--calibration`의
  homography로 픽셀을 변환한다.
- image-normalized Zone: 기존 경로. 픽셀을 프레임 크기로 나눈다.

`--calibration`은 같은 클립에서 만든 calibration이어야 한다. 촬영 중 카메라가
움직였으므로 다른 클립의 calibration을 쓰면 좌표가 어긋난다.

사용 예:

    python scripts/pick_zone_polygon.py \\
        --video data/videos/IMG_7325.MOV \\
        --frame 40 \\
        --calibration configs/camera_calibration/cam01_clip00_orig.json \\
        --zone-id play_floor \\
        --zone-name "놀이 구역" \\
        --zone-type play \\
        --corners 4 \\
        --floor-output data/zones/floor_cam01.json \\
        --image-output data/zones/image_cam01.json

조작:
    좌클릭      다음 꼭짓점 지정
    마우스 휠   확대·축소
    u, BS       직전 입력 취소
    s, Enter    저장 후 종료
    q / ESC     저장하지 않고 종료

꼭짓점은 Zone 둘레를 따라 한 방향으로 찍는다. 순서가 섞이면 폴리곤이
자기교차해 저장 단계에서 거부된다.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import List, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from pick_calibration_points import (  # noqa: E402
    PickerError,
    Picker,
    ReferencePoint,
    read_frame,
)
from src.geofencing.floor_plane import (  # noqa: E402
    FloorPlaneTransformer,
    load_calibration,
)
from src.common.types import VALID_ZONE_TYPES  # noqa: E402
from src.geofencing.floor_zone import parse_floor_zones  # noqa: E402
from src.geofencing.polygon_rules import validate_polygon_points  # noqa: E402

MIN_CORNERS = 3
# 계약이 정한 집합을 그대로 쓴다. 직접 나열하면 common/types와 어긋나 저장 뒤
# 로더에서야 거부되는 Zone이 만들어진다.
ZONE_TYPES = tuple(sorted(VALID_ZONE_TYPES))
NORMALIZED_RANGE = (0.0, 1.0)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", required=True)
    parser.add_argument("--frame", type=int, default=0)
    parser.add_argument("--calibration", required=True, help="같은 클립의 calibration JSON")
    parser.add_argument("--zone-id", required=True)
    parser.add_argument("--zone-name", required=True)
    parser.add_argument(
        "--zone-type",
        default="play",
        choices=ZONE_TYPES,
        help="ENTER·EXIT는 이 값과 무관하고, DWELL과 ENTER 종류만 달라진다.",
    )
    parser.add_argument("--corners", type=int, default=4, help="Zone 꼭짓점 수")
    # store_true + default=True로 두면 옵션을 줘도 안 줘도 True라 enter_alert를
    # 끌 수 없다. 기본값은 True로 두되 --no-enter-alert로 끌 수 있어야 한다.
    parser.add_argument(
        "--enter-alert",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="ENTER Event 알림 여부. 끄려면 --no-enter-alert.",
    )
    parser.add_argument("--dwell-threshold-sec", type=int, default=5)
    parser.add_argument("--floor-output", required=True)
    parser.add_argument("--image-output", required=True)
    parser.add_argument(
        "--unit-verified",
        action="store_true",
        help=(
            "calibration 좌표가 실제 meter임이 확인됐을 때만 준다. 없으면 floor "
            "Zone에 diagnostic_only를 붙여 runtime 사용을 막는다."
        ),
    )
    return parser.parse_args()


def corner_slots(count: int) -> List[ReferencePoint]:
    """Picker는 기준점 목록을 받으므로 꼭짓점을 같은 형태로 만들어 재사용한다.

    실측 좌표가 없으므로 floor 값은 표시용 0으로 두고, 배너에는 순번만 쓴다.
    """
    if count < MIN_CORNERS:
        raise PickerError(f"--corners는 {MIN_CORNERS} 이상이어야 합니다: {count}")
    return [
        ReferencePoint(point_id=f"C{index + 1}", role="fit", floor_x=0.0, floor_y=0.0)
        for index in range(count)
    ]


def to_floor_points(
    transformer: FloorPlaneTransformer, picked: Sequence[Sequence[float]]
) -> List[List[float]]:
    return [[round(v, 4) for v in transformer.transform(list(point))] for point in picked]


def to_image_points(
    picked: Sequence[Sequence[float]], width: int, height: int
) -> List[List[float]]:
    """픽셀을 0~1 정규화 좌표로 바꾼다. 기존 Zone 경로의 형식이다."""
    return [
        [round(min(max(x / width, 0.0), 1.0), 6), round(min(max(y / height, 0.0), 1.0), 6)]
        for x, y in picked
    ]


def build_floor_config(args: argparse.Namespace, camera_id: str, points) -> dict:
    """floor Zone 설정을 만든다.

    `coordinate_space`는 로더가 `floor_meters`만 받으므로 값을 바꿀 수 없다.
    그런데 이번 촬영은 줄자 눈금의 단위가 확정되지 않아 points가 meter라고
    단정할 수 없다. 값이 meter인 척하는 파일이 runtime에 흘러들지 않도록
    단위가 확인되기 전까지는 진단용 표시를 함께 저장한다.
    """
    config = {
        "schema_version": 1,
        "camera_id": camera_id,
        "coordinate_space": "floor_meters",
        "zones": [
            {
                "zone_id": args.zone_id,
                "zone_name": args.zone_name,
                "type": "polygon",
                "zone_type": args.zone_type,
                "points": points,
                "rules": {
                    "enter_alert": bool(args.enter_alert),
                    "dwell_threshold_sec": int(args.dwell_threshold_sec),
                },
            }
        ],
    }
    if not args.unit_verified:
        config["diagnostic_only"] = True
        config["unit_note"] = (
            "calibration 좌표 단위 미확인. points는 meter가 아니라 촬영 기록 "
            "원단위를 100으로 나눈 값이다. runtime에 사용하지 않는다."
        )
    return config


def build_image_config(args: argparse.Namespace, points) -> list:
    return [
        {
            "zone_id": args.zone_id,
            "name": args.zone_name,
            "type": "polygon",
            "zone_type": args.zone_type,
            "points": points,
            "rules": {
                "enter_alert": bool(args.enter_alert),
                "dwell_threshold_sec": int(args.dwell_threshold_sec),
            },
        }
    ]


def write_json_atomic(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as file:
            json.dump(payload, file, ensure_ascii=False, indent=2)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(temp_name, path)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise


def main() -> None:
    args = parse_args()
    try:
        slots = corner_slots(args.corners)
        frame = read_frame(Path(args.video), args.frame)
        calibration = load_calibration(args.calibration)
    except (PickerError, Exception) as exc:  # noqa: BLE001 - 로더 계약 오류를 그대로 보여준다
        raise SystemExit(str(exc)) from exc

    height, width = frame.shape[:2]
    if (width, height) != (calibration.frame_width, calibration.frame_height):
        raise SystemExit(
            f"영상 해상도가 calibration과 다릅니다: {width}x{height} != "
            f"{calibration.frame_width}x{calibration.frame_height}"
        )

    picker = Picker(frame, slots)
    if not picker.run():
        raise SystemExit("저장하지 않고 종료했습니다.")

    transformer = FloorPlaneTransformer(calibration)
    floor_points = to_floor_points(transformer, picker.picked)
    image_points = to_image_points(picker.picked, width, height)

    # 저장 전에 두 형식 모두 폴리곤 규칙을 통과하는지 확인한다. 꼭짓점 순서가
    # 섞여 자기교차하면 여기서 걸린다.
    try:
        validate_polygon_points(floor_points, label=f"zone '{args.zone_id}' floor points")
        validate_polygon_points(
            image_points,
            coordinate_range=NORMALIZED_RANGE,
            label=f"zone '{args.zone_id}' image points",
        )
        floor_config = build_floor_config(args, calibration.camera_id, floor_points)
        parse_floor_zones(floor_config)
    except Exception as exc:  # noqa: BLE001 - 검증 실패 사유를 그대로 보여준다
        raise SystemExit(f"Zone이 계약을 만족하지 않습니다: {exc}") from exc

    write_json_atomic(Path(args.floor_output), floor_config)
    write_json_atomic(Path(args.image_output), build_image_config(args, image_points))

    print(f"floor Zone 저장: {args.floor_output}")
    for name, point in zip(slots, floor_points):
        print(f"   {name.point_id}: (y {point[1]:.2f}, x {point[0]:.2f})")
    print(f"image Zone 저장: {args.image_output}")
    print(
        "두 파일은 같은 클릭에서 만들어졌으므로 같은 물리적 Zone을 나타낸다. "
        "판정 차이는 정의 차이가 아니라 좌표 경로 차이다."
    )


if __name__ == "__main__":
    main()
