"""KidCafe Safety AI - 메인 파이프라인."""

import argparse

import cv2

from src.common.event_writer import EventWriter
from src.events.event_manager import EventManager
from src.geofencing.zone_checker import ZoneChecker
from src.geofencing.zone_loader import load_zones
from src.tracking.bytetrack_wrapper import ByteTracker


def run_pipeline(
    video_path: str,
    zones_path: str,
    output_path: str = "outputs/events.jsonl",
    frames_limit: int = None,
    show: bool = False,
):
    """전체 파이프라인 실행."""
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"영상을 열 수 없습니다: {video_path}")

    frame_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    frame_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    print(f"[INFO] Video: {video_path}")
    print(f"[INFO] Resolution: {frame_width}x{frame_height}, FPS: {fps:.1f}")
    print(f"[INFO] Total frames: {total_frames}")

    # 컴포넌트 초기화
    tracker = ByteTracker(conf=0.5)
    zones = load_zones(zones_path)
    checker = ZoneChecker(zones, frame_width, frame_height)
    event_manager = EventManager()
    writer = EventWriter(output_path)

    print(f"[INFO] Loaded {len(zones)} zones")
    print(f"[INFO] Output: {output_path}")
    print("-" * 50)

    frame_number = 0
    total_events = 0
    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break

            # 1. Detection + Tracking
            result = tracker.update(frame, frame_number, video_path)

            # 2. Geofencing + Events
            frame_events = []
            for track in result.tracks:
                zones_in = checker.check(track)
                events = event_manager.process(
                    track=track,
                    zones_in=zones_in,
                    frame_number=frame_number,
                    video_source=video_path,
                )
                frame_events.extend(events)

            # 3. Save
            if frame_events:
                writer.write_batch(frame_events)
                total_events += len(frame_events)
                for ev in frame_events:
                    print(
                        f"[Frame {frame_number:5d}] {ev.event_type} "
                        f"| track_id={ev.track_id} | zone={ev.zone_id}"
                    )

            # 4. (선택) 시각화
            if show:
                _draw_overlay(frame, result.tracks, zones, frame_width, frame_height)
                cv2.imshow("KidCafe Safety AI", frame)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break

            if frame_number % 30 == 0:
                print(
                    f"  ... processing frame {frame_number}/{total_frames}",
                    end="\r",
                )

            frame_number += 1
            if frames_limit is not None and frame_number >= frames_limit:
                break
    finally:
        cap.release()
        if show:
            cv2.destroyAllWindows()

    print("-" * 50)
    print(f"[DONE] Processed {frame_number} frames, {total_events} events")


def _draw_overlay(frame, tracks, zones, fw, fh):
    """bbox + zone polygon 시각화."""
    # Zone polygon (빨강)
    for z in zones:
        if z.type != "polygon":
            continue
        pts = [(int(x * fw), int(y * fh)) for x, y in z.points]
        for i in range(len(pts)):
            cv2.line(frame, pts[i], pts[(i + 1) % len(pts)], (0, 0, 255), 2)

    # Track bbox + ID (초록)
    for t in tracks:
        x1, y1, x2, y2 = map(int, t.bbox)
        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
        cv2.putText(
            frame,
            f"ID {t.track_id}",
            (x1, y1 - 10),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (0, 255, 0),
            2,
        )


def main():
    parser = argparse.ArgumentParser(description="KidCafe Safety AI Pipeline")
    parser.add_argument("--video", default="data/videos/test.mp4")
    parser.add_argument("--zones", default="data/zones/sample.json")
    parser.add_argument("--output", default="outputs/events.jsonl")
    parser.add_argument(
        "--frames-limit",
        type=int,
        default=None,
        help="처음 N프레임만 처리 (테스트용)",
    )
    parser.add_argument(
        "--show",
        action="store_true",
        help="실시간 시각화 창 표시 (cv2.imshow)",
    )
    args = parser.parse_args()

    print("=" * 50)
    print("KidCafe Safety AI v0.1.0 (Walking Skeleton)")
    print("=" * 50)

    run_pipeline(
        video_path=args.video,
        zones_path=args.zones,
        output_path=args.output,
        frames_limit=args.frames_limit,
        show=args.show,
    )


if __name__ == "__main__":
    main()