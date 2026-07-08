"""KidCafe Safety AI - 메인 파이프라인."""

from __future__ import annotations

import argparse
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import cv2

from src.common.event_writer import EventWriter
from src.common.pipeline_logging import format_eta, setup_logging
from src.common.types import CurrentStatus, CurrentZoneStatus, Zone
from src.events.event_manager import EventManager
from src.geofencing.zone_checker import ZoneChecker
from src.geofencing.zone_loader import load_zones
from src.input.base import InputSource
from src.input.file_source import FileVideoSource
from src.input.rtsp_source import RTSPSource
from src.input.webcam_source import WebcamSource
from src.integrations.event_api_client import EventApiClient
from src.integrations.live_frame_client import LiveFrameClient
from src.integrations.live_frame_dispatcher import LiveFrameDispatcher
from src.tracking.bytetrack_wrapper import ByteTracker
from src.visualization.video_overlay import VideoOverlayWriter


LOGGER = logging.getLogger(__name__)

_STATUS_UPDATE_INTERVAL_SEC = 2.0


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
    api_url: Optional[str] = None,
) -> None:
    """파일 영상 기반 파이프라인 (기존 인터페이스 유지).

    내부적으로 FileVideoSource를 생성해 run_pipeline_from_source를 호출한다.
    """
    source = FileVideoSource(video_path)
    run_pipeline_from_source(
        source=source,
        zones_path=zones_path,
        output_path=output_path,
        csv_output_path=csv_output_path,
        summary_output_path=summary_output_path,
        overlay_path=overlay_path,
        frames_limit=frames_limit,
        show=show,
        conf=conf,
        api_url=api_url,
    )


def run_pipeline_from_source(
    source: InputSource,
    zones_path: str,
    output_path: str = "outputs/events.jsonl",
    csv_output_path: str = "outputs/events.csv",
    summary_output_path: str = "outputs/summary.json",
    overlay_path: str = "outputs/result.mp4",
    frames_limit: Optional[int] = None,
    show: bool = False,
    conf: float = 0.5,
    api_url: Optional[str] = None,
    model_path: str = "yolo26n.pt",
    device: str = "auto",
    live_frame_enabled: bool = False,
    live_frame_fps: float = 1.5,
    live_frame_quality: int = 75,
) -> None:
    """모든 입력 소스 타입을 처리하는 파이프라인 코어.

    Args:
        source: FileVideoSource / WebcamSource / RTSPSource 중 하나.
        api_url: 지정 시 FastAPI로 이벤트/상태를 전송한다. None이면 전송 안 함.
        live_frame_enabled: 지정 시 FastAPI PUT /live/frame으로 최신 frame을 전송한다.
            Event/CurrentStatus 전송(api_client)과는 별도로 켜고 끌 수 있다.
    """
    source.open()
    api_client: Optional[EventApiClient] = None
    live_frame_dispatcher: Optional[LiveFrameDispatcher] = None
    overlay_writer = None
    writer = None
    fps = source.fps
    try:
        if api_url:
            api_client = EventApiClient(base_url=api_url)
            LOGGER.info("API 전송 활성화: %s", api_url)

        if live_frame_enabled:
            if not api_url:
                raise ValueError("--live-frame-enabled 사용 시 --api-url을 지정해야 합니다.")
            min_interval_sec = 1.0 / live_frame_fps if live_frame_fps > 0 else 0.5
            live_frame_client = LiveFrameClient(
                base_url=api_url,
                quality=live_frame_quality,
                min_interval_sec=min_interval_sec,
            )
            live_frame_dispatcher = LiveFrameDispatcher(client=live_frame_client)
            LOGGER.info(
                "Live Frame 전송 활성화 (latest-only worker): %s (fps=%.1f, quality=%d)",
                api_url,
                live_frame_fps,
                live_frame_quality,
            )

        frame_width = source.width
        frame_height = source.height
        total_frames = source.total_frames

        LOGGER.info("Source: %s", source.source_id)
        LOGGER.info("Resolution: %sx%s, FPS: %.1f", frame_width, frame_height, fps)
        LOGGER.info("Total frames: %s", total_frames if total_frames else "unknown (live)")

        if frames_limit is not None:
            target_frames = (
                min(total_frames, frames_limit) if total_frames else frames_limit
            )
        else:
            target_frames = total_frames

        tracker = ByteTracker(model_path=model_path, conf=conf, fps=fps, device=device)
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
        LOGGER.info("Model: %s", model_path)

        frame_number = 0
        total_events = 0
        pipeline_start = time.time()
        _last_status_time = pipeline_start

        while True:
            frame_start = time.time()

            ret, frame = source.read()
            if not ret or frame is None:
                break

            # 1. Detection + Tracking
            result = tracker.update(frame, frame_number, source.source_id)

            # 2. Geofencing + Events
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

            active_ids = {track.track_id for track in result.tracks}
            stale_events = event_manager.flush_stale_tracks(
                active_track_ids=active_ids,
                frame_number=frame_number,
                video_source=source.source_id,
            )
            frame_events.extend(stale_events)

            # 3. 로컬 저장
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

            # 4. API 전송
            if api_client is not None:
                for event in frame_events:
                    api_client.send_event(event)

                _now = time.time()
                if _now - _last_status_time >= _STATUS_UPDATE_INTERVAL_SEC:
                    status = _build_current_status(
                        source_id=source.source_id,
                        frame_number=frame_number,
                        active_track_count=len(result.tracks),
                        zone_occupancy=event_manager.get_zone_occupancy(),
                        zones=zones,
                    )
                    api_client.send_current_status(status)
                    _last_status_time = _now

            # 4-1. Live Frame 등록 (latest-only, worker가 비차단 전송)
            if live_frame_dispatcher is not None:
                live_frame_dispatcher.update_frame(
                    frame,
                    source=source.source_id,
                    frame_number=frame_number,
                    captured_at=_utc_now_iso_z(),
                )

            # 5. 결과 영상 저장
            overlay_writer.write_frame(
                frame=frame,
                tracks=result.tracks,
                zones=zones,
                events=frame_events,
            )

            # 6. 실시간 미리보기 (옵션)
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
                    avg_time = elapsed / processed
                    eta_seconds = max(target_frames - processed, 0) * avg_time
                    progress = (processed / target_frames) * 100
                else:
                    eta_seconds = 0.0
                    progress = 0.0

                LOGGER.info(
                    "Progress %.1f%% | frame %s/%s | %.1f FPS | ETA %s",
                    progress,
                    processed,
                    target_frames if target_frames else "?",
                    processing_fps,
                    format_eta(eta_seconds) if target_frames else "-",
                )

            frame_number += 1
            if frames_limit is not None and frame_number >= frames_limit:
                LOGGER.info("frames_limit=%s에 도달해 처리를 종료합니다.", frames_limit)
                break

    finally:
        source.release()
        if overlay_writer is not None:
            overlay_writer.close()
        if show:
            cv2.destroyAllWindows()
        if api_client is not None:
            api_client.close()
        if live_frame_dispatcher is not None:
            live_frame_dispatcher.close()
        if writer is not None:
            writer.finalize(fps=fps)

    LOGGER.info("Processed %s frames, %s events", frame_number, total_events)


def _utc_now_iso_z() -> str:
    """UTC 현재 시각을 'Z' suffix ISO 8601 문자열로 반환한다.

    datetime.isoformat()은 기본적으로 '+00:00'을 붙이는데,
    docs/api_contract.md의 captured_at 예시는 'Z' 형식(2026-07-07T12:00:00Z)이므로
    B가 별도 파싱 분기 없이 바로 사용할 수 있도록 여기서 정규화한다.
    """
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _build_current_status(
    source_id: str,
    frame_number: int,
    active_track_count: int,
    zone_occupancy: Dict[str, int],
    zones: List[Zone],
) -> Dict[str, Any]:
    """PUT /status/current 페이로드를 생성한다."""
    zone_map = {z.zone_id: z.name for z in zones}
    status = CurrentStatus(
        source=source_id,
        frame_number=frame_number,
        active_track_count=active_track_count,
        zone_occupancy=[
            CurrentZoneStatus(
                zone_id=zone_id,
                zone_name=zone_map.get(zone_id, zone_id),
                current_count=count,
                risk_level="HIGH" if count > 0 else "NORMAL",
            )
            for zone_id, count in zone_occupancy.items()
        ],
        updated_at=datetime.now(timezone.utc).astimezone().isoformat(),
    )
    return status.to_dict()


def _draw_overlay(frame, tracks, zones, frame_width, frame_height) -> None:
    """show=True일 때만 사용하는 간단한 실시간 확인용 overlay."""
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
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="KidCafe Safety AI Pipeline")

    # 입력 소스
    parser.add_argument(
        "--source-type",
        choices=["file", "webcam", "rtsp"],
        default="file",
        help="입력 소스 종류. file=파일 영상, webcam=웹캠, rtsp=RTSP 스트림.",
    )
    parser.add_argument(
        "--source",
        default=None,
        help="소스 경로 또는 ID. webcam: 카메라 인덱스(0), rtsp: URL, file: 파일 경로.",
    )
    parser.add_argument(
        "--video",
        default="data/videos/test.mp4",
        help="[레거시] 파일 영상 경로. --source-type file 일 때 --source 미지정 시 사용.",
    )

    # 출력
    parser.add_argument("--output", default="outputs/events.jsonl")
    parser.add_argument("--csv-output", default="outputs/events.csv")
    parser.add_argument("--summary-output", default="outputs/summary.json")
    parser.add_argument("--overlay-output", default="outputs/result.mp4")

    # 모델
    parser.add_argument(
        "--model",
        default="yolo26n.pt",
        help="YOLO 모델 경로. 기본값: yolo26n.pt",
    )

    # API 연동
    parser.add_argument(
        "--api-url",
        default=None,
        help="FastAPI 서버 URL. 지정 시 이벤트/상태를 전송한다. 예: http://localhost:8000",
    )
    parser.add_argument(
        "--live-frame-enabled",
        action="store_true",
        help="PUT /live/frame으로 최신 frame을 전송한다. --api-url 지정 필요.",
    )
    parser.add_argument(
        "--live-frame-fps",
        type=float,
        default=1.5,
        help="Live Frame 업로드 주기 (FPS). 기본값 1.5 (1~2 FPS 범위).",
    )
    parser.add_argument(
        "--live-frame-quality",
        type=int,
        default=75,
        help="Live Frame JPEG quality (0~100). 기본값 75 (권장 70~80).",
    )

    # Zone
    parser.add_argument(
        "--zones",
        default="data/zones/sample.json",
        help="Zone 정의 JSON 파일 경로.",
    )

    # 추론 장치
    parser.add_argument(
        "--infer-device",
        default="auto",
        choices=["auto", "mps", "cuda", "cpu"],
        help="YOLO 추론 장치. auto=자동 선택.",
    )

    # 해상도 (webcam 전용)
    parser.add_argument("--width", type=int, default=None, help="웹캠 가로 해상도 요청.")
    parser.add_argument("--height", type=int, default=None, help="웹캠 세로 해상도 요청.")

    # RTSP alias (계정/비밀번호 포함 URL이 로그/이벤트에 노출되지 않도록)
    parser.add_argument(
        "--rtsp-alias",
        default=None,
        help="RTSP source_id 별칭. 지정 시 URL 대신 이 값이 이벤트/로그에 기록된다. 예: camera_01",
    )

    # 기타
    parser.add_argument("--frames-limit", type=int, default=None)
    parser.add_argument("--show", action="store_true")
    parser.add_argument("--conf", type=float, default=0.5)
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )

    args = parser.parse_args()
    setup_logging(args.log_level)

    LOGGER.info("=" * 50)
    LOGGER.info("KidCafe Safety AI v0.2.5")
    LOGGER.info("=" * 50)

    source = _build_source(args)

    run_pipeline_from_source(
        source=source,
        zones_path=args.zones,
        output_path=args.output,
        csv_output_path=args.csv_output,
        summary_output_path=args.summary_output,
        overlay_path=args.overlay_output,
        frames_limit=args.frames_limit,
        show=args.show,
        conf=args.conf,
        api_url=args.api_url,
        model_path=args.model,
        device=args.infer_device,
        live_frame_enabled=args.live_frame_enabled,
        live_frame_fps=args.live_frame_fps,
        live_frame_quality=args.live_frame_quality,
    )


def _build_source(args) -> InputSource:
    """CLI 인자로부터 적절한 InputSource를 생성한다."""
    if args.source_type == "webcam":
        try:
            device = int(args.source) if args.source is not None else 0
        except ValueError:
            raise ValueError(
                f"--source-type webcam 사용 시 --source는 정수여야 합니다. 받은 값: {args.source!r}"
            )
        LOGGER.info("웹캠 입력 선택: device=%d", device)
        return WebcamSource(device=device, width=args.width, height=args.height)

    if args.source_type == "rtsp":
        if not args.source:
            raise ValueError("--source-type rtsp 사용 시 --source URL을 지정해야 합니다.")
        LOGGER.info("RTSP 입력 선택: %s (alias=%s)", args.source, args.rtsp_alias or "없음")
        return RTSPSource(url=args.source, alias=args.rtsp_alias)

    # file (default)
    path = args.source if args.source else args.video
    LOGGER.info("파일 영상 입력 선택: %s", path)
    return FileVideoSource(path=path)


if __name__ == "__main__":
    main()
