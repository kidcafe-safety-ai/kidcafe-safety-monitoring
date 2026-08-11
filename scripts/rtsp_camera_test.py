"""IP 카메라 RTSP 수신 검증용 독립 실행 스크립트.

이 스크립트는 기존 탐지·추적·이벤트 파이프라인을 거치지 않고,
OpenCV + FFmpeg로 RTSP 스트림을 직접 열어 수신 가능 여부와 FPS를 확인한다.

사용 예:
  python scripts/rtsp_camera_test.py
  python scripts/rtsp_camera_test.py --stream sub
  python scripts/rtsp_camera_test.py --path /media/video2

주의:
  - 카메라 비밀번호는 실행 중 getpass()로 입력받으며 화면에 표시하지 않는다.
  - RTSP URL 전체나 비밀번호는 터미널에 출력하지 않는다.
  - 영상/이미지 파일을 자동 저장하지 않는다.
"""

from __future__ import annotations

import argparse
import getpass
import os
import time
from collections import deque
from dataclasses import dataclass
from typing import Deque
from urllib.parse import quote

import cv2


DEFAULT_HOST = "192.168.0.4"
DEFAULT_USERNAME = "admin"
DEFAULT_PORT = 554
MAIN_STREAM_PATH = "/media/video1"
SUB_STREAM_PATH = "/media/video2"
WINDOW_NAME = "RTSP Camera Test - press q to quit"
MAX_CONSECUTIVE_READ_FAILURES = 30
MOVING_FPS_WINDOW = 30


@dataclass(frozen=True)
class CameraConfig:
    """RTSP 접속에 필요한 카메라 설정."""

    host: str
    username: str
    port: int
    path: str


@dataclass
class RuntimeStats:
    """프레임 수신 중 누적되는 측정값."""

    total_frames: int = 0
    read_failures: int = 0
    consecutive_failures: int = 0
    first_frame_time: float | None = None
    last_frame_time: float | None = None

    def mark_frame(self, timestamp: float) -> None:
        self.total_frames += 1
        self.consecutive_failures = 0
        self.last_frame_time = timestamp
        if self.first_frame_time is None:
            self.first_frame_time = timestamp

    def mark_failure(self) -> None:
        self.read_failures += 1
        self.consecutive_failures += 1

    def average_fps(self) -> float:
        if (
            self.first_frame_time is None
            or self.last_frame_time is None
            or self.total_frames <= 1
        ):
            return 0.0

        elapsed = self.last_frame_time - self.first_frame_time
        return self.total_frames / elapsed if elapsed > 0 else 0.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="OpenCV + FFmpeg 기반 RTSP IP 카메라 수신 테스트",
    )
    parser.add_argument("--host", default=DEFAULT_HOST, help="카메라 IP 주소")
    parser.add_argument("--username", default=DEFAULT_USERNAME, help="RTSP 사용자 이름")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="RTSP 포트")
    parser.add_argument(
        "--stream",
        choices=("main", "sub"),
        default="main",
        help="기본 스트림 선택. main=/media/video1, sub=/media/video2",
    )
    parser.add_argument(
        "--path",
        default=None,
        help="RTSP stream path 직접 지정. 지정하면 --stream보다 우선한다.",
    )
    parser.add_argument(
        "--window-name",
        default=WINDOW_NAME,
        help="OpenCV 영상 창 이름",
    )
    return parser.parse_args()


def resolve_stream_path(stream: str, explicit_path: str | None) -> str:
    if explicit_path:
        return explicit_path if explicit_path.startswith("/") else f"/{explicit_path}"

    return MAIN_STREAM_PATH if stream == "main" else SUB_STREAM_PATH


def build_rtsp_url(config: CameraConfig, password: str) -> str:
    """특수문자가 포함된 계정 정보도 안전하게 URL에 넣는다."""

    encoded_username = quote(config.username, safe="")
    encoded_password = quote(password, safe="")
    encoded_path = quote(config.path, safe="/")
    return (
        f"rtsp://{encoded_username}:{encoded_password}"
        f"@{config.host}:{config.port}{encoded_path}"
    )


def configure_opencv_ffmpeg() -> None:
    """OpenCV FFmpeg backend가 RTSP TCP transport를 사용하도록 설정한다."""

    # OpenCV는 FFmpeg 옵션을 환경 변수로 읽는다.
    # stimeout 단위는 microsecond이며, 연결 불가 상황에서 무한 대기를 줄인다.
    os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = (
        "rtsp_transport;tcp|stimeout;5000000"
    )


def open_capture(rtsp_url: str) -> tuple[cv2.VideoCapture, float]:
    open_started_at = time.perf_counter()
    capture = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG)
    connection_seconds = time.perf_counter() - open_started_at

    return capture, connection_seconds


def get_capture_resolution(
    capture: cv2.VideoCapture,
    frame_width: int | None = None,
    frame_height: int | None = None,
) -> tuple[int, int]:
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)

    if (width <= 0 or height <= 0) and frame_width is not None and frame_height is not None:
        return frame_width, frame_height

    return width, height


def get_capture_fps(capture: cv2.VideoCapture) -> float:
    fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
    return fps if fps > 0 else 0.0


def calculate_moving_fps(frame_timestamps: Deque[float]) -> float:
    if len(frame_timestamps) < 2:
        return 0.0

    elapsed = frame_timestamps[-1] - frame_timestamps[0]
    return (len(frame_timestamps) - 1) / elapsed if elapsed > 0 else 0.0


def draw_overlay(frame, moving_fps: float, stats: RuntimeStats):
    """프레임 위에 현재 측정 FPS와 수신 프레임 수를 표시한다."""

    overlay_text = (
        f"Measured FPS: {moving_fps:.1f} | "
        f"Frames: {stats.total_frames} | "
        f"Read failures: {stats.read_failures}"
    )
    cv2.putText(
        frame,
        overlay_text,
        (18, 34),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.75,
        (0, 255, 0),
        2,
        cv2.LINE_AA,
    )
    return frame


def print_connection_summary(
    config: CameraConfig,
    connection_seconds: float,
    capture: cv2.VideoCapture,
) -> None:
    width, height = get_capture_resolution(capture)
    camera_fps = get_capture_fps(capture)

    print("\n[INFO] RTSP 연결 성공")
    print(f"[INFO] Host: {config.host}")
    print(f"[INFO] Port: {config.port}")
    print(f"[INFO] Stream path: {config.path}")
    print("[INFO] Transport: RTSP over TCP")
    print(f"[INFO] RTSP 연결 소요 시간: {connection_seconds:.3f}초")
    print(f"[INFO] 영상 해상도: {width}x{height}" if width and height else "[INFO] 영상 해상도: 확인 전")
    if camera_fps:
        print(f"[INFO] 카메라 FPS 정보: {camera_fps:.2f}")
    else:
        print("[INFO] 카메라 FPS 정보: 확인 불가")
    print("[INFO] q 키 또는 Ctrl+C로 종료할 수 있습니다.\n")


def print_final_summary(
    capture: cv2.VideoCapture,
    stats: RuntimeStats,
    last_frame_shape: tuple[int, int] | None,
    connection_seconds: float,
) -> None:
    frame_width = last_frame_shape[0] if last_frame_shape else None
    frame_height = last_frame_shape[1] if last_frame_shape else None
    width, height = get_capture_resolution(capture, frame_width, frame_height)
    camera_fps = get_capture_fps(capture)

    print("\n[RESULT] RTSP 수신 테스트 종료")
    print(f"[RESULT] RTSP 연결 소요 시간: {connection_seconds:.3f}초")
    if width and height:
        print(f"[RESULT] 영상 해상도: {width}x{height}")
    else:
        print("[RESULT] 영상 해상도: 확인 불가")

    if camera_fps:
        print(f"[RESULT] 카메라가 전달하는 FPS 정보: {camera_fps:.2f}")
    else:
        print("[RESULT] 카메라가 전달하는 FPS 정보: 확인 불가")
    print(f"[RESULT] 실제 측정 평균 FPS: {stats.average_fps():.2f}")
    print(f"[RESULT] 수신한 전체 프레임 수: {stats.total_frames}")
    print(f"[RESULT] 프레임 읽기 실패 횟수: {stats.read_failures}")


def run_rtsp_test(config: CameraConfig, password: str, window_name: str) -> int:
    configure_opencv_ffmpeg()
    rtsp_url = build_rtsp_url(config, password)
    capture, connection_seconds = open_capture(rtsp_url)
    stats = RuntimeStats()
    frame_timestamps: Deque[float] = deque(maxlen=MOVING_FPS_WINDOW)
    last_frame_shape: tuple[int, int] | None = None

    if not capture.isOpened():
        print("[ERROR] RTSP 스트림을 열 수 없습니다.")
        print("[ERROR] IP/포트/계정/비밀번호/스트림 경로와 카메라 Wi-Fi 연결 상태를 확인하세요.")
        capture.release()
        return 1

    print_connection_summary(config, connection_seconds, capture)

    try:
        while True:
            ok, frame = capture.read()

            if not ok or frame is None:
                stats.mark_failure()
                print(
                    "[WARN] 프레임 읽기 실패 "
                    f"({stats.consecutive_failures}/{MAX_CONSECUTIVE_READ_FAILURES})"
                )

                if stats.consecutive_failures >= MAX_CONSECUTIVE_READ_FAILURES:
                    print(
                        "[ERROR] 프레임을 연속으로 30회 읽지 못해 테스트를 종료합니다."
                    )
                    return 2

                continue

            now = time.perf_counter()
            stats.mark_frame(now)
            frame_timestamps.append(now)
            last_frame_shape = (frame.shape[1], frame.shape[0])

            moving_fps = calculate_moving_fps(frame_timestamps)
            display_frame = draw_overlay(frame.copy(), moving_fps, stats)
            cv2.imshow(window_name, display_frame)

            if cv2.waitKey(1) & 0xFF == ord("q"):
                print("[INFO] q 키 입력으로 종료합니다.")
                return 0

    except KeyboardInterrupt:
        print("\n[INFO] Ctrl+C 입력으로 종료합니다.")
        return 0
    finally:
        print_final_summary(capture, stats, last_frame_shape, connection_seconds)
        capture.release()
        cv2.destroyAllWindows()


def main() -> int:
    args = parse_args()
    stream_path = resolve_stream_path(args.stream, args.path)
    config = CameraConfig(
        host=args.host,
        username=args.username,
        port=args.port,
        path=stream_path,
    )

    print("[INFO] KidCafe RTSP camera receive test")
    print("[INFO] RTSP URL과 비밀번호는 로그에 출력하지 않습니다.")
    password = getpass.getpass("카메라 RTSP 비밀번호를 입력하세요: ")

    if not password:
        print("[ERROR] 비밀번호가 비어 있습니다.")
        return 1

    return run_rtsp_test(config, password, args.window_name)


if __name__ == "__main__":
    raise SystemExit(main())
