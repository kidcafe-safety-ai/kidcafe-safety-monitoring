"""캐시된 Track이 ground truth 대상 인물인지 눈으로 확인한다.

한 영상에 여러 사람이 잡히면 `evaluate_zone_paths.py`의 Track 선택 규칙이
어느 쪽을 고를지가 절대 수치를 바꾼다. `IMG_7385`가 그런 경우로, `longest`와
`gt-overlap`이 서로 다른 Track을 고른다. 어느 쪽이 manifest의
`primary_actor_id`인지는 수치만 봐서는 알 수 없다.

그래서 캐시에 있는 bbox와 foot point를 프레임에 그려 저장한다. 사람이 복장을
보고 대조하면 되고, 모델은 필요 없다.

사용 예:

    python scripts/verify_track_identity.py \\
        --cache outputs/phase4_zone_eval/foot_points.json \\
        --manifest data/annotations/phase4/recordings_manifest.csv \\
        --repo-root . \\
        --video-id P4_S01_A01_zone_enter_exit_06_cam01 \\
        --frames 250,350,450 \\
        --output-dir outputs/phase4_zone_eval/track_check
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Dict, List

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# track_id별 BGR 색. 순서는 고정이라 같은 id는 항상 같은 색으로 그려진다.
COLORS = (
    (60, 220, 60),
    (60, 60, 235),
    (235, 180, 60),
    (200, 60, 200),
    (60, 220, 220),
)


class VerifyError(RuntimeError):
    """확인 이미지를 만들 수 없는 입력 상태."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--video-id", required=True)
    parser.add_argument(
        "--frames",
        required=True,
        help="확인할 frame 번호를 쉼표로 구분해 적는다. 예: 250,350,450",
    )
    parser.add_argument("--output-dir", required=True)
    return parser.parse_args()


def parse_frames(text: str) -> List[int]:
    """`--frames` 문자열을 frame 번호 목록으로 바꾼다."""
    numbers = []
    for piece in text.split(","):
        piece = piece.strip()
        if not piece:
            continue
        if not piece.isdigit():
            raise VerifyError(f"frame 번호가 숫자가 아닙니다: {piece}")
        numbers.append(int(piece))
    if not numbers:
        raise VerifyError("확인할 frame이 없습니다.")
    return sorted(set(numbers))


def color_for(track_id: int) -> tuple:
    return COLORS[track_id % len(COLORS)]


def find_video(manifest: Path, video_id: str) -> str:
    if not manifest.is_file():
        raise VerifyError(f"manifest가 없습니다: {manifest}")
    with open(manifest, "r", encoding="utf-8", newline="") as file:
        for row in csv.DictReader(file):
            if row["video_id"] == video_id:
                return row["video_path"]
    raise VerifyError(f"manifest에 없는 video_id: {video_id}")


def load_cached_frames(cache: Path, video_id: str) -> Dict[str, List[dict]]:
    if not cache.is_file():
        raise VerifyError(f"캐시가 없습니다: {cache}")
    payload = json.loads(cache.read_text(encoding="utf-8"))
    videos = payload.get("videos", {})
    if video_id not in videos:
        raise VerifyError(f"캐시에 없는 video_id: {video_id}")
    return videos[video_id]["frames"]


def draw_tracks(frame, tracks: List[dict]):
    """한 frame에 bbox·track id·foot point를 그린다."""
    for track in tracks:
        track_id = int(track["track_id"])
        color = color_for(track_id)
        x1, y1, x2, y2 = (int(round(v)) for v in track["bbox"])
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 3)
        cv2.putText(
            frame,
            f"T{track_id}",
            (x1, max(y1 - 10, 20)),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.2,
            color,
            3,
        )
        foot_x, foot_y = (int(round(v)) for v in track["foot_point"])
        cv2.circle(frame, (foot_x, foot_y), 8, color, -1)
    return frame


def main() -> None:
    args = parse_args()
    root = Path(args.repo_root).resolve()
    try:
        wanted = parse_frames(args.frames)
        cached = load_cached_frames(Path(args.cache), args.video_id)
        video_path = root / find_video(Path(args.manifest), args.video_id)
        if not video_path.is_file():
            raise VerifyError(f"영상이 없습니다: {video_path}")

        output_dir = Path(args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        capture = cv2.VideoCapture(str(video_path))
        if not capture.isOpened():
            raise VerifyError(f"영상을 열 수 없습니다: {video_path}")
        # seek 대신 순차 디코딩한다. 컨테이너에 따라 frame 단위 seek가
        # 어긋나는데, 여기서 어긋나면 엉뚱한 frame을 보고 판단하게 된다.
        try:
            written = []
            number = 0
            last = wanted[-1]
            while number <= last:
                ok, frame = capture.read()
                if not ok:
                    break
                if number in wanted:
                    draw_tracks(frame, cached.get(str(number), []))
                    target = output_dir / f"{args.video_id}_f{number:05d}.jpg"
                    cv2.imwrite(str(target), frame)
                    written.append((number, len(cached.get(str(number), []))))
                number += 1
        finally:
            capture.release()
    except VerifyError as exc:
        raise SystemExit(str(exc)) from exc

    missing = sorted(set(wanted) - {n for n, _ in written})
    for number, count in written:
        print(f"frame {number}: Track {count}개 -> {args.video_id}_f{number:05d}.jpg")
    if missing:
        print(f"영상 길이를 넘어 건너뛴 frame: {missing}")
    print(f"-> {output_dir}")


if __name__ == "__main__":
    main()
