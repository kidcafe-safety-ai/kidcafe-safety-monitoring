"""기록된 기준점 픽셀을 영상 프레임에 겹쳐 그려 클립 대응을 확인한다.

촬영 원본은 Git에 없고 파일명도 `IMG_####.MOV`라 어느 파일이 어느
`calibration_version`인지 기억에 의존하게 된다. 잘못 짝지으면 Zone이 조용히
어긋난 채로 라벨링이 진행되므로, 눈으로 한 번 확인할 수단을 둔다.

기록된 좌표에 원을 그렸을 때 그 자리에 빨간 테이프가 있으면 그 파일이 맞다.
빗나가면 다른 클립이거나 다른 프레임이다.

사용 예:

    python scripts/verify_clip_match.py \\
        --video data/videos/IMG_7326.MOV \\
        --frame 40 \\
        --picked docs/phase4_homography/cam01_clip01_picked.csv \\
        --output outputs/clip_match.png

`--show`를 주면 창으로도 띄운다. 아무 키나 누르면 닫힌다.
"""

from __future__ import annotations

import argparse
import csv
import math
import sys
from pathlib import Path
from typing import List, Tuple

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from pick_calibration_points import PickerError, read_frame  # noqa: E402

MARKER_RADIUS = 14
MARKER_THICKNESS = 2
# fit은 초록, holdout은 파랑. BGR이다.
ROLE_COLORS = {"fit": (0, 220, 0), "holdout": (255, 160, 0)}
DEFAULT_COLOR = (0, 220, 220)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", required=True)
    parser.add_argument("--frame", type=int, default=0)
    parser.add_argument("--picked", required=True, help="pick_calibration_points.py가 만든 CSV")
    parser.add_argument("--output", required=True, help="겹쳐 그린 PNG 저장 경로")
    parser.add_argument("--show", action="store_true", help="창으로도 띄운다")
    return parser.parse_args()


def load_picked(path: Path) -> List[Tuple[str, str, float, float]]:
    if not path.is_file():
        raise PickerError(f"픽셀 CSV가 없습니다: {path}")
    rows: List[Tuple[str, str, float, float]] = []
    with open(path, "r", encoding="utf-8", newline="") as file:
        for number, row in enumerate(csv.DictReader(file), start=2):
            point_id = (row.get("point_id") or "").strip()
            if not point_id:
                continue
            try:
                x = float(row["pixel_x"])
                y = float(row["pixel_y"])
            except (KeyError, TypeError, ValueError) as exc:
                raise PickerError(f"{path} {number}행 픽셀 좌표를 읽을 수 없습니다.") from exc
            if not (math.isfinite(x) and math.isfinite(y)):
                raise PickerError(f"{path} {number}행 픽셀 좌표가 유한하지 않습니다.")
            rows.append((point_id, (row.get("role") or "").strip(), x, y))
    if not rows:
        raise PickerError(f"{path}에 기준점이 없습니다.")
    return rows


def draw(frame, rows) -> Tuple[int, int]:
    """기록된 위치에 표식을 그리고, 프레임 밖으로 나간 점 수를 센다."""
    height, width = frame.shape[:2]
    outside = 0
    for point_id, role, x, y in rows:
        if not (0 <= x < width and 0 <= y < height):
            outside += 1
            continue
        color = ROLE_COLORS.get(role, DEFAULT_COLOR)
        center = (int(round(x)), int(round(y)))
        cv2.circle(frame, center, MARKER_RADIUS, color, MARKER_THICKNESS)
        cv2.drawMarker(frame, center, color, cv2.MARKER_CROSS, MARKER_RADIUS, 1)
        cv2.putText(
            frame,
            point_id,
            (center[0] + MARKER_RADIUS + 4, center[1] - 4),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            color,
            2,
            cv2.LINE_AA,
        )
    return len(rows), outside


def main() -> None:
    args = parse_args()
    try:
        rows = load_picked(Path(args.picked))
        frame = read_frame(Path(args.video), args.frame)
    except PickerError as exc:
        raise SystemExit(str(exc)) from exc

    height, width = frame.shape[:2]
    total, outside = draw(frame, rows)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(output), frame):
        raise SystemExit(f"이미지를 저장하지 못했습니다: {output}")

    print(f"영상 {Path(args.video).name} #{args.frame}  {width}x{height}")
    print(f"기준점 {total}개 표시, 프레임 밖 {outside}개")
    print(f"저장: {output}")
    if outside:
        print("프레임 밖 점이 있습니다. 해상도가 다른 파일일 가능성이 큽니다.")
    print("표식이 빨간 테이프 위에 있으면 이 파일이 맞습니다. 빗나가면 다른 클립입니다.")

    if args.show:
        cv2.imshow("clip match", frame)
        cv2.waitKey(0)
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
