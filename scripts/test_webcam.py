"""웹캠 실시간 파이프라인 측정 스크립트.

측정 항목:
  - 웹캠 해상도 / CAP_FPS
  - 처리 FPS (frame loop 기준)
  - 평균 frame latency (ms)
  - frame drop 여부
  - ENTER / DWELL / EXIT 이벤트 수

사용법:
  python scripts/test_webcam.py                                           # 기본 (camera-device=0, 90프레임)
  python scripts/test_webcam.py --frames 150                              # 더 많은 프레임
  python scripts/test_webcam.py --camera-device 1                        # 외부 카메라
  python scripts/test_webcam.py --camera-device 0 --infer-device cpu     # CPU 추론 비교
  python scripts/test_webcam.py --api-url http://localhost:8000           # API 전송 포함
"""

from __future__ import annotations

import argparse
import sys
import time
import statistics
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.input.webcam_source import WebcamSource
from src.tracking.bytetrack_wrapper import ByteTracker
from src.geofencing.zone_loader import load_zones
from src.geofencing.zone_checker import ZoneChecker
from src.events.event_manager import EventManager
from src.common.pipeline_logging import setup_logging
from src.common.types import CurrentStatus, CurrentZoneStatus
from src.integrations.event_api_client import EventApiClient


def run_webcam_test(
    camera_device: int = 0,
    zones_path: str = "data/zones/sample.json",
    model_path: str = "yolo26n.pt",
    frames: int = 90,
    api_url: str | None = None,
    conf: float = 0.4,
    width: int | None = None,
    height: int | None = None,
    infer_device: str = "auto",
) -> dict:
    source = WebcamSource(device=camera_device, width=width, height=height)
    source.open()

    print(f"\n{'='*50}")
    print(f"웹캠 테스트 시작")
    print(f"  camera_device: {camera_device}")
    print(f"  infer_device : {infer_device}")
    print(f"  해상도     : {source.width}x{source.height}")
    print(f"  CAP_FPS    : {source.fps}")
    print(f"  모델       : {model_path}")
    print(f"  측정 프레임: {frames}")
    print(f"  API URL    : {api_url or '없음 (로컬만)'}")
    print(f"{'='*50}\n")

    api_client = EventApiClient(api_url) if api_url else None

    zones = load_zones(zones_path)
    checker = ZoneChecker(zones, source.width, source.height)
    event_manager = EventManager(zones=zones, fps=source.fps)
    tracker = ByteTracker(model_path=model_path, conf=conf, fps=source.fps, device=infer_device)

    frame_times = []
    event_counts = {"ENTER": 0, "DWELL": 0, "EXIT": 0}
    dropped_frames = 0
    api_send_ok = 0
    api_send_fail = 0

    pipeline_start = time.time()

    try:
        for frame_number in range(frames):
            t0 = time.time()

            ret, frame = source.read()
            if not ret or frame is None:
                dropped_frames += 1
                print(f"[Frame {frame_number:04d}] WARNING: 프레임 읽기 실패")
                continue

            result = tracker.update(frame, frame_number, source.source_id)

            frame_events = []
            for track in result.tracks:
                zones_in = checker.check(track)
                events = event_manager.process(
                    track=track,
                    zones_in=zones_in,
                    frame_number=frame_number,
                    video_source=source.source_id,
                )
                frame_events.extend(events)

            active_ids = {t.track_id for t in result.tracks}
            stale = event_manager.flush_stale_tracks(active_ids, frame_number, source.source_id)
            frame_events.extend(stale)

            for ev in frame_events:
                event_counts[ev.event_type] = event_counts.get(ev.event_type, 0) + 1
                print(f"  [Event] {ev.event_type} | track_id={ev.track_id} | zone={ev.zone_id}")

            if api_client:
                for ev in frame_events:
                    ok = api_client.send_event(ev)
                    if ok:
                        api_send_ok += 1
                    else:
                        api_send_fail += 1

                if frame_number % 30 == 0:
                    zone_map = {z.zone_id: z.name for z in zones}
                    status = CurrentStatus(
                        source=source.source_id,
                        frame_number=frame_number,
                        active_track_count=len(result.tracks),
                        zone_occupancy=[
                            CurrentZoneStatus(
                                zone_id=k,
                                zone_name=zone_map.get(k, k),
                                current_count=v,
                                risk_level="HIGH" if v > 0 else "NORMAL",
                            )
                            for k, v in event_manager.get_zone_occupancy().items()
                        ],
                        updated_at=__import__("datetime").datetime.now(
                            __import__("datetime").timezone.utc
                        ).astimezone().isoformat(),
                    )
                    api_client.send_current_status(status.to_dict())

            elapsed_ms = (time.time() - t0) * 1000
            frame_times.append(elapsed_ms)

            if frame_number % 30 == 0:
                fps_now = 1000.0 / (sum(frame_times[-30:]) / min(len(frame_times), 30))
                print(f"[Frame {frame_number:04d}/{frames}] tracks={len(result.tracks)} | {fps_now:.1f} FPS | {elapsed_ms:.1f}ms")

    finally:
        source.release()
        if api_client:
            api_client.close()

    total_elapsed = time.time() - pipeline_start
    processed = len(frame_times)

    results = {
        "camera_device": camera_device,
        "infer_device": infer_device,
        "resolution": f"{source.width}x{source.height}",
        "cap_fps": source.fps,
        "model": model_path,
        "processed_frames": processed,
        "dropped_frames": dropped_frames,
        "total_elapsed_sec": round(total_elapsed, 2),
        "avg_fps": round(processed / total_elapsed, 2) if total_elapsed > 0 else 0,
        "avg_latency_ms": round(statistics.mean(frame_times), 1) if frame_times else 0,
        "p95_latency_ms": round(sorted(frame_times)[max(0, int(len(frame_times) * 0.95) - 1)], 1) if frame_times else 0,
        "max_latency_ms": round(max(frame_times), 1) if frame_times else 0,
        "events": event_counts,
        "api_send_ok": api_send_ok,
        "api_send_fail": api_send_fail,
    }

    print(f"\n{'='*50}")
    print("측정 결과")
    print(f"{'='*50}")
    for k, v in results.items():
        print(f"  {k:<22}: {v}")
    print(f"{'='*50}\n")

    return results


def main():
    parser = argparse.ArgumentParser(description="웹캠 실시간 파이프라인 측정")
    parser.add_argument("--camera-device", type=int, default=0, dest="camera_device")
    parser.add_argument("--frames", type=int, default=90)
    parser.add_argument("--model", default="yolo26n.pt")
    parser.add_argument("--zones", default="data/zones/sample.json")
    parser.add_argument("--conf", type=float, default=0.4)
    parser.add_argument("--api-url", default=None)
    parser.add_argument("--width", type=int, default=None, help="카메라 가로 해상도 요청 (예: 640)")
    parser.add_argument("--height", type=int, default=None, help="카메라 세로 해상도 요청 (예: 480)")
    parser.add_argument(
        "--infer-device",
        default="auto",
        choices=["auto", "mps", "cuda", "cpu"],
        dest="infer_device",
        help="추론 장치 (기본: auto)",
    )
    args = parser.parse_args()

    setup_logging("INFO")
    run_webcam_test(
        camera_device=args.camera_device,
        zones_path=args.zones,
        model_path=args.model,
        frames=args.frames,
        api_url=args.api_url,
        conf=args.conf,
        width=args.width,
        height=args.height,
        infer_device=args.infer_device,
    )


if __name__ == "__main__":
    main()
