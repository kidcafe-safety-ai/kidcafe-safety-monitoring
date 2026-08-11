"""KidCafe Safety AI - 메인 파이프라인."""

from __future__ import annotations

import argparse
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import cv2

from src.common.event_writer import EventWriter
from src.common.pipeline_metrics import PipelineMetrics
from src.common.pipeline_logging import format_eta, setup_logging
from src.common.types import CurrentStatus, CurrentZoneStatus, Zone
from src.events.event_manager import EventManager
from src.geofencing.zone_checker import ZoneChecker
from src.geofencing.zone_loader import load_zones
from src.input.base import InputSource
from src.input.file_source import FileVideoSource
from src.input.rtsp_source import (
    DEFAULT_RTSP_HOST,
    DEFAULT_RTSP_MAIN_PATH,
    DEFAULT_RTSP_PORT,
    DEFAULT_RTSP_SUB_PATH,
    RTSPConnectionConfig,
    RTSPCredentialError,
    RTSPSource,
    describe_rtsp_log_context,
)
from src.input.webcam_source import WebcamSource
from src.integrations.async_event_dispatcher import AsyncEventDispatcher
from src.integrations.live_frame_client import LiveFrameClient
from src.integrations.live_frame_dispatcher import LiveFrameDispatcher
from src.safety.auxiliary_fall_model import AuxiliaryFallModel
from src.safety.fall_detector import FallDetectorConfig
from src.safety.fall_pipeline import FallPipeline
from src.safety.pose_normal_gate import PoseNormalGate, PoseNormalGateConfig
from src.tracking.bytetrack_wrapper import ByteTracker
from src.tracking.pose_tracker import PoseTracker
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
    fall_detection_enabled: bool = False,
    fall_config_path: str = "configs/fall_detection.json",
    fall_model_path: Optional[str] = None,
    fall_model_conf: float = 0.5,
    fall_model_device: str = "auto",
    fall_model_iou_threshold: float = 0.3,
    fall_model_interval_frames: int = 1,
    fall_pose_normal_gate_enabled: bool = False,
    metrics_output_path: Optional[str] = None,
    api_failed_events_output_path: str = "outputs/api_failed_events.jsonl",
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
        fall_detection_enabled=fall_detection_enabled,
        fall_config_path=fall_config_path,
        fall_model_path=fall_model_path,
        fall_model_conf=fall_model_conf,
        fall_model_device=fall_model_device,
        fall_model_iou_threshold=fall_model_iou_threshold,
        fall_model_interval_frames=fall_model_interval_frames,
        fall_pose_normal_gate_enabled=fall_pose_normal_gate_enabled,
        metrics_output_path=metrics_output_path,
        api_failed_events_output_path=api_failed_events_output_path,
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
    model_path: Optional[str] = None,
    device: str = "auto",
    live_frame_enabled: bool = False,
    live_frame_fps: float = 1.5,
    live_frame_quality: int = 75,
    fall_detection_enabled: bool = False,
    fall_config_path: str = "configs/fall_detection.json",
    fall_model_path: Optional[str] = None,
    fall_model_conf: float = 0.5,
    fall_model_device: str = "auto",
    fall_model_iou_threshold: float = 0.3,
    fall_model_interval_frames: int = 1,
    fall_pose_normal_gate_enabled: bool = False,
    metrics_output_path: Optional[str] = None,
    api_failed_events_output_path: str = "outputs/api_failed_events.jsonl",
) -> None:
    """모든 입력 소스 타입을 처리하는 파이프라인 코어.

    Args:
        source: FileVideoSource / WebcamSource / RTSPSource 중 하나.
        api_url: 지정 시 AsyncEventDispatcher를 통해 FastAPI로 이벤트/상태를
            비차단 전송한다. None이면 전송 안 함.
        model_path: 사람 탐지/추적 모델 경로. None이면 fall_detection_enabled에 맞는
            기본값을 쓴다(False: yolo26n.pt+ByteTracker, True: yolo26n-pose.pt+
            PoseTracker) — 낙상 감지를 껐을 때 불필요하게 더 무거운 pose 모델을
            쓰지 않기 위함이다.
        live_frame_enabled: 지정 시 FastAPI PUT /live/frame으로 최신 frame을 전송한다.
            api_url이 필요하며, Event/CurrentStatus 전송과는 별도로 켜고 끌 수 있다.
        fall_detection_enabled: FALL_SUSPECT 감지(FallPipeline)를 켤지 여부. 기본
            False — Subject 7~8 진단에서 오탐 목표를 충족하지 못했으므로
            (docs/fall_evaluation.md 참고) 명시적으로 켜야만 동작한다. 켜면
            tracker도 PoseTracker로 바뀐다 — pose confirm 경로가
            Track.keypoints를 필요로 하기 때문이다.
        fall_model_path: fine-tuned fall/nofall 보조 모델 경로. None이면 모델 없이
            bbox+pose 규칙 기반 경로만 사용한다 (scripts/evaluate_fall.py와 동일 정책).
        fall_model_interval_frames: 보조 모델 실행 간격. pose normal gate가 없으면
            고정 간격이고, pose normal gate가 있으면 fallback 구간의 최대 간격이다.
        fall_pose_normal_gate_enabled: 안정적인 직립 Pose에서만 RGB 보조 모델을
            건너뛰는 보수적 gate. 기본 False로 기존 경로를 유지한다.
        metrics_output_path: 지정 시 모델 초기화와 종료 flush를 제외한 frame-loop
            latency/FPS 지표를 JSON으로 저장한다. None이면 계측 파일을 만들지 않는다.
        api_failed_events_output_path: API 전송 최종 실패 Event를 기록할 JSONL 경로.
    """
    source.open()
    dispatcher: Optional[AsyncEventDispatcher] = None
    overlay_writer = None
    writer = None
    metrics = PipelineMetrics() if metrics_output_path is not None else None
    processed_frame_number = 0
    total_events = 0
    fps = source.fps
    try:
        if live_frame_enabled and not api_url:
            raise ValueError("--live-frame-enabled 사용 시 --api-url을 지정해야 합니다.")

        if api_url:
            live_frame_dispatcher: Optional[LiveFrameDispatcher] = None
            if live_frame_enabled:
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

            dispatcher = AsyncEventDispatcher(
                base_url=api_url,
                live_frame_dispatcher=live_frame_dispatcher,
                failed_events_path=api_failed_events_output_path,
            )
            LOGGER.info("API 비차단 전송 활성화: %s", api_url)

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

        if fall_detection_enabled:
            tracker_name = "PoseTracker"
            resolved_model_path = model_path or "yolo26n-pose.pt"
            tracker = PoseTracker(
                model_path=resolved_model_path, conf=conf, fps=fps, device=device
            )
        else:
            tracker_name = "ByteTracker"
            resolved_model_path = model_path or "yolo26n.pt"
            tracker = ByteTracker(
                model_path=resolved_model_path, conf=conf, fps=fps, device=device
            )
        zones = load_zones(zones_path)
        checker = ZoneChecker(zones, frame_width, frame_height)
        event_manager = EventManager(zones=zones, fps=fps)

        fall_pipeline: Optional[FallPipeline] = None
        if fall_detection_enabled:
            fall_detector_config = FallDetectorConfig.from_file(fall_config_path)
            auxiliary_model = None
            if fall_model_path:
                auxiliary_model = AuxiliaryFallModel(
                    model_path=fall_model_path,
                    conf=fall_model_conf,
                    device=fall_model_device,
                )
            pose_normal_gate = None
            if fall_pose_normal_gate_enabled:
                if auxiliary_model is None:
                    raise ValueError(
                        "--fall-pose-normal-gate-enabled 사용 시 --fall-model-path가 "
                        "필요합니다."
                    )
                pose_normal_gate = PoseNormalGate(
                    fps=fps,
                    config=PoseNormalGateConfig.from_fall_detector_config(
                        fall_detector_config
                    ),
                )
            fall_pipeline = FallPipeline(
                fps=fps,
                detector_config=fall_detector_config,
                auxiliary_model=auxiliary_model,
                iou_threshold=fall_model_iou_threshold,
                fall_config_path=fall_config_path,
                auxiliary_inference_interval_frames=fall_model_interval_frames,
                pose_normal_gate=pose_normal_gate,
            )
            LOGGER.info(
                "Fall Detection 활성화: config=%s, model=%s",
                fall_config_path,
                fall_model_path or "없음(bbox+pose 규칙 기반만 사용)",
            )
            if fall_pose_normal_gate_enabled:
                LOGGER.info(
                    "Pose NORMAL gate 활성화: auxiliary_interval=%d",
                    fall_model_interval_frames,
                )

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
        LOGGER.info("Tracker: %s, Model: %s", tracker_name, resolved_model_path)

        pipeline_start = time.perf_counter()
        _last_status_time = time.time()

        while True:
            frame_start = time.perf_counter()

            ret, frame = source.read()
            if not ret or frame is None:
                break

            # 1. Detection + Tracking
            #
            # RTSPSource는 지연 누적을 막기 위해 오래된 frame을 drop하고 최신
            # frame만 전달한다. 이때 처리 loop 횟수를 safety/event 시간축으로
            # 사용하면 dwell/fall/cause 규칙 시간이 실제 카메라 시간보다 느려진다.
            # 따라서 RTSP처럼 capture_sequence를 제공하는 source는 원본 캡처
            # frame_number를 사용하고, file/webcam은 기존 처리 frame_number를
            # 그대로 사용한다.
            source_frame_number = _resolve_source_frame_number(
                source,
                processed_frame_number,
            )
            result = tracker.update(frame, source_frame_number, source.source_id)

            # 2. Geofencing + Events
            frame_events = []
            for track in result.tracks:
                zones_in = checker.check(track)
                events = event_manager.process(
                    track=track,
                    zones_in=zones_in,
                    frame_number=source_frame_number,
                    video_source=source.source_id,
                )
                frame_events.extend(events)

            active_ids = {track.track_id for track in result.tracks}
            stale_events = event_manager.flush_stale_tracks(
                active_track_ids=active_ids,
                frame_number=source_frame_number,
                video_source=source.source_id,
            )
            frame_events.extend(stale_events)

            # 2-1. 낙상 감지 (옵션)
            if fall_pipeline is not None:
                frame_events.extend(fall_pipeline.process(frame, result))

            # 3. 로컬 저장
            if frame_events:
                writer.write_batch(frame_events)
                total_events += len(frame_events)
                for event in frame_events:
                    LOGGER.info(
                        "[Frame %05d] %s | track_id=%s | zone=%s",
                        source_frame_number,
                        event.event_type,
                        event.track_id,
                        event.zone_id,
                    )

            # 4. API 비차단 전송 (AsyncEventDispatcher가 큐 등록 후 즉시 반환)
            if dispatcher is not None:
                for event in frame_events:
                    dispatcher.enqueue_event(event)

                _now = time.time()
                if _now - _last_status_time >= _STATUS_UPDATE_INTERVAL_SEC:
                    status = _build_current_status(
                        source_id=source.source_id,
                        frame_number=source_frame_number,
                        active_track_count=len(result.tracks),
                        zone_occupancy=event_manager.get_zone_occupancy(),
                        zones=zones,
                    )
                    dispatcher.update_current_status(status)
                    _last_status_time = _now

                # 4-1. Live Frame 등록 (latest-only, worker가 비차단 전송)
                # Dashboard Live View는 관리자가 바로 추적 상태를 확인할 수 있도록
                # 원본 frame이 아니라 ID/box/zone overlay가 포함된 frame을 전송한다.
                if live_frame_enabled:
                    live_frame = frame.copy()
                    _draw_overlay(live_frame, result.tracks, zones, frame_width, frame_height)
                    dispatcher.update_live_frame(
                        live_frame,
                        source=source.source_id,
                        frame_number=source_frame_number,
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

            processing_time = time.perf_counter() - frame_start
            if metrics is not None:
                metrics.record(processing_time)
            processing_fps = 1.0 / processing_time if processing_time > 0 else 0.0

            if processed_frame_number % 30 == 0:
                elapsed = time.perf_counter() - pipeline_start
                processed = processed_frame_number + 1
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

            processed_frame_number += 1
            if frames_limit is not None and processed_frame_number >= frames_limit:
                LOGGER.info("frames_limit=%s에 도달해 처리를 종료합니다.", frames_limit)
                break

    finally:
        source.release()
        if overlay_writer is not None:
            overlay_writer.close()
        if show:
            cv2.destroyAllWindows()
        if dispatcher is not None:
            dispatcher.close(timeout=3.0)
        if writer is not None:
            writer.finalize(fps=fps)
        if metrics is not None and metrics_output_path is not None:
            metrics.write_json(metrics_output_path)

    LOGGER.info("Processed %s frames, %s events", processed_frame_number, total_events)


def _resolve_source_frame_number(
    source: InputSource,
    processed_frame_number: int,
) -> int:
    """안전 규칙에 사용할 입력 source 기준 frame_number를 반환한다.

    FileVideoSource/WebcamSource는 read()마다 순차 처리되므로 처리 loop 번호가
    source frame_number와 같다. RTSPSource는 최신 프레임 유지를 위해 처리되지
    않은 오래된 프레임을 버릴 수 있으므로, read()로 전달된 frame의 원본 캡처
    sequence를 우선 사용한다.
    """

    metadata_getter = getattr(source, "get_last_frame_metadata", None)
    if not callable(metadata_getter):
        return processed_frame_number

    metadata = metadata_getter()
    capture_sequence = getattr(metadata, "capture_sequence", None)
    if (
        isinstance(capture_sequence, int)
        and not isinstance(capture_sequence, bool)
        and capture_sequence > 0
    ):
        # RTSP capture_sequence는 1부터 증가한다. 기존 Event frame_number 계약은
        # 0-based이므로 첫 번째 캡처 프레임은 frame_number=0으로 변환한다.
        return capture_sequence - 1

    return processed_frame_number


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
    """Live View와 show=True 미리보기에서 사용하는 간단한 실시간 확인용 overlay."""
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
        help="소스 경로 또는 ID. webcam: 카메라 인덱스(0), rtsp: 카메라 IP/host, file: 파일 경로.",
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
    parser.add_argument(
        "--metrics-output",
        default=None,
        help="frame-loop FPS/latency JSON 경로. 미지정 시 생성하지 않는다.",
    )

    # 모델
    parser.add_argument(
        "--model",
        default=None,
        help="사람 탐지/추적 YOLO 모델 경로. 미지정 시 --fall-detection-enabled 여부에 "
        "따라 자동 선택된다(끄면 yolo26n.pt+ByteTracker, 켜면 yolo26n-pose.pt+PoseTracker).",
    )

    # 낙상 감지 (FALL_SUSPECT)
    parser.add_argument(
        "--fall-detection-enabled",
        action="store_true",
        help="FallPipeline 기반 FALL_SUSPECT 감지를 켠다. 기본 비활성화 — "
        "Subject 7~8 진단에서 오탐 목표를 미충족(자세한 내용은 "
        "docs/fall_evaluation.md 참고).",
    )
    parser.add_argument(
        "--fall-config",
        default="configs/fall_detection.json",
        help="FallDetectorConfig JSON 경로.",
    )
    parser.add_argument(
        "--fall-model-path",
        default=None,
        help="fine-tuned fall/nofall 보조 모델 경로. 미지정 시 bbox+pose 규칙 기반만 사용.",
    )
    parser.add_argument("--fall-model-conf", type=float, default=0.5)
    parser.add_argument(
        "--fall-model-device",
        default="auto",
        choices=["auto", "mps", "cuda", "cpu"],
    )
    parser.add_argument("--fall-model-iou-threshold", type=float, default=0.3)
    parser.add_argument(
        "--fall-model-interval-frames",
        type=int,
        default=1,
        help="보조 fall/nofall 모델 실행 간격(frame). 1이면 매 frame 실행.",
    )
    parser.add_argument(
        "--fall-pose-normal-gate-enabled",
        action="store_true",
        help="안정적인 직립 Pose에서 RGB 보조 모델 추론을 생략한다. 기본 비활성화.",
    )

    # API 연동
    parser.add_argument(
        "--api-url",
        default=None,
        help="FastAPI 서버 URL. 지정 시 이벤트/상태를 전송한다. 예: http://localhost:8000",
    )
    parser.add_argument(
        "--api-failed-events-output",
        default="outputs/api_failed_events.jsonl",
        help="API 최종 전송 실패 Event JSONL 경로.",
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
    parser.add_argument(
        "--rtsp-host",
        default=DEFAULT_RTSP_HOST,
        help="RTSP 카메라 IP/host. --source-type rtsp에서 --source 미지정 시 사용.",
    )
    parser.add_argument(
        "--rtsp-port",
        type=int,
        default=DEFAULT_RTSP_PORT,
        help="RTSP 포트.",
    )
    parser.add_argument(
        "--rtsp-stream",
        choices=["main", "sub"],
        default="main",
        help="RTSP 스트림 선택. main=/media/video1, sub=/media/video2.",
    )
    parser.add_argument(
        "--rtsp-path",
        default=None,
        help="RTSP stream path 직접 지정. 지정하면 --rtsp-stream보다 우선한다.",
    )
    parser.add_argument(
        "--rtsp-username-env",
        default="KIDCAFE_RTSP_USERNAME",
        help="RTSP 사용자 이름을 읽을 환경변수 이름. 미설정 시 admin fallback.",
    )
    parser.add_argument(
        "--rtsp-password-env",
        default="KIDCAFE_RTSP_PASSWORD",
        help="RTSP 비밀번호를 읽을 환경변수 이름.",
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
    LOGGER.info("KidCafe Safety AI v0.3.0")
    LOGGER.info("=" * 50)

    try:
        source = _build_source(args)
    except (RTSPCredentialError, ValueError) as exc:
        LOGGER.error("%s", exc)
        raise SystemExit(2) from None

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
        fall_detection_enabled=args.fall_detection_enabled,
        fall_config_path=args.fall_config,
        fall_model_path=args.fall_model_path,
        fall_model_conf=args.fall_model_conf,
        fall_model_device=args.fall_model_device,
        fall_model_iou_threshold=args.fall_model_iou_threshold,
        fall_model_interval_frames=args.fall_model_interval_frames,
        fall_pose_normal_gate_enabled=args.fall_pose_normal_gate_enabled,
        metrics_output_path=args.metrics_output,
        api_failed_events_output_path=args.api_failed_events_output,
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
        rtsp_path = (
            args.rtsp_path
            if args.rtsp_path
            else DEFAULT_RTSP_MAIN_PATH
            if args.rtsp_stream == "main"
            else DEFAULT_RTSP_SUB_PATH
        )

        # 하위 호환: 이미 조립된 RTSP URL을 넘긴 경우도 동작은 유지한다.
        # 다만 새 권장 방식은 인증정보를 환경변수에서 읽어 내부 조립하는 것이다.
        if args.source and str(args.source).startswith("rtsp://"):
            host, port, path, username_set, password_set = describe_rtsp_log_context(
                args.source
            )
            LOGGER.info(
                "RTSP 입력 선택: camera_ip=%s, port=%s, path=%s, "
                "username_set=%s, password_set=%s, alias=%s",
                host,
                port or "기본",
                path,
                username_set,
                password_set,
                args.rtsp_alias or "없음",
            )
            return RTSPSource(url=args.source, alias=args.rtsp_alias)

        rtsp_host = args.source if args.source else args.rtsp_host
        LOGGER.info(
            "RTSP 입력 선택: camera_ip=%s, path=%s, alias=%s",
            rtsp_host,
            rtsp_path,
            args.rtsp_alias or "없음",
        )
        return RTSPSource.from_env(
            RTSPConnectionConfig(
                host=rtsp_host,
                port=args.rtsp_port,
                path=rtsp_path,
                alias=args.rtsp_alias,
            ),
            username_env=args.rtsp_username_env,
            password_env=args.rtsp_password_env,
        )

    # file (default)
    path = args.source if args.source else args.video
    LOGGER.info("파일 영상 입력 선택: %s", path)
    return FileVideoSource(path=path)


if __name__ == "__main__":
    main()
