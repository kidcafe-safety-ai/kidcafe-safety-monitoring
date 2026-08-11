"""RTSP 입력 소스.

OpenCV FFmpeg backend를 이용해 IP 카메라 RTSP 스트림을 TCP 방식으로 읽는다.
카메라 인증정보는 URL 조립 시 내부에서만 사용하고, 로그·source_id에는 노출하지 않는다.
자동 재연결은 이번 단계 범위가 아니므로 구현하지 않는다.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from typing import Optional, Tuple
from urllib.parse import quote, urlsplit

import cv2
import numpy as np

from src.input.base import InputSource

LOGGER = logging.getLogger(__name__)

RTSP_USERNAME_ENV = "KIDCAFE_RTSP_USERNAME"
RTSP_PASSWORD_ENV = "KIDCAFE_RTSP_PASSWORD"
DEFAULT_RTSP_USERNAME = "admin"
DEFAULT_RTSP_PORT = 554
DEFAULT_RTSP_HOST = "192.168.0.4"
DEFAULT_RTSP_MAIN_PATH = "/media/video1"
DEFAULT_RTSP_SUB_PATH = "/media/video2"

_RTSP_FPS_FALLBACK = 25.0
_OPENCV_FFMPEG_CAPTURE_OPTIONS = "rtsp_transport;tcp|stimeout;5000000"
_RTSP_READ_WAIT_SEC = 0.05
_RTSP_STALE_TIMEOUT_SEC = 3.0
_RTSP_MAX_CONSECUTIVE_READ_FAILURES = 30
_RTSP_RELEASE_JOIN_TIMEOUT_SEC = 2.0


class RTSPCredentialError(RuntimeError):
    """RTSP 인증정보 환경변수가 누락되었을 때 발생하는 오류."""


@dataclass(frozen=True)
class RTSPConnectionConfig:
    """RTSP URL 조립에 필요한 비밀값 없는 연결 설정."""

    host: str = DEFAULT_RTSP_HOST
    port: int = DEFAULT_RTSP_PORT
    path: str = DEFAULT_RTSP_MAIN_PATH
    username: str = DEFAULT_RTSP_USERNAME
    alias: Optional[str] = None


@dataclass(frozen=True)
class RTSPSourceStats:
    """RTSP 최신 프레임 수신/전달 통계."""

    captured_frames: int
    delivered_frames: int
    dropped_frames: int
    read_failures: int
    consecutive_read_failures: int
    last_frame_received_at: Optional[float]
    runtime_seconds: float
    delivered_fps: float


@dataclass(frozen=True)
class RTSPFrameMetadata:
    """파이프라인에 전달된 RTSP 프레임의 원본 시간축 메타데이터."""

    capture_sequence: int
    captured_monotonic: float
    source_elapsed_seconds: float


def normalize_rtsp_path(path: str) -> str:
    """RTSP path가 항상 '/'로 시작하도록 정규화한다."""

    stripped = path.strip()
    if not stripped:
        raise ValueError("RTSP stream path가 비어 있습니다.")
    return stripped if stripped.startswith("/") else f"/{stripped}"


def normalize_rtsp_env_value(value: str) -> str:
    """PowerShell env 설정 중 섞이기 쉬운 바깥 공백/따옴표를 정리한다.

    내부 특수문자와 공백은 그대로 유지하고, 외부에서 감싼 값만 보정한다.
    """

    normalized = value.strip()
    if len(normalized) >= 2 and normalized[0] == normalized[-1] and normalized[0] in {
        "'",
        '"',
    }:
        normalized = normalized[1:-1].strip()
    return normalized


def build_rtsp_url(
    *,
    host: str,
    username: str,
    password: str,
    port: int = DEFAULT_RTSP_PORT,
    path: str = DEFAULT_RTSP_MAIN_PATH,
) -> str:
    """RTSP URL을 조립한다.

    username/password/path는 URL 인코딩한다. 반환값은 비밀값을 포함하므로
    호출자는 이 값을 로그에 출력하면 안 된다.
    """

    if not password:
        raise RTSPCredentialError(
            f"RTSP password environment variable({RTSP_PASSWORD_ENV}) is required."
        )

    encoded_username = quote(username, safe="")
    encoded_password = quote(password, safe="")
    encoded_path = quote(normalize_rtsp_path(path), safe="/")
    credentials = f"{encoded_username}:{encoded_password}"
    return f"rtsp://{credentials}@{host}:{port}{encoded_path}"


def read_rtsp_credentials_from_env(
    *,
    username_env: str = RTSP_USERNAME_ENV,
    password_env: str = RTSP_PASSWORD_ENV,
    default_username: str = DEFAULT_RTSP_USERNAME,
) -> Tuple[str, str]:
    """RTSP 계정 정보를 환경변수에서 읽는다.

    username은 없으면 admin으로 fallback한다. password는 반드시 환경변수에
    있어야 하며, 누락 시 명확한 오류를 발생시킨다.
    """

    username = normalize_rtsp_env_value(
        os.getenv(username_env, default_username)
    ) or default_username
    raw_password = os.getenv(password_env)

    if raw_password is None:
        raise RTSPCredentialError(
            f"{password_env} 환경변수가 설정되어 있지 않습니다. "
            "카메라 비밀번호, IP, 네트워크 연결, 카메라 상태를 확인하세요."
        )

    password = normalize_rtsp_env_value(raw_password)
    if not password:
        raise RTSPCredentialError(
            f"{password_env} 환경변수가 비어 있습니다. "
            "카메라 비밀번호, IP, 네트워크 연결, 카메라 상태를 확인하세요."
        )

    return username, password


def build_rtsp_url_from_env(
    config: RTSPConnectionConfig,
    *,
    username_env: str = RTSP_USERNAME_ENV,
    password_env: str = RTSP_PASSWORD_ENV,
) -> str:
    """환경변수 인증정보를 사용해 RTSP URL을 조립한다."""

    username, password = read_rtsp_credentials_from_env(
        username_env=username_env,
        password_env=password_env,
        default_username=config.username,
    )
    return build_rtsp_url(
        host=config.host,
        username=username,
        password=password,
        port=config.port,
        path=config.path,
    )


def sanitize_rtsp_url(url: str) -> str:
    """로그용 RTSP URL에서 사용자 이름과 비밀번호를 제거한다."""

    parsed = urlsplit(url)
    if parsed.scheme != "rtsp":
        return url

    host = parsed.hostname or "unknown-host"
    port = f":{parsed.port}" if parsed.port is not None else ""
    credentials = "***:***@" if parsed.username or parsed.password else ""
    return f"rtsp://{credentials}{host}{port}{parsed.path or ''}"


def describe_rtsp_url(url: str) -> tuple[str, str]:
    """비밀값 없이 RTSP URL의 host/path만 반환한다."""

    parsed = urlsplit(url)
    host = parsed.hostname or "unknown-host"
    path = parsed.path or ""
    return host, path


def describe_rtsp_port(url: str) -> Optional[int]:
    """비밀값 없이 RTSP URL의 port만 반환한다."""

    return urlsplit(url).port


def describe_rtsp_log_context(url: str) -> tuple[str, Optional[int], str, bool, bool]:
    """로그에 안전하게 남길 RTSP 연결 정보만 반환한다."""

    parsed = urlsplit(url)
    host = parsed.hostname or "unknown-host"
    path = parsed.path or ""
    return host, parsed.port, path, bool(parsed.username), bool(parsed.password)


def make_safe_source_id(url: str, alias: Optional[str] = None) -> str:
    """이벤트/로그에 사용해도 되는 source_id를 만든다."""

    if alias:
        return alias
    host, path = describe_rtsp_url(url)
    return f"rtsp:{host}{path}"


def configure_rtsp_tcp_transport() -> None:
    """OpenCV FFmpeg backend가 RTSP TCP transport를 쓰도록 설정한다."""

    os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = _OPENCV_FFMPEG_CAPTURE_OPTIONS


class RTSPSource(InputSource):
    """RTSP/IP 카메라에서 실시간 프레임을 읽는 소스.

    CAP_FFMPEG 백엔드를 사용한다. 카메라 수신은 백그라운드 스레드가 담당하고,
    파이프라인 read()는 아직 전달하지 않은 최신 프레임 1장만 가져간다.
    처리 FPS가 카메라 FPS보다 낮으면 오래된 프레임은 dropped_frames로 집계하고
    덮어쓴다. 자동 재연결은 구현하지 않는다.
    """

    def __init__(
        self,
        url: str,
        alias: Optional[str] = None,
        *,
        read_wait_sec: float = _RTSP_READ_WAIT_SEC,
        stale_timeout_sec: float = _RTSP_STALE_TIMEOUT_SEC,
        max_consecutive_read_failures: int = _RTSP_MAX_CONSECUTIVE_READ_FAILURES,
    ) -> None:
        self._url = url
        self._alias = alias
        self._source_id = make_safe_source_id(url, alias)
        (
            self._host,
            self._port,
            self._path,
            self._username_set,
            self._password_set,
        ) = describe_rtsp_log_context(url)
        self._cap: Optional[cv2.VideoCapture] = None
        self._fps: float = _RTSP_FPS_FALLBACK
        self._width: int = 0
        self._height: int = 0
        self._connection_seconds: float = 0.0
        self._read_wait_sec = read_wait_sec
        self._stale_timeout_sec = stale_timeout_sec
        self._max_consecutive_read_failures = max_consecutive_read_failures

        self._condition = threading.Condition()
        self._stop_event = threading.Event()
        self._reader_thread: Optional[threading.Thread] = None
        self._latest_frame: Optional[np.ndarray] = None
        self._latest_frame_metadata: Optional[RTSPFrameMetadata] = None
        self._last_delivered_metadata: Optional[RTSPFrameMetadata] = None
        self._latest_frame_seq: int = 0
        self._delivered_frame_seq: int = 0
        self._terminal: bool = False
        self._terminal_reason: Optional[str] = None
        self._summary_logged: bool = False

        self._captured_frames: int = 0
        self._delivered_frames: int = 0
        self._dropped_frames: int = 0
        self._read_failures: int = 0
        self._consecutive_read_failures: int = 0
        self._started_monotonic: Optional[float] = None
        self._last_frame_monotonic: Optional[float] = None
        self._last_frame_received_at: Optional[float] = None

    @classmethod
    def from_env(
        cls,
        config: RTSPConnectionConfig,
        *,
        username_env: str = RTSP_USERNAME_ENV,
        password_env: str = RTSP_PASSWORD_ENV,
    ) -> "RTSPSource":
        """환경변수 인증정보를 사용해 RTSPSource를 생성한다."""

        url = build_rtsp_url_from_env(
            config,
            username_env=username_env,
            password_env=password_env,
        )
        return cls(url=url, alias=config.alias)

    def open(self) -> None:
        configure_rtsp_tcp_transport()
        self._reset_runtime_state()
        LOGGER.info(
            "RTSP 입력 연결 시도: 입력 유형=RTSP, camera_ip=%s, port=%s, path=%s",
            self._host,
            self._port or "기본",
            self._path,
        )
        LOGGER.info(
            "RTSP 안전 진단: username_set=%s, password_set=%s, ffmpeg_options=%s, "
            "requested_backend=CAP_FFMPEG",
            self._username_set,
            self._password_set,
            _OPENCV_FFMPEG_CAPTURE_OPTIONS,
        )

        started_at = time.perf_counter()
        self._cap = cv2.VideoCapture(self._url, cv2.CAP_FFMPEG)
        self._connection_seconds = time.perf_counter() - started_at
        if self._cap is not None:
            self._cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        if not self._cap.isOpened():
            LOGGER.error("RTSP 안전 진단 결과: isOpened=False")
            if self._cap is not None:
                self._cap.release()
                self._cap = None
            raise RuntimeError(
                "RTSP 스트림을 열 수 없습니다. "
                "카메라 비밀번호, IP, 네트워크 연결, 카메라 상태를 확인하세요. "
                f"camera_ip={self._host}, path={self._path}"
            )
        LOGGER.info("RTSP 안전 진단 결과: isOpened=True")

        self._width = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self._height = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        raw_fps = self._cap.get(cv2.CAP_PROP_FPS)
        self._fps = raw_fps if raw_fps > 0 else _RTSP_FPS_FALLBACK
        actual_backend = self._get_backend_name()

        LOGGER.info(
            "RTSP 연결 성공: 입력 유형=RTSP, camera_ip=%s, 연결 소요 시간=%.3f초, "
            "수신 해상도=%dx%d, 카메라 FPS=%.2f, actual_backend=%s",
            self._host,
            self._connection_seconds,
            self._width,
            self._height,
            self._fps,
            actual_backend,
        )

        self._started_monotonic = time.perf_counter()
        self._reader_thread = threading.Thread(
            target=self._capture_loop,
            name=f"RTSPSourceReader-{self._source_id}",
            daemon=True,
        )
        self._reader_thread.start()

    def read(self) -> Tuple[bool, Optional[np.ndarray]]:
        if self._cap is None or self._reader_thread is None:
            return False, None

        with self._condition:
            while True:
                if (
                    self._latest_frame is not None
                    and self._latest_frame_seq > self._delivered_frame_seq
                ):
                    frame = self._latest_frame
                    metadata = self._latest_frame_metadata
                    self._delivered_frame_seq = self._latest_frame_seq
                    self._last_delivered_metadata = metadata
                    self._delivered_frames += 1
                    return True, frame

                if self._terminal or self._stop_event.is_set():
                    return False, None

                if self._is_stale_locked(time.perf_counter()):
                    self._mark_terminal_locked(
                        f"{self._stale_timeout_sec:.1f}초 동안 새 RTSP 프레임 없음"
                    )
                    LOGGER.error(
                        "RTSP 스트림 종료 판단: %s (camera_ip=%s, path=%s)",
                        self._terminal_reason,
                        self._host,
                        self._path,
                    )
                    return False, None

                self._condition.wait(timeout=self._read_wait_sec)

    def release(self) -> None:
        self._stop_event.set()
        with self._condition:
            self._condition.notify_all()

        thread = self._reader_thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=_RTSP_RELEASE_JOIN_TIMEOUT_SEC)

        if thread is not None and thread.is_alive():
            LOGGER.warning(
                "RTSP 수신 스레드가 즉시 종료되지 않아 VideoCapture release로 해제를 보조합니다. "
                "camera_ip=%s, path=%s",
                self._host,
                self._path,
            )

        if self._cap is not None:
            self._cap.release()
            self._cap = None
            LOGGER.info("RTSP 소스 해제: camera_ip=%s, path=%s", self._host, self._path)

        if thread is not None and thread.is_alive():
            thread.join(timeout=1.0)

        self._reader_thread = None
        self._log_summary_once()

    def get_stats(self) -> RTSPSourceStats:
        """현재 RTSP 수신/전달 통계를 반환한다."""

        with self._condition:
            return self._build_stats_locked(time.perf_counter())

    def get_last_frame_metadata(self) -> Optional[RTSPFrameMetadata]:
        """가장 최근 read()로 파이프라인에 전달한 프레임의 원본 메타데이터."""

        with self._condition:
            return self._last_delivered_metadata

    def _reset_runtime_state(self) -> None:
        with self._condition:
            self._stop_event.clear()
            self._latest_frame = None
            self._latest_frame_metadata = None
            self._last_delivered_metadata = None
            self._latest_frame_seq = 0
            self._delivered_frame_seq = 0
            self._terminal = False
            self._terminal_reason = None
            self._summary_logged = False
            self._captured_frames = 0
            self._delivered_frames = 0
            self._dropped_frames = 0
            self._read_failures = 0
            self._consecutive_read_failures = 0
            self._started_monotonic = None
            self._last_frame_monotonic = None
            self._last_frame_received_at = None

    def _capture_loop(self) -> None:
        while not self._stop_event.is_set():
            cap = self._cap
            if cap is None:
                break

            try:
                ret, frame = cap.read()
            except Exception as exc:  # OpenCV backend 예외는 수신 스레드에서 안전하게 종료한다.
                self._record_capture_exception(exc)
                break

            now = time.perf_counter()

            if ret and frame is not None:
                self._store_latest_frame(frame, now)
                continue

            should_stop = self._record_read_failure(now)
            if should_stop:
                break
            time.sleep(min(self._read_wait_sec, 0.02))

    def _record_capture_exception(self, exc: Exception) -> None:
        exception_type = type(exc).__name__
        with self._condition:
            self._read_failures += 1
            self._consecutive_read_failures += 1
            self._mark_terminal_locked(f"RTSP 프레임 수신 예외: {exception_type}")
            self._condition.notify_all()

        LOGGER.error(
            "RTSP 프레임 수신 예외로 스트림을 종료합니다: exception_type=%s, "
            "camera_ip=%s, path=%s",
            exception_type,
            self._host,
            self._path,
        )

    def _store_latest_frame(self, frame: np.ndarray, captured_monotonic: float) -> None:
        dropped_frames_to_log: Optional[int] = None
        with self._condition:
            if (
                self._latest_frame is not None
                and self._latest_frame_seq > self._delivered_frame_seq
            ):
                self._dropped_frames += 1
                if self._dropped_frames == 1 or self._dropped_frames % 100 == 0:
                    dropped_frames_to_log = self._dropped_frames

            self._latest_frame = frame
            self._latest_frame_seq += 1
            source_elapsed_seconds = (
                captured_monotonic - self._started_monotonic
                if self._started_monotonic is not None
                else 0.0
            )
            self._latest_frame_metadata = RTSPFrameMetadata(
                capture_sequence=self._latest_frame_seq,
                captured_monotonic=captured_monotonic,
                source_elapsed_seconds=max(source_elapsed_seconds, 0.0),
            )
            self._captured_frames += 1
            self._consecutive_read_failures = 0
            self._last_frame_monotonic = captured_monotonic
            self._last_frame_received_at = time.time()
            self._condition.notify_all()

        if dropped_frames_to_log is not None:
            LOGGER.info(
                "RTSP 최신 프레임 유지 중: dropped_frames=%d "
                "(오류가 아니라 오래된 프레임을 버려 실시간성을 유지한 결과입니다.)",
                dropped_frames_to_log,
            )

    def _record_read_failure(self, failure_monotonic: float) -> bool:
        with self._condition:
            self._read_failures += 1
            self._consecutive_read_failures += 1
            consecutive = self._consecutive_read_failures

            if consecutive == 1:
                LOGGER.warning(
                    "RTSP 프레임 읽기 일시 실패: retrying (camera_ip=%s, path=%s)",
                    self._host,
                    self._path,
                )

            if consecutive >= self._max_consecutive_read_failures:
                self._mark_terminal_locked(
                    f"RTSP 프레임 연속 {consecutive}회 읽기 실패"
                )
                LOGGER.error(
                    "RTSP 스트림 종료 판단: %s (camera_ip=%s, path=%s)",
                    self._terminal_reason,
                    self._host,
                    self._path,
                )
                self._condition.notify_all()
                return True

            if self._is_stale_locked(failure_monotonic):
                self._mark_terminal_locked(
                    f"{self._stale_timeout_sec:.1f}초 동안 새 RTSP 프레임 없음"
                )
                LOGGER.error(
                    "RTSP 스트림 종료 판단: %s (camera_ip=%s, path=%s)",
                    self._terminal_reason,
                    self._host,
                    self._path,
                )
                self._condition.notify_all()
                return True

            self._condition.notify_all()
            return False

    def _is_stale_locked(self, now: float) -> bool:
        last_activity = self._last_frame_monotonic or self._started_monotonic
        return (
            last_activity is not None
            and now - last_activity >= self._stale_timeout_sec
        )

    def _mark_terminal_locked(self, reason: str) -> None:
        self._terminal = True
        self._terminal_reason = reason

    def _build_stats_locked(self, now: float) -> RTSPSourceStats:
        runtime_seconds = (
            now - self._started_monotonic if self._started_monotonic is not None else 0.0
        )
        delivered_fps = (
            self._delivered_frames / runtime_seconds if runtime_seconds > 0 else 0.0
        )
        return RTSPSourceStats(
            captured_frames=self._captured_frames,
            delivered_frames=self._delivered_frames,
            dropped_frames=self._dropped_frames,
            read_failures=self._read_failures,
            consecutive_read_failures=self._consecutive_read_failures,
            last_frame_received_at=self._last_frame_received_at,
            runtime_seconds=runtime_seconds,
            delivered_fps=delivered_fps,
        )

    def _log_summary_once(self) -> None:
        with self._condition:
            if self._summary_logged:
                return
            self._summary_logged = True
            stats = self._build_stats_locked(time.perf_counter())

        LOGGER.info(
            "RTSP 수신 통계: captured_frames=%d, delivered_frames=%d, "
            "dropped_frames=%d, read_failures=%d, runtime=%.2f초, delivered_fps=%.2f",
            stats.captured_frames,
            stats.delivered_frames,
            stats.dropped_frames,
            stats.read_failures,
            stats.runtime_seconds,
            stats.delivered_fps,
        )

    def _get_backend_name(self) -> str:
        if self._cap is None or not hasattr(self._cap, "getBackendName"):
            return "unknown"
        try:
            return str(self._cap.getBackendName())
        except cv2.error:
            return "unknown"
        except AttributeError:
            return "unknown"

    @property
    def fps(self) -> float:
        return self._fps

    @property
    def width(self) -> int:
        return self._width

    @property
    def height(self) -> int:
        return self._height

    @property
    def source_id(self) -> str:
        return self._source_id
