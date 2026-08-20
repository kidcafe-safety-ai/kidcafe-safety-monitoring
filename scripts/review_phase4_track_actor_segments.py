"""Phase 4 다중 인원 영상에서 Track segment를 A01/A02에 매핑한다.

한 번의 실행은 영상 하나만 다룬다. `--cache-dir`의 캐시된 bbox·Track만 읽어
프레임에 겹쳐 그린다 — YOLO·Pose를 다시 돌리지 않는다. 현재 검수 중인
segment의 track_id는 빨간색, 나머지 track은 회색으로 그린다.

ID switch는 이 도구에서 직접 표시하지 않는다. 같은 actor에게 배정된 두
segment의 track_id가 다르면 switch가 일어난 것이므로,
`derive_phase4_track_id_switches.py`가 검수 결과에서 기계적으로 계산한다.

키:
    Space       재생/일시정지
    , / .       이전/다음 frame
    A / D       10 frame 이전/다음
    1 / 2       현재 영상 actor_ids 순서대로 actor 배정
    B           배경·오검출 등 실제 참여자가 아닌 Track으로 배정
    0           배정 해제
    V / Enter   현재 segment 승인(review_status=reviewed)
    U           needs_review로 표시
    N / P       다음/이전 segment
    Q           저장 후 종료
    Tab         다음 segment 대체 키
    Backspace   이전 segment 대체 키
    Esc         저장 후 종료 대체 키

배경 인원·오검출 등 실제 actor가 아닌 track은 B로 남기고 notes에 이유를
적는다.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

import phase4_recording_contract as contract  # noqa: E402


_DISPLAY_MAX_WIDTH = 1280
_FRAME_CACHE_JPEG_QUALITY = 82
_CURRENT_TRACK_COLOR = (0, 0, 255)
_OTHER_TRACK_COLOR = (160, 160, 160)
_CLEAR_KEY = ord("0")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--segments", required=True)
    parser.add_argument("--cache-dir", required=True)
    parser.add_argument("--video-id", required=True)
    parser.add_argument("--repo-root", default=".")
    parser.add_argument(
        "--include-reviewed",
        action="store_true",
        help="이미 reviewed인 segment도 다시 연다",
    )
    return parser.parse_args()


class ReviewSession:
    def __init__(
        self,
        *,
        manifest_path: Path,
        segments_path: Path,
        cache_dir: Path,
        repo_root: Path,
        video_id: str,
        include_reviewed: bool = False,
    ) -> None:
        self.segments_path = segments_path
        self.repo_root = repo_root.resolve()
        self.manifest_rows = contract.load_recordings_manifest(manifest_path)
        self.manifest_by_video = {row["video_id"]: row for row in self.manifest_rows}
        if video_id not in self.manifest_by_video:
            raise ValueError(f"manifest에 없는 video_id입니다: {video_id}")
        self.video_id = video_id
        self.actor_ids = contract.split_actor_ids(
            self.manifest_by_video[video_id]["actor_ids"]
        )
        if len(self.actor_ids) > 9:
            raise ValueError(f"{video_id}: 검수 UI가 지원하는 actor는 최대 9명입니다.")
        self.assign_keys = {
            ord(str(index)): actor_id
            for index, actor_id in enumerate(self.actor_ids, start=1)
        }
        self.all_rows = contract.load_track_actor_segments(segments_path, self.manifest_rows)

        eligible = [row for row in self.all_rows if row["video_id"] == video_id]
        if not include_reviewed:
            eligible = [row for row in eligible if row["review_status"] != "reviewed"]
        if not eligible:
            raise ValueError(
                f"{video_id}: 검수할 segment가 없습니다 (include_reviewed={include_reviewed})."
            )
        eligible.sort(key=lambda row: (int(row["start_frame"]), int(row["track_id"])))

        cache_path = cache_dir / f"{video_id}.json"
        if not cache_path.is_file():
            raise ValueError(f"cache 파일이 없습니다: {cache_path}")
        cache_video = json.loads(cache_path.read_text(encoding="utf-8"))
        self._tracks_by_frame: dict[int, list[dict]] = {
            frame["frame_number"]: frame["tracks"] for frame in cache_video["frames"]
        }

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
        return self.manifest_by_video[self.video_id]

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
        return self.clamp_frame(int(self.current["start_frame"]))

    def tracks_at(self, frame_number: int) -> list[dict]:
        return self._tracks_by_frame.get(frame_number, [])

    def _reset_capture(self, *, clear_cache: bool = True) -> None:
        if self._capture is not None:
            self._capture.release()
        self._capture = cv2.VideoCapture(str(self.current_video_path()))
        if not self._capture.isOpened():
            raise ValueError(f"영상을 열 수 없습니다: {self.current_video_path()}")
        self._last_frame_index = -1
        self._last_frame = None
        if clear_cache:
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
            self._reset_capture(clear_cache=False)

        while self._last_frame_index < frame_number:
            ok, decoded = self._capture.read()
            if not ok:
                return None
            self._last_frame_index += 1
            self._last_frame = self._cache_frame(self._last_frame_index, decoded)
        return self._last_frame.copy() if self._last_frame is not None else None

    def assign_actor(self, actor_id: str) -> None:
        if actor_id not in self.actor_ids:
            raise ValueError(
                f"{self.video_id}: actor_id={actor_id!r}가 manifest actor_ids에 없습니다."
            )
        self.current["actor_id"] = actor_id
        self.current["notes"] = _remove_note(
            self.current["notes"], contract.NON_ACTOR_TRACK_NOTE
        )

    def assign_non_actor(self) -> None:
        self.current["actor_id"] = ""
        self.current["notes"] = _add_note(
            self.current["notes"], contract.NON_ACTOR_TRACK_NOTE
        )

    def clear_actor(self) -> None:
        self.current["actor_id"] = ""
        self.current["notes"] = _remove_note(
            self.current["notes"], contract.NON_ACTOR_TRACK_NOTE
        )

    def approve(self) -> str:
        original_status = self.current["review_status"]
        self.current["review_status"] = "reviewed"
        try:
            contract.validate_track_actor_segments(self.all_rows, self.manifest_rows)
        except ValueError:
            self.current["review_status"] = original_status
            raise
        self.current["notes"] = _remove_note(
            self.current["notes"], contract.SCENARIO_SEEDED_DRAFT_NOTE
        )
        return "reviewed"

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
        contract.validate_track_actor_segments(self.all_rows, self.manifest_rows)
        contract.write_csv_atomic(
            self.segments_path,
            contract.TRACK_ACTOR_SEGMENT_FIELDS,
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
    for index in range(len(parts) - len(message_parts) + 1):
        if parts[index:index + len(message_parts)] == message_parts:
            del parts[index:index + len(message_parts)]
            break
    return "; ".join(parts)


def _add_note(notes: str, message: str) -> str:
    parts = [part.strip() for part in notes.split(";") if part.strip()]
    if message not in parts:
        parts.append(message)
    return "; ".join(parts)


def _draw_overlay(session: ReviewSession, frame_number: int, frame):
    row = session.current
    overlay = frame.copy()
    display_width = overlay.shape[1]
    video_width = int(session.current_manifest["width"])
    scale = display_width / video_width if video_width else 1.0
    current_track_id = int(row["track_id"])

    for track in session.tracks_at(frame_number):
        x1, y1, x2, y2 = (value * scale for value in track["bbox"])
        color = (
            _CURRENT_TRACK_COLOR
            if track["track_id"] == current_track_id
            else _OTHER_TRACK_COLOR
        )
        thickness = 3 if track["track_id"] == current_track_id else 1
        cv2.rectangle(
            overlay, (round(x1), round(y1)), (round(x2), round(y2)), color, thickness
        )
        cv2.putText(
            overlay,
            f"id={track['track_id']}",
            (round(x1), max(0, round(y1) - 6)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            color,
            2,
            cv2.LINE_AA,
        )

    lines = [
        (
            f"{session.index + 1}/{len(session.rows)} {row['video_id']} "
            f"track_id={row['track_id']} status={row['review_status']}"
        ),
        (
            f"frame={frame_number}/{session.frame_count() - 1} "
            f"segment=[{row['start_frame']}, {row['end_frame']}] actor={row['actor_id']}"
        ),
        (
            "Space play  ,/. 1f  A/D 10f  "
            + "  ".join(
                f"{index}={actor_id}"
                for index, actor_id in enumerate(session.actor_ids, start=1)
            )
            + "  0=clear  "
            "B=non-actor  Enter approve+next  U needs_review  N/P segment  Q quit"
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
    window_name = "Phase 4 Track/Actor Review"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(window_name, 1280, 720)

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
            elif key in session.assign_keys:
                session.assign_actor(session.assign_keys[key])
                track_id = session.current["track_id"]
                print(
                    f"{session.current['video_id']}: track_id={track_id} "
                    f"-> {session.assign_keys[key]}"
                )
            elif key == _CLEAR_KEY:
                session.clear_actor()
            elif lowered == ord("b"):
                session.assign_non_actor()
                track_id = session.current["track_id"]
                print(
                    f"{session.current['video_id']}: track_id={track_id} -> non-actor"
                )
            elif lowered == ord("v") or key in (10, 13):
                try:
                    result = session.approve()
                    session.save()
                    print(f"{session.current['video_id']}: {result}")
                    if session.go_next():
                        frame_number = session.default_start_frame()
                        playing = False
                    else:
                        print("현재 영상의 마지막 segment입니다.")
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
            segments_path=Path(args.segments),
            cache_dir=Path(args.cache_dir),
            repo_root=Path(args.repo_root),
            video_id=args.video_id,
            include_reviewed=args.include_reviewed,
        )
        run_interactive(session)
    except (OSError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
