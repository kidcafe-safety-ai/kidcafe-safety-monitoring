"""KidCafe Safety AI - 메인 파이프라인."""

from __future__ import annotations

import argparse
import logging
import time
from typing import Optional

import cv2

from src.common.event_writer import EventWriter
from src.common.pipeline_logging import format_eta, setup_logging
from src.events.event_manager import EventManager
from src.geofencing.zone_checker import ZoneChecker
from src.geofencing.zone_loader import load_zones
from src.tracking.bytetrack_wrapper import ByteTracker
from src.visualization.video_overlay import VideoOverlayWriter


LOGGER = logging.getLogger(__name__)


def run_pipeline(
    video_path: str,
    zones_path: str,
    output_path: str = "outputs/events.jsonl",
    csv_output_path: str = "outputs/events.csv",
    summary_output_path: str = "outputs/summary.json",
    overlay_path: str = "outputs/result.mp4",
    frames_limit: Optional[int] = None,
    show: bool = False,
    conf: float = 0.5,
) -> None:
    """
    전체 파이프라인을 실행한다.

    A 역할 호환:
    - ByteTracker 유지
    - EventManager(zones=zones, fps=fps) 유지
    - ZoneChecker 유지
    - VideoOverlayWriter 유지
    - outputs/result.mp4 생성 흐름 유지

    B 역할 추가:
    - print 대신 logging 사용
    - 진행률 ETA 출력
    - outputs/events.jsonl 저장 유지
    - outputs/events.csv 저장 추가
    - outputs/summary.json 저장 추가

    C 역할 호환:
    - C는 events.jsonl, events.csv, summary.json, result.mp4를 그대로 사용 가능
    """
    cap = cv2.VideoCapture(video_path)

    if not cap.isOpened():
        raise RuntimeError(f"영상을 열 수 없습니다: {video_path}")

    overlay_writer = None

    frame_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    frame_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    if fps <= 0:
        LOGGER.warning("비정상 FPS 값이 감지되어 fps=30.0으로 대체합니다.")
        fps = 30.0

    if frames_limit is not None:
        target_frames = min(total_frames, frames_limit) if total_frames > 0 else frames_limit
    else:
        target_frames = total_frames

    LOGGER.info("Video: %s", video_path)
    LOGGER.info("Resolution: %sx%s, FPS: %.1f", frame_width, frame_height, fps)
    LOGGER.info("Total frames: %s", total_frames)
    LOGGER.info("Target frames: %s", target_frames)

    tracker = ByteTracker(conf=conf, fps=fps)
    zones = load_zones(zones_path)
    checker = ZoneChecker(zones, frame_width, frame_height)
    event_manager = EventManager(zones=zones, fps=fps)

    writer = EventWriter(
        output_path=output_path,
        csv_output_path=csv_output_path,
        summary_output_path=summary_output_path,
    )

    overlay_writer = VideoOverlayWriter(
        output_path=overlay_path,
        frame_width=frame_width,
        frame_height=frame_height,
        fps=fps,
    )

    LOGGER.info("Loaded %s zones", len(zones))
    LOGGER.info("JSONL Output: %s", output_path)
    LOGGER.info("CSV Output: %s", csv_output_path)
    LOGGER.info("Summary Output: %s", summary_output_path)
    LOGGER.info("Overlay Output: %s", overlay_path)

    frame_number = 0
    total_events = 0
    pipeline_start = time.time()

    try:
        while True:
            frame_start = time.time()

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

            # 화면에서 사라진 track 상태 정리 + EXIT 이벤트 발생
            active_ids = {track.track_id for track in result.tracks}

            stale_events = event_manager.flush_stale_tracks(
                active_track_ids=active_ids,
                frame_number=frame_number,
                video_source=video_path,
            )

            frame_events.extend(stale_events)

            # 3. Save events
            if frame_events:
                writer.write_batch(frame_events)
                total_events += len(frame_events)

                for event in frame_events:
                    LOGGER.info(
                        "[Frame %05d] %s | track_id=%s | zone=%s",
                        frame_number,
                        event.event_type,
                        event.track_id,
                        event.zone_id,
                    )

            # 4. Save overlay video frame
            overlay_writer.write_frame(
                frame=frame,
                tracks=result.tracks,
                zones=zones,
                events=frame_events,
            )

            # 5. Optional realtime display
            if show:
                _draw_overlay(frame, result.tracks, zones, frame_width, frame_height)
                cv2.imshow("KidCafe Safety AI", frame)

                if cv2.waitKey(1) & 0xFF == ord("q"):
                    LOGGER.warning("사용자 입력으로 파이프라인을 중단합니다.")
                    break

            processing_time = time.time() - frame_start
            processing_fps = 1.0 / processing_time if processing_time > 0 else 0.0

            if frame_number % 30 == 0:
                elapsed = time.time() - pipeline_start
                processed = frame_number + 1

                if processed > 0 and target_frames:
                    avg_time_per_frame = elapsed / processed
                    remaining_frames = max(target_frames - processed, 0)
                    eta_seconds = remaining_frames * avg_time_per_frame
                    progress = (processed / target_frames) * 100
                else:
                    eta_seconds = 0.0
                    progress = 0.0

                LOGGER.info(
                    "Progress %.1f%% | frame %s/%s | processing %.1f FPS | ETA %s",
                    progress,
                    processed,
                    target_frames,
                    processing_fps,
                    format_eta(eta_seconds),
                )

            frame_number += 1

            if frames_limit is not None and frame_number >= frames_limit:
                LOGGER.info("frames_limit=%s에 도달하여 처리를 종료합니다.", frames_limit)
                break

    finally:
        cap.release()

        if overlay_writer is not None:
            overlay_writer.close()

        if show:
            cv2.destroyAllWindows()

        writer.finalize(fps=fps)

    LOGGER.info("Processed %s frames, %s events", frame_number, total_events)
    LOGGER.info("Saved JSONL: %s", output_path)
    LOGGER.info("Saved CSV: %s", csv_output_path)
    LOGGER.info("Saved Summary: %s", summary_output_path)
    LOGGER.info("Saved Overlay: %s", overlay_path)


def _draw_overlay(frame, tracks, zones, frame_width, frame_height) -> None:
    """
    bbox + zone polygon 시각화.

    show=True일 때만 사용하는 간단한 실시간 확인용 overlay.
    결과 영상 저장은 A가 만든 VideoOverlayWriter가 담당한다.
    """
    for zone in zones:
        if zone.type != "polygon":
            continue

        points = [
            (int(x * frame_width), int(y * frame_height))
            for x, y in zone.points
        ]

        for index in range(len(points)):
            cv2.line(
                frame,
                points[index],
                points[(index + 1) % len(points)],
                (0, 0, 255),
                2,
            )

    for track in tracks:
        x1, y1, x2, y2 = map(int, track.bbox)

        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)

        cv2.putText(
            frame,
            f"ID {track.track_id}",
            (x1, y1 - 10),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (0, 255, 0),
            2,
        )


def main() -> None:
    """
    CLI entry point.
    """
    parser = argparse.ArgumentParser(description="KidCafe Safety AI Pipeline")

    parser.add_argument("--video", default="data/videos/test.mp4")
    parser.add_argument("--zones", default="data/zones/sample.json")
    parser.add_argument("--output", default="outputs/events.jsonl")

    parser.add_argument(
        "--csv-output",
        default="outputs/events.csv",
        help="CSV 이벤트 로그 출력 경로.",
    )

    parser.add_argument(
        "--summary-output",
        default="outputs/summary.json",
        help="대시보드 KPI summary JSON 출력 경로.",
    )

    parser.add_argument(
        "--frames-limit",
        type=int,
        default=None,
        help="처음 N프레임만 처리한다. 테스트용 옵션.",
    )

    parser.add_argument(
        "--show",
        action="store_true",
        help="실시간 시각화 창을 표시한다.",
    )

    parser.add_argument(
        "--overlay-output",
        default="outputs/result.mp4",
        help="결과 영상 mp4 출력 경로.",
    )

    parser.add_argument(
        "--conf",
        type=float,
        default=0.5,
        help="YOLO confidence threshold. 범위: 0~1.",
    )

    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="로그 레벨.",
    )

    args = parser.parse_args()

    setup_logging(args.log_level)

    LOGGER.info("=" * 50)
    LOGGER.info("KidCafe Safety AI v0.1.0")
    LOGGER.info("=" * 50)

    run_pipeline(
        video_path=args.video,
        zones_path=args.zones,
        output_path=args.output,
        csv_output_path=args.csv_output,
        summary_output_path=args.summary_output,
        frames_limit=args.frames_limit,
        overlay_path=args.overlay_output,
        conf=args.conf,
        show=args.show,
    )


if __name__ == "__main__":
    main()