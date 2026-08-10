"""Phase 4 직접 촬영 낙상·Cause annotation을 영상으로 2인 검수한다.

키:
    Space       재생/일시정지
    , / .       이전/다음 frame
    A / D       10 frame 이전/다음
    S/I/L/R/C   fall start / impact / lying / recovery / contact frame 지정
    6/7/8/9/0   위 다섯 frame 지정용 숫자 대체 키
    1/2/3/4/5   위 다섯 frame 값 삭제
    T/G         contact_occurred / cause_candidate_exists 전환
    V/Enter     현재 reviewer 승인 후 다음 영상
    U           needs_review
    N/P         다음/이전 영상
    Q           저장 후 종료
    Tab         다음 영상 대체 키
    Backspace   이전 영상 대체 키
    Esc         저장 후 종료 대체 키

첫 번째 reviewer가 V를 누르면 필수값을 검증하고 reviewer_id를 기록하되 상태는
pending으로 유지한다. 두 번째 reviewer가 값을 바꾸지 않고 V를 눌러야 reviewed가
된다. 두 번째 reviewer가 값을 수정하면 자동 합의로 처리하지 않고 needs_review로
남긴다.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent))

import phase4_recording_contract as contract  # noqa: E402


_SECOND_REVIEW_PLACEHOLDER = "__SECOND_REVIEW_REQUIRED__"
_DISPLAY_MAX_WIDTH = 1280
_FRAME_CACHE_JPEG_QUALITY = 82
_FALL_TIMING_FIELDS = {
    "fall_start_frame",
    "impact_frame",
    "lying_start_frame",
    "recovery_frame",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--annotations", required=True)
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--reviewer-id", required=True)
    parser.add_argument("--pass", dest="review_pass", choices=["first", "second"], required=True)
    parser.add_argument("--split", choices=sorted(contract.VALID_SPLIT_ROLES))
    parser.add_argument("--video-id")
    return parser.parse_args()


class ReviewSession:
    def __init__(
        self,
        *,
        manifest_path: Path,
        annotations_path: Path,
        repo_root: Path,
        reviewer_id: str,
        review_pass: str,
        split_role: Optional[str] = None,
        video_id: Optional[str] = None,
    ) -> None:
        if not reviewer_id.strip():
            raise ValueError("reviewer_id가 비어 있습니다.")
        if review_pass not in {"first", "second"}:
            raise ValueError("review_pass는 first 또는 second여야 합니다.")

        self.manifest_path = manifest_path
        self.annotations_path = annotations_path
        self.repo_root = repo_root.resolve()
        self.reviewer_id = reviewer_id.strip()
        self.review_pass = review_pass
        self.manifest_rows = contract.load_recordings_manifest(manifest_path)
        self.manifest_by_video = {row["video_id"]: row for row in self.manifest_rows}
        self.all_rows = contract.load_fall_cause_annotations(
            annotations_path, self.manifest_rows
        )

        eligible = []
        for row in self.all_rows:
            manifest = self.manifest_by_video[row["video_id"]]
            if split_role and manifest["split_role"] != split_role:
                continue
            if review_pass == "first":
                if row["review_status"] == "pending" and not row["reviewer_id"]:
                    eligible.append(row)
            elif (
                row["review_status"] == "pending"
                and row["reviewer_id"]
                and not row["second_reviewer_id"]
            ):
                if row["reviewer_id"] == self.reviewer_id:
                    raise ValueError(
                        f"{row['video_id']}: first reviewer와 second reviewer가 같습니다."
                    )
                eligible.append(row)

        if video_id is not None:
            eligible = [row for row in eligible if row["video_id"] == video_id]
        if not eligible:
            raise ValueError(
                f"{review_pass} pass에서 검수할 annotation이 없습니다 "
                f"(split={split_role}, video_id={video_id})."
            )

        self.rows = eligible
        self.index = 0
        self._capture = None
        self._capture_video_id: Optional[str] = None
        self._last_frame_index = -1
        self._last_frame = None
        self._frame_cache = {}
        self._second_pass_changed_ids: set[str] = set()

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
        for field in ("fall_start_frame", "contact_frame", "impact_frame"):
            value = self.current[field]
            if value:
                return self.clamp_frame(int(value) - 30)
        return 0

    def _reset_capture(self) -> None:
        if self._capture is not None:
            self._capture.release()
        self._capture = cv2.VideoCapture(str(self.current_video_path()))
        if not self._capture.isOpened():
            raise ValueError(f"영상을 열 수 없습니다: {self.current_video_path()}")
        self._capture_video_id = self.current["video_id"]
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
        if self._capture is None or self._capture_video_id != self.current["video_id"]:
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

    def _mark_changed(self) -> None:
        if self.review_pass == "second":
            self._second_pass_changed_ids.add(self.current["video_id"])

    def set_frame(self, field: str, frame_number: int) -> None:
        if field not in {
            "fall_start_frame",
            "impact_frame",
            "lying_start_frame",
            "recovery_frame",
            "contact_frame",
        }:
            raise ValueError(f"지원하지 않는 frame field입니다: {field}")
        if self.current["label"] == "no_fall" and field in _FALL_TIMING_FIELDS:
            raise ValueError("no_fall 영상에는 낙상 frame을 입력하지 않습니다.")
        value = str(self.clamp_frame(frame_number))
        if self.current[field] != value:
            self.current[field] = value
            self._mark_changed()

    def clear_frame(self, field: str) -> None:
        if self.current[field]:
            self.current[field] = ""
            self._mark_changed()

    def toggle_contact(self) -> None:
        new_value = "false" if self.current["contact_occurred"] == "true" else "true"
        self.current["contact_occurred"] = new_value
        if new_value == "false":
            self.current["contact_frame"] = ""
        self._mark_changed()

    def toggle_cause_candidate(self) -> None:
        current = self.current["cause_candidate_exists"]
        new_value = "false" if current == "true" else "true"
        self.current["cause_candidate_exists"] = new_value
        if new_value == "false":
            self.current["cause_actor_id"] = ""
        else:
            victim = self.current["victim_actor_id"]
            actors = contract.split_actor_ids(self.current_manifest["actor_ids"])
            candidates = [actor for actor in actors if actor != victim]
            if len(candidates) == 1:
                self.current["cause_actor_id"] = candidates[0]
        self._mark_changed()

    def _validate_as_reviewed(self, second_reviewer_id: str) -> None:
        original_status = self.current["review_status"]
        original_reviewer = self.current["reviewer_id"]
        original_second = self.current["second_reviewer_id"]
        try:
            self.current["review_status"] = "reviewed"
            self.current["reviewer_id"] = original_reviewer or self.reviewer_id
            self.current["second_reviewer_id"] = second_reviewer_id
            contract.validate_fall_cause_annotations(
                self.all_rows, self.manifest_rows
            )
        finally:
            self.current["review_status"] = original_status
            self.current["reviewer_id"] = original_reviewer
            self.current["second_reviewer_id"] = original_second

    def approve(self) -> str:
        if self.review_pass == "first":
            self._validate_as_reviewed(_SECOND_REVIEW_PLACEHOLDER)
            self.current["reviewer_id"] = self.reviewer_id
            self.current["review_status"] = "pending"
            return "first_review_complete"

        if self.current["video_id"] in self._second_pass_changed_ids:
            self.current["second_reviewer_id"] = self.reviewer_id
            self.current["review_status"] = "needs_review"
            self.current["notes"] = _append_note(
                self.current["notes"], "second reviewer changed annotation"
            )
            return "needs_review"

        self._validate_as_reviewed(self.reviewer_id)
        self.current["second_reviewer_id"] = self.reviewer_id
        self.current["review_status"] = "reviewed"
        self.current["notes"] = _remove_note(
            self.current["notes"], contract.SCENARIO_SEEDED_DRAFT_NOTE
        )
        return "reviewed"

    def mark_needs_review(self) -> None:
        if self.review_pass == "first":
            self.current["reviewer_id"] = self.reviewer_id
        else:
            self.current["second_reviewer_id"] = self.reviewer_id
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
        contract.validate_fall_cause_annotations(self.all_rows, self.manifest_rows)
        contract.write_csv_atomic(
            self.annotations_path,
            contract.FALL_CAUSE_FIELDS,
            self.all_rows,
            force=True,
        )

    def close(self) -> None:
        if self._capture is not None:
            self._capture.release()
            self._capture = None


def _append_note(notes: str, message: str) -> str:
    clean = notes.strip()
    return f"{clean}; {message}" if clean else message


def _remove_note(notes: str, message: str) -> str:
    parts = [part.strip() for part in notes.split(";") if part.strip()]
    message_parts = [part.strip() for part in message.split(";") if part.strip()]
    if parts[: len(message_parts)] == message_parts:
        parts = parts[len(message_parts):]
    return "; ".join(parts)


def _draw_overlay(session: ReviewSession, frame_number: int, frame):
    row = session.current
    manifest = session.current_manifest
    overlay = frame.copy()
    lines = [
        (
            f"{session.index + 1}/{len(session.rows)} {row['video_id']} "
            f"split={manifest['split_role']} status={row['review_status']}"
        ),
        f"frame={frame_number}/{session.frame_count() - 1} label={row['label']}",
        (
            f"start={row['fall_start_frame']} impact={row['impact_frame']} "
            f"lying={row['lying_start_frame']} recovery={row['recovery_frame']}"
        ),
        (
            f"victim={row['victim_actor_id']} contact={row['contact_occurred']}@"
            f"{row['contact_frame']} cause={row['cause_candidate_exists']}:"
            f"{row['cause_actor_id']}"
        ),
        (
            "Space play  ,/. 1f  A/D 10f  S/I/L/R/C set  1-5 clear  "
            "6-0 set  Enter approve+next  Tab next  Backspace prev  Esc quit"
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
    window_name = "Phase 4 Fall Annotation Review"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(window_name, 1280, 720)
    frame_keys = {
        ord("s"): "fall_start_frame",
        ord("i"): "impact_frame",
        ord("l"): "lying_start_frame",
        ord("r"): "recovery_frame",
        ord("c"): "contact_frame",
        ord("6"): "fall_start_frame",
        ord("7"): "impact_frame",
        ord("8"): "lying_start_frame",
        ord("9"): "recovery_frame",
        ord("0"): "contact_frame",
    }
    clear_keys = {
        ord("1"): "fall_start_frame",
        ord("2"): "impact_frame",
        ord("3"): "lying_start_frame",
        ord("4"): "recovery_frame",
        ord("5"): "contact_frame",
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
                try:
                    session.set_frame(field, frame_number)
                    print(f"{session.current['video_id']}: {field}={frame_number}")
                except ValueError as exc:
                    print(f"입력 거부: {exc}")
            elif key in clear_keys:
                session.clear_frame(clear_keys[key])
            elif lowered == ord("t"):
                session.toggle_contact()
            elif lowered == ord("g"):
                session.toggle_cause_candidate()
            elif lowered == ord("v") or key in (10, 13):
                try:
                    result = session.approve()
                    session.save()
                    print(f"{session.current['video_id']}: {result}")
                    if session.go_next():
                        frame_number = session.default_start_frame()
                        playing = False
                    else:
                        print("현재 검수 pass의 마지막 영상입니다.")
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
            annotations_path=Path(args.annotations),
            repo_root=Path(args.repo_root),
            reviewer_id=args.reviewer_id,
            review_pass=args.review_pass,
            split_role=args.split,
            video_id=args.video_id,
        )
        run_interactive(session)
    except (OSError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
