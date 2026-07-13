"""
마우스로 zone 좌표를 직접 찍는 스크립트

Usage:
    .venv-benchmark/bin/python scripts/draw_zone.py \
        --video data/videos/test5.mp4 \
        --output data/zones/benchmark_test5.json \
        --zone-id doorway_area \
        --zone-name "문앞 구역"

조작:
    마우스 클릭  : 꼭짓점 추가
    Enter / q   : 완료 후 저장
    r           : 전체 초기화
    z           : 마지막 점 취소
"""

import argparse
import json
from pathlib import Path

import cv2
import numpy as np


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--video", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--zone-id", default="zone_01")
    p.add_argument("--zone-name", default="구역")
    p.add_argument(
        "--zone-type",
        default="danger",
        choices=["play", "exit", "restricted", "danger"],
        help="안전정책 분류 (Phase 3 필수 필드)",
    )
    p.add_argument("--dwell-sec", type=int, default=3)
    p.add_argument("--frame", type=int, default=0, help="기준으로 쓸 프레임 번호")
    return p.parse_args()


def main():
    args = parse_args()

    cap = cv2.VideoCapture(args.video)
    cap.set(cv2.CAP_PROP_POS_FRAMES, args.frame)
    ret, frame = cap.read()
    cap.release()

    if not ret:
        raise RuntimeError(f"영상을 읽을 수 없습니다: {args.video}")

    h, w = frame.shape[:2]
    points = []

    def draw(img):
        vis = img.copy()
        for i, (px, py) in enumerate(points):
            cv2.circle(vis, (px, py), 5, (0, 255, 0), -1)
            cv2.putText(vis, str(i + 1), (px + 6, py - 6),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
        if len(points) >= 2:
            cv2.polylines(vis, [np.array(points, dtype=np.int32)],
                          isClosed=len(points) >= 3, color=(0, 255, 0), thickness=2)
        cv2.putText(vis, f"클릭: 점 추가 | Enter/q: 저장 | z: 마지막 취소 | r: 초기화",
                    (10, h - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 0), 1)
        cv2.putText(vis, f"점 {len(points)}개", (10, 25),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
        return vis

    def on_mouse(event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN:
            points.append((x, y))
            cv2.imshow("draw_zone", draw(frame))

    cv2.namedWindow("draw_zone")
    cv2.setMouseCallback("draw_zone", on_mouse)
    cv2.imshow("draw_zone", draw(frame))

    while True:
        key = cv2.waitKey(20) & 0xFF
        if key in (13, ord('q')):  # Enter or q
            break
        elif key == ord('r'):
            points.clear()
            cv2.imshow("draw_zone", draw(frame))
        elif key == ord('z') and points:
            points.pop()
            cv2.imshow("draw_zone", draw(frame))

    cv2.destroyAllWindows()

    if len(points) < 3:
        print("점이 3개 미만입니다. 저장하지 않습니다.")
        return

    normalized = [[round(x / w, 4), round(y / h, 4)] for x, y in points]

    zone = [{
        "zone_id": args.zone_id,
        "name": args.zone_name,
        "type": "polygon",
        "zone_type": args.zone_type,
        "points": normalized,
        "rules": {
            "enter_alert": True,
            "dwell_threshold_sec": args.dwell_sec,
        },
    }]

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(zone, f, ensure_ascii=False, indent=2)

    print(f"\n저장 완료: {args.output}")
    print(f"좌표 (정규화): {normalized}")


if __name__ == "__main__":
    main()
