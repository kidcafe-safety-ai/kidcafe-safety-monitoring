"""Phase 4 촬영 영상에서 Zone 진입·이탈 interval을 영상으로 검수한다.

한 번의 실행은 영상 하나만 다룬다. 기본 검수 화면에는 기존 image polygon이나
Homography 판정 결과를 표시하지 않는다. 검수자는 원본 영상의 회색 테이프와
두 발 사이 바닥 중심을 보고 독립 ground truth를 만든다. 합의가 필요한 경계만 별도
adjudication에서 `--show-zone-reference`로 참고선을 표시할 수 있다.

키:
    Space       재생/일시정지
    , / .       이전/다음 frame
    A / D       10 frame 이전/다음
    E / X       enter / exit frame 지정
    1 / 2       enter / exit frame 삭제
    M           같은 영상에 새 interval 추가(진입·이탈이 여러 번일 때)
    V / Enter   현재 interval 승인(review_status=reviewed)
    U           needs_review로 표시
    N / P       다음/이전 interval (같은 영상에 2개 이상일 때)
    Q           저장 후 종료
    Tab         다음 interval 대체 키
    Backspace   이전 interval 대체 키
    Esc         저장 후 종료 대체 키

`enter_frame`은 두 발 사이 바닥 중심이 회색 테이프 안으로 들어온 첫 frame,
`exit_frame`은 밖으로 나온 첫 frame이다. 가림 등으로 경계가 불명확하면
승인하지 말고 U로 needs_review를 남긴다.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

import phase4_recording_contract as contract  # noqa: E402


_DISPLAY_MAX_WIDTH = 1280
_FRAME_CACHE_JPEG_QUALITY = 82
_ZONE_COLOR = (220, 220, 0)
_SETTABLE_FIELDS = ("enter_frame", "exit_frame", "dwell_start_frame")
DEFAULT_DWELL_THRESHOLD_SEC = 5.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--intervals", required=True)
    parser.add_argument("--video-id", required=True)
    parser.add_argument("--image-zone", help="adjudication 참고용 image Zone JSON")
    parser.add_argument(
        "--show-zone-reference",
        action="store_true",
        help="독립 1차 검수에서는 사용하지 않고 경계 합의 때만 참고선을 표시한다",
    )
    parser.add_argument("--repo-root", default=".")
    parser.add_argument(
        "--include-reviewed",
        action="store_true",
        help="이미 reviewed인 interval도 다시 연다",
    )
    return parser.parse_args()


def _load_zone_polygons(path: Path) -> dict[str, list[tuple[float, float]]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"image Zone JSON을 읽을 수 없습니다: {path}") from exc
    polygons: dict[str, list[tuple[float, float]]] = {}
    for zone in data:
        zone_id = zone.get("zone_id")
        points = zone.get("points") or []
        if zone_id and len(points) >= 3:
            polygons[zone_id] = [(float(x), float(y)) for x, y in points]
    if not polygons:
        raise ValueError(f"{path}에 유효한 zone polygon이 없습니다.")
    return polygons


class ReviewSession:
    def __init__(
        self,
        *,
        manifest_path: Path,
        intervals_path: Path,
        repo_root: Path,
        video_id: str,
        image_zone_path: Optional[Path] = None,
        show_zone_reference: bool = False,
        include_reviewed: bool = False,
    ) -> None:
        self.manifest_path = manifest_path
        self.intervals_path = intervals_path
        self.repo_root = repo_root.resolve()
        self.manifest_rows = contract.load_recordings_manifest(manifest_path)
        self.manifest_by_video = {row["video_id"]: row for row in self.manifest_rows}
        if video_id not in self.manifest_by_video:
            raise ValueError(f"manifest에 없는 video_id입니다: {video_id}")
        self.all_rows = contract.load_zone_intervals(intervals_path, self.manifest_rows)

        eligible = [row for row in self.all_rows if row["video_id"] == video_id]
        if not include_reviewed:
            eligible = [row for row in eligible if row["review_status"] != "reviewed"]
        if not eligible:
            raise ValueError(
                f"{video_id}: 검수할 interval이 없습니다 "
                f"(include_reviewed={include_reviewed})."
            )

        if show_zone_reference and image_zone_path is None:
            raise ValueError("--show-zone-reference에는 --image-zone이 필요합니다.")
        self._zone_polygons: dict[str, list[tuple[float, float]]] = {}
        if show_zone_reference and image_zone_path is not None:
            self._zone_polygons = _load_zone_polygons(image_zone_path)
            missing_zones = sorted(
                {row["zone_id"] for row in eligible} - set(self._zone_polygons)
            )
            if missing_zones:
                raise ValueError(f"{image_zone_path}에 없는 zone_id: {missing_zones}")

        self.rows = eligible
        self.index = 0
        self._capture: Optional[cv2.VideoCapture] = None
        self._last_frame_index = -1
        self._last_frame = None
        self._frame_cache: dict[int, np.ndarray] = {}

    @property
    def current(self) -> dict[str, str]:
        return self.rows[self.index]

    @property
    def current_manifest(self) -> dict[str, str]:
        return self.manifest_by_video[self.current["video_id"]]

    def frame_count(self) -> int:
        return int(self.current_manifest["frame_count"])

    def clamp_frame(self, frame_number: int) -> int:
        return max(0, min(frame_number, self.frame_count() - 1))

    def current_video_path(self) -> Path:
        path = self.repo_root / self.current_manifest["video_path"]
        resolved = path.resolve(strict=True)
        resolved.relative_to(self.repo_root)
        return resolved

    def default_start_frame(self) -> int:
        enter = self.current["enter_frame"]
        if enter:
            return self.clamp_frame(int(enter) - 15)
        return 0

    def zone_polygon_px(self) -> Optional[np.ndarray]:
        norm = self._zone_polygons.get(self.current["zone_id"])
        if norm is None:
            return None
        width = int(self.current_manifest["width"])
        height = int(self.current_manifest["height"])
        return np.array(
            [[round(x * width), round(y * height)] for x, y in norm], dtype=np.int32
        )

    def _reset_capture(self) -> None:
        if self._capture is not None:
            self._capture.release()
        self._capture = cv2.VideoCapture(str(self.current_video_path()))
        if not self._capture.isOpened():
            raise ValueError(f"영상을 열 수 없습니다: {self.current_video_path()}")
        self._last_frame_index = -1
        self._last_frame = None
        self._frame_cache = {}

    @staticmethod
    def _resize_for_display(frame):
        height, width = frame.shape[:2]
        if width <= _DISPLAY_MAX_WIDTH:
            return frame
        scale = _DISPLAY_MAX_WIDTH / width
        return cv2.resize(
            frame,
            (_DISPLAY_MAX_WIDTH, max(1, round(height * scale))),
            interpolation=cv2.INTER_AREA,
        )

    @staticmethod
    def _decode_cached_frame(encoded):
        frame = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
        if frame is None:
            raise ValueError("검수 frame cache를 디코딩할 수 없습니다.")
        return frame

    def _cache_frame(self, frame_number: int, frame):
        display_frame = self._resize_for_display(frame)
        ok, encoded = cv2.imencode(
            ".jpg",
            display_frame,
            [cv2.IMWRITE_JPEG_QUALITY, _FRAME_CACHE_JPEG_QUALITY],
        )
        if not ok:
            raise ValueError(f"frame {frame_number} 검수 cache 생성에 실패했습니다.")
        self._frame_cache[frame_number] = encoded
        return display_frame

    def frame_at(self, frame_number: int):
        if self._capture is None:
            self._reset_capture()

        cached = self._frame_cache.get(frame_number)
        if cached is not None:
            return self._decode_cached_frame(cached)
        if frame_number < self._last_frame_index:
            raise ValueError(f"frame {frame_number}이 검수 cache에서 누락됐습니다.")

        while self._last_frame_index < frame_number:
            ok, decoded = self._capture.read()
            if not ok:
                return None
            self._last_frame_index += 1
            self._last_frame = self._cache_frame(self._last_frame_index, decoded)
        return self._last_frame.copy() if self._last_frame is not None else None

    def set_frame(self, field: str, frame_number: int) -> None:
        if field not in _SETTABLE_FIELDS:
            raise ValueError(f"지원하지 않는 frame field입니다: {field}")
        self.current[field] = str(self.clamp_frame(frame_number))

    def clear_frame(self, field: str) -> None:
        if field not in _SETTABLE_FIELDS:
            raise ValueError(f"지원하지 않는 frame field입니다: {field}")
        self.current[field] = ""

    def add_interval(self) -> None:
        video_id = self.current["video_id"]
        zone_id = self.current["zone_id"]
        existing_indexes = [
            int(row["interval_index"])
            for row in self.all_rows
            if row["video_id"] == video_id and row["zone_id"] == zone_id
        ]
        new_row = {
            "video_id": video_id,
            "zone_id": zone_id,
            "interval_index": str(max(existing_indexes) + 1),
            "enter_frame": "",
            "exit_frame": "",
            "dwell_start_frame": "",
            "review_status": "pending",
            "notes": "",
        }
        insert_at = self.all_rows.index(self.current) + 1
        self.all_rows.insert(insert_at, new_row)
        self.rows.insert(self.index + 1, new_row)
        self.index += 1

    def approve(self) -> str:
        original_status = self.current["review_status"]
        original_dwell = self.current["dwell_start_frame"]
        self._derive_dwell_start_frame()
        self.current["review_status"] = "reviewed"
        try:
            contract.validate_zone_intervals(self.all_rows, self.manifest_rows)
        except ValueError:
            self.current["review_status"] = original_status
            self.current["dwell_start_frame"] = original_dwell
            raise
        self.current["notes"] = _remove_note(
            self.current["notes"], contract.SCENARIO_SEEDED_DRAFT_NOTE
        )
        return "reviewed"

    def _derive_dwell_start_frame(self) -> None:
        enter_text = self.current["enter_frame"]
        exit_text = self.current["exit_frame"]
        if not enter_text or not exit_text:
            self.current["dwell_start_frame"] = ""
            return

        enter_frame = int(enter_text)
        exit_frame = int(exit_text)
        fps = float(self.current_manifest["fps"])
        dwell_frame = enter_frame + math.ceil(DEFAULT_DWELL_THRESHOLD_SEC * fps)
        self.current["dwell_start_frame"] = (
            str(dwell_frame) if dwell_frame < exit_frame else ""
        )

    def mark_needs_review(self) -> None:
        self.current["review_status"] = "needs_review"

    def go_next(self) -> bool:
        if self.index >= len(self.rows) - 1:
            return False
        self.index += 1
        return True

    def go_previous(self) -> bool:
        if self.index <= 0:
            return False
        self.index -= 1
        return True

    def save(self) -> None:
        contract.validate_zone_intervals(self.all_rows, self.manifest_rows)
        contract.write_csv_atomic(
            self.intervals_path,
            contract.ZONE_INTERVAL_FIELDS,
            self.all_rows,
            force=True,
        )

    def close(self) -> None:
        if self._capture is not None:
            self._capture.release()
            self._capture = None


def _remove_note(notes: str, message: str) -> str:
    parts = [part.strip() for part in notes.split(";") if part.strip()]
    message_parts = [part.strip() for part in message.split(";") if part.strip()]
    if parts[: len(message_parts)] == message_parts:
        parts = parts[len(message_parts):]
    return "; ".join(parts)


def _draw_overlay(session: ReviewSession, frame_number: int, frame):
    row = session.current
    overlay = frame.copy()
    polygon = session.zone_polygon_px()
    if polygon is not None:
        display_width = overlay.shape[1]
        video_width = int(session.current_manifest["width"])
        scale = display_width / video_width if video_width else 1.0
        scaled = np.round(polygon * scale).astype(np.int32)
        cv2.polylines(overlay, [scaled], isClosed=True, color=_ZONE_COLOR, thickness=2)
    lines = [
        (
            f"{session.index + 1}/{len(session.rows)} {row['video_id']} "
            f"zone={row['zone_id']} status={row['review_status']}"
        ),
        f"frame={frame_number}/{session.frame_count() - 1} interval={row['interval_index']}",
        (
            f"enter={row['enter_frame']} exit={row['exit_frame']} "
            f"dwell(auto)={row['dwell_start_frame']}"
        ),
        f"blind_ground_truth={not bool(session._zone_polygons)}",
        (
            "Space play  ,/. 1f  A/D 10f  E/X set  1/2 clear  M add-interval  "
            "Enter approve+next  U needs_review  N/P interval  Q quit"
        ),
    ]
    for index, text in enumerate(lines):
        cv2.putText(
            overlay,
            text,
            (10, 24 + index * 24),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (0, 255, 0),
            1,
        )
    return overlay


def run_interactive(session: ReviewSession) -> None:  # pragma: no cover
    frame_number = session.default_start_frame()
    playing = False
    window_name = "Phase 4 Zone Interval Review"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(window_name, 1280, 720)
    frame_keys = {
        ord("e"): "enter_frame",
        ord("x"): "exit_frame",
    }
    clear_keys = {
        ord("1"): "enter_frame",
        ord("2"): "exit_frame",
    }

    try:
        while True:
            if cv2.getWindowProperty(window_name, cv2.WND_PROP_VISIBLE) < 1:
                break
            frame = session.frame_at(frame_number)
            if frame is None:
                raise ValueError(
                    f"frame {frame_number}을 디코딩할 수 없습니다: "
                    f"{session.current_video_path()}"
                )
            cv2.imshow(window_name, _draw_overlay(session, frame_number, frame))
            key = cv2.waitKey(30 if playing else 0) & 0xFF
            lowered = ord(chr(key).lower()) if 0 <= key < 128 else key

            if key == 255:
                if playing:
                    frame_number = session.clamp_frame(frame_number + 1)
                continue
            if key == ord(" "):
                playing = not playing
            elif key in (81, ord(",")):
                frame_number = session.clamp_frame(frame_number - 1)
            elif key in (83, ord(".")):
                frame_number = session.clamp_frame(frame_number + 1)
            elif lowered == ord("a"):
                frame_number = session.clamp_frame(frame_number - 10)
            elif lowered == ord("d"):
                frame_number = session.clamp_frame(frame_number + 10)
            elif lowered in frame_keys:
                field = frame_keys[lowered]
                session.set_frame(field, frame_number)
                print(f"{session.current['video_id']}: {field}={frame_number}")
            elif key in clear_keys:
                session.clear_frame(clear_keys[key])
            elif lowered == ord("m"):
                session.add_interval()
                frame_number = session.default_start_frame()
                new_index = session.current["interval_index"]
                print(f"{session.current['video_id']}: interval {new_index} 추가")
            elif lowered == ord("v") or key in (10, 13):
                try:
                    result = session.approve()
                    session.save()
                    print(f"{session.current['video_id']}: {result}")
                    if session.go_next():
                        frame_number = session.default_start_frame()
                        playing = False
                    else:
                        print("현재 영상의 마지막 interval입니다.")
                except ValueError as exc:
                    print(f"승인 실패: {exc}")
            elif lowered == ord("u"):
                session.mark_needs_review()
                session.save()
            elif lowered == ord("n") or key == 9:
                if session.go_next():
                    frame_number = session.default_start_frame()
                    playing = False
            elif lowered == ord("p") or key in (8, 127):
                if session.go_previous():
                    frame_number = session.default_start_frame()
                    playing = False
            elif lowered == ord("q") or key == 27:
                session.save()
                break
    finally:
        try:
            session.save()
        finally:
            session.close()
            cv2.destroyAllWindows()


def main() -> None:
    args = parse_args()
    try:
        session = ReviewSession(
            manifest_path=Path(args.manifest),
            intervals_path=Path(args.intervals),
            repo_root=Path(args.repo_root),
            video_id=args.video_id,
            image_zone_path=Path(args.image_zone) if args.image_zone else None,
            show_zone_reference=args.show_zone_reference,
            include_reviewed=args.include_reviewed,
        )
        run_interactive(session)
    except (OSError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
