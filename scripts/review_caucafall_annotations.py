"""CAUCAFall annotation 초안을 실제 프레임과 대조해 검수하는 인터랙티브 도구.

generate_caucafall_annotations.py가 만든 pending 행을 사람이 눈으로 확인하고,
fall_start_frame이 실제 낙상 시작과 맞는지, impact_frame/lying_start_frame을
추가로 입력할지, review_status를 reviewed/needs_review로 바꿀지 결정한다.

CSV 로드/저장·프레임 탐색/clamp·review_status 전이 같은 상태 관리 로직
(ReviewSession)과 실제 cv2.imshow 화면·키 입력 루프(run_interactive)를
분리했다. ReviewSession은 GUI 없이 pytest로 검증하고, run_interactive는
디스플레이가 있는 환경에서 직접 실행해 확인해야 한다.

화면에는 evaluate_fall.py가 실제로 읽는 AVI를 순차 디코딩한 프레임을 기본으로
보여준다 (PNG만 보여주면 PNG↔TXT 정합성만 확인되고, 실제 평가 파이프라인이
보는 AVI↔TXT 정합성은 확인되지 않기 때문). CAUCAFall이 함께 제공하는 프레임별
PNG는 참고용 보조 화면으로 나란히 띄운다. AVI는 임의 seek(CAP_PROP_POS_FRAMES)
대신 항상 순차 디코딩한다 — 코덱에 따라 seek이 부정확할 수 있어, 뒤로 이동할
때도 처음부터 다시 순차 디코딩해서 target frame까지 읽는다.

키 조작:
    Space   재생/일시정지
    ← / →   1프레임 이동
    A / D   10프레임 이동
    S       현재 프레임을 fall_start_frame으로 지정
    I       현재 프레임을 impact_frame으로 지정
    L       현재 프레임을 lying_start_frame으로 지정
    R       reviewed 처리 (fall_start_frame<=impact_frame<=lying_start_frame 순서 검증)
    U       needs_review 처리
    N / P   다음/이전 영상
    Q       저장 후 종료

R/U/N/P 처리 시마다 자동 저장하고, 전체 루프를 try/finally로 감싸 창을 강제로
닫거나(X 버튼) Ctrl+C·예외로 중단해도 마지막 상태가 저장되도록 한다.

Usage:
    .venv/bin/python scripts/review_caucafall_annotations.py \
        --annotations data/annotations/caucafall_v5/development_annotations.csv \
        --videos-dir data/datasets/caucafall/v5/development \
        --label fall
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Dict, List, Optional

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent))
from evaluate_fall import _AnnotationRow, load_annotations  # noqa: E402
from evaluate_fall import validate_annotations  # noqa: E402
from generate_caucafall_annotations import _contains_holdout_segment  # noqa: E402

_VALID_REVIEW_STATUSES = {"pending", "reviewed", "needs_review"}
_DEFAULT_MARGIN_FRAMES = 15

# evaluate_fall._REQUIRED_COLUMNS는 컬럼 존재 여부만 확인하는 set이라 순서가
# 보장되지 않는다. CSV에 쓸 때는 순서가 고정된 목록이 필요하므로 별도로 둔다.
_CSV_COLUMNS_V1 = [
    "video_id",
    "label",
    "video_path",
    "fall_start_frame",
    "impact_frame",
    "lying_start_frame",
    "review_status",
]
# V2는 CAUCAFall 원본 class 0->1 전환을 dataset_fall_label_frame으로
# 보존하고, fall_start_frame에는 사람이 검수한 실제 동작 시작점을 기록한다.
_CSV_COLUMNS_V2 = [
    "video_id",
    "label",
    "video_path",
    "dataset_fall_label_frame",
    "fall_start_frame",
    "impact_frame",
    "lying_start_frame",
    "review_status",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--annotations", required=True, help="검수할 annotation CSV 경로")
    parser.add_argument("--videos-dir", required=True, help="video_path 기준 디렉터리")
    parser.add_argument(
        "--margin",
        type=int,
        default=_DEFAULT_MARGIN_FRAMES,
        help="영상 진입 시 fall_start_frame 후보 기준 앞으로 이동할 프레임 수",
    )
    parser.add_argument("--video-id", default=None, help="이 video_id부터 바로 시작한다.")
    parser.add_argument(
        "--label",
        default=None,
        choices=["fall", "no_fall"],
        help="이 label의 영상만 순회한다.",
    )
    parser.add_argument(
        "--auto-verify-no-fall",
        action="store_true",
        help=(
            "GUI를 열지 않고 no_fall 행 전체를 검사한다. 실제 프레임 범위의 class가 "
            "전부 0이면 자동으로 reviewed 처리하고, 1이 섞여 있으면 needs_review로 "
            "표시한다 (사람이 표본 확인은 별도로 해야 함)."
        ),
    )
    parser.add_argument(
        "--annotation-version",
        default="auto",
        choices=["auto", "v1", "v2"],
        help=(
            "auto(기본값): CSV 헤더에 dataset_fall_label_frame이 있으면 v2, 없으면 v1로 "
            "판별한다. v1/v2를 명시하면 실제 헤더와 다를 때 즉시 오류로 막는다 — "
            "v2 CSV를 실수로 v1 규칙(느슨한 reviewed 검증)으로 여는 걸 방지하기 위함이다. "
            "v2: fall 행을 reviewed 처리하려면 dataset_fall_label_frame/fall_start_frame/"
            "impact_frame/lying_start_frame 네 값이 모두 있어야 한다."
        ),
    )
    return parser.parse_args()


def guard_holdout(videos_dir: Path) -> None:
    if _contains_holdout_segment(videos_dir.resolve()):
        raise SystemExit("Subject 9~10(holdout)은 검수하지 않습니다 (docs/data_sources.md).")


def guard_video_path(video_path: Path, videos_dir: Path) -> None:
    """CSV의 video_path가 holdout을 가리키거나 videos_dir 밖으로 벗어나면 차단한다.

    --videos-dir 자체가 holdout이 아니어도, 개별 행이 절대경로나 `../holdout/...`
    상대경로로 holdout을 가리키면 guard_holdout()만으로는 막을 수 없다.
    """
    if _contains_holdout_segment(video_path):
        raise SystemExit(f"holdout 경로는 검수할 수 없습니다: {video_path}")
    videos_root = videos_dir.resolve()
    try:
        video_path.relative_to(videos_root)
    except ValueError as exc:
        raise SystemExit(
            f"video_path가 --videos-dir 밖을 가리킵니다: {video_path} (기준: {videos_root})"
        ) from exc


def frame_label_files(activity_folder: Path) -> List[Path]:
    """정렬된 txt 라벨 파일 목록. 순서 인덱스가 곧 frame_number다."""
    return sorted(f for f in activity_folder.glob("*.txt") if f.name != "classes.txt")


def frame_image_files(activity_folder: Path) -> List[Path]:
    """정렬된 png 프레임 이미지 목록(참고용). txt와 1:1 대응(같은 base 이름)한다."""
    return sorted(activity_folder.glob("*.png"))


def get_frame_labels(activity_folder: Path, frame_count: int) -> List[Optional[str]]:
    """활동 폴더의 프레임별 class를 정렬 순서대로 읽어 frame_count에 맞춰 자른다.

    generate_caucafall_annotations.process_activity_folder()와 동일하게, txt
    개수가 실제 프레임 수를 초과하면 뒤에서부터 제외한다 (frame_number 정합성 유지).
    """
    classes: List[Optional[str]] = []
    for txt in frame_label_files(activity_folder)[:frame_count]:
        content = txt.read_text(encoding="utf-8").strip()
        classes.append(content.splitlines()[0].split()[0] if content else None)
    return classes


def _count_video_frames(video_path: Path) -> int:
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return 0
    count = 0
    try:
        while True:
            ret, _ = cap.read()
            if not ret:
                break
            count += 1
    finally:
        cap.release()
    return count


def save_rows(rows: List[_AnnotationRow], csv_path: Path, columns: List[str]) -> None:
    """임시 파일에 먼저 쓰고, 성공하면 원자적으로 원본 CSV를 교체한다.

    중간에 오류가 나거나 프로세스가 죽어도 원본 CSV(이전 검수 결과 포함)는
    훼손되지 않는다. review_status 값 자체와 행 구조(evaluate_fall.py의
    validate_annotations)를 저장 직전에 검증한다.

    columns: 실제로 쓸 컬럼 목록(_CSV_COLUMNS_V1 또는 _CSV_COLUMNS_V2). v1 CSV에
        dataset_fall_label_frame을 억지로 추가하지 않기 위해 호출자(ReviewSession)가
        로드 시점에 감지한 컬럼 집합을 그대로 넘긴다.
    """
    for row in rows:
        if row.review_status not in _VALID_REVIEW_STATUSES:
            raise ValueError(
                f"{row.video_id}: review_status='{row.review_status}'는 "
                f"{sorted(_VALID_REVIEW_STATUSES)} 중 하나여야 합니다."
            )
    # 검수 도중 자동 저장은 구조 검증만 한다 — v2 fall 행은 세 시점을 다
    # 채우기 전까지 pending으로 반복 저장되므로 fall_start_frame 필수 조건을
    # (evaluate_fall.py 채점 경로와 달리) 여기서는 강제하지 않는다. 다만
    # review_status="reviewed"인 행은 require_fall_start_frame=False와 무관하게
    # validate_annotations() 안에서 여전히 fall_start_frame을 요구한다.
    validate_annotations(rows, require_fall_start_frame=False)

    # mark_reviewed()를 거치지 않고 review_status="reviewed"가 된 행(CSV를 손으로
    # 고치거나, 이미 불완전하게 reviewed였던 v1 파일을 v2 컬럼으로 열었다가 다시
    # 저장하는 경우 등)도 v2 CSV라면 네 필드를 전부 갖추도록 강제한다.
    if columns == _CSV_COLUMNS_V2:
        for row in rows:
            if row.review_status == "reviewed":
                _validate_v2_three_timestamps(row)

    row_values = {
        "video_id": lambda row: row.video_id,
        "label": lambda row: row.label,
        "video_path": lambda row: row.video_path,
        "dataset_fall_label_frame": lambda row: _empty_or(row.dataset_fall_label_frame),
        "fall_start_frame": lambda row: _empty_or(row.fall_start_frame),
        "impact_frame": lambda row: _empty_or(row.impact_frame),
        "lying_start_frame": lambda row: _empty_or(row.lying_start_frame),
        "review_status": lambda row: row.review_status,
    }

    tmp_path = csv_path.with_suffix(csv_path.suffix + ".tmp")
    with open(tmp_path, "w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row_values[column](row) for column in columns})
    tmp_path.replace(csv_path)  # POSIX에서 원자적 rename


def _empty_or(value: Optional[int]):
    return "" if value is None else value


def _validate_frame_order(row: _AnnotationRow) -> None:
    """비어 있는 값은 건너뛰고, 입력된 값들 사이의 순서(fall_start<=impact<=lying)만 검증한다."""
    ordered = [
        (name, value)
        for name, value in (
            ("fall_start_frame", row.fall_start_frame),
            ("impact_frame", row.impact_frame),
            ("lying_start_frame", row.lying_start_frame),
        )
        if value is not None
    ]
    for (name_a, value_a), (name_b, value_b) in zip(ordered, ordered[1:]):
        if value_a > value_b:
            raise ValueError(
                f"{row.video_id}: {name_a}({value_a})는 {name_b}({value_b}) 이하여야 합니다."
            )


def _validate_v2_three_timestamps(row: _AnnotationRow) -> None:
    """V2 fall 행은 원본 라벨 프레임과 세 동작 시점이 있어야 검수를 확정한다.

    v1은 fall_start_frame 하나만 있어도 reviewed였지만, v2는 dataset_fall_label_frame과
    분리된 실제 onset/impact/lying 세 시점을 전부 확보하는 게 목적이므로, 하나라도
    비어 있으면 아직 검수가 끝나지 않은 것으로 본다.
    """
    if row.label != "fall":
        return
    missing = [
        name
        for name, value in (
            ("dataset_fall_label_frame", row.dataset_fall_label_frame),
            ("fall_start_frame", row.fall_start_frame),
            ("impact_frame", row.impact_frame),
            ("lying_start_frame", row.lying_start_frame),
        )
        if value is None
    ]
    if missing:
        raise ValueError(
            f"{row.video_id}: v2 검수는 {missing}이(가) 모두 있어야 reviewed로 표시할 수 있습니다."
        )


class ReviewSession:
    """CSV 로드/저장, 현재 영상·프레임 탐색, review_status 전이를 관리한다.

    cv2.imshow/waitKey 루프와 분리되어 있어 디스플레이 없이도 테스트할 수 있다.
    """

    def __init__(
        self,
        csv_path: Path,
        videos_dir: Path,
        margin: int = _DEFAULT_MARGIN_FRAMES,
        video_id: Optional[str] = None,
        label: Optional[str] = None,
        annotation_version: str = "auto",
    ) -> None:
        self.csv_path = Path(csv_path)
        self.videos_dir = Path(videos_dir)
        self.margin = margin
        # 저장할 컬럼 목록은 실제 CSV 헤더로 정한다 — v1 CSV를 열었는데
        # dataset_fall_label_frame 컬럼을 억지로 만들어내지 않기 위함이다.
        with open(self.csv_path, "r", encoding="utf-8", newline="") as file:
            header = next(csv.reader(file), [])
        detected_version = "v2" if "dataset_fall_label_frame" in header else "v1"
        self.csv_columns = _CSV_COLUMNS_V2 if detected_version == "v2" else _CSV_COLUMNS_V1

        # 명시한 버전과 실제 헤더가 다르면 다른 검수 규칙으로 저장되지 않도록
        # 즉시 거부한다. 기본 auto는 헤더에서 버전을 판별한다.
        if annotation_version != "auto" and annotation_version != detected_version:
            raise ValueError(
                f"{csv_path}: --annotation-version={annotation_version}로 지정했지만 "
                f"실제 CSV 헤더는 {detected_version}입니다."
            )
        self.annotation_version = (
            detected_version if annotation_version == "auto" else annotation_version
        )
        # self.all_rows가 저장 대상의 유일한 진실 공급원이다. --label로 필터링된
        # self.rows는 all_rows와 같은 객체를 참조하므로(얕은 필터), 검수 중 변경한
        # 내용은 그대로 반영되면서도 save()가 제외된 행을 지워버리지 않는다.
        self.all_rows: List[_AnnotationRow] = load_annotations(
            str(self.csv_path), include_unreviewed=True
        )
        for row in self.all_rows:
            guard_video_path(self._resolve_path(row.video_path), self.videos_dir)

        self.rows: List[_AnnotationRow] = (
            [r for r in self.all_rows if r.label == label] if label else self.all_rows
        )
        if not self.rows:
            raise ValueError(f"{csv_path}에 검수할 행이 없습니다 (label={label}).")

        self.index = 0
        if video_id is not None:
            for i, row in enumerate(self.rows):
                if row.video_id == video_id:
                    self.index = i
                    break
            else:
                raise ValueError(f"video_id={video_id}를 찾을 수 없습니다.")

        self._frame_count_cache: Dict[str, int] = {}
        self._avi_cap = None
        self._avi_cap_video_id: Optional[str] = None
        self._avi_last_frame_index = -1
        self._avi_last_frame = None

    def _resolve_path(self, video_path: str) -> Path:
        path = Path(video_path)
        if path.is_absolute():
            return path.resolve()
        return (self.videos_dir / path).resolve()

    @property
    def current(self) -> _AnnotationRow:
        return self.rows[self.index]

    def _video_path_for(self, row: _AnnotationRow) -> Path:
        return self._resolve_path(row.video_path)

    def _frame_count_for(self, row: _AnnotationRow) -> int:
        if row.video_id not in self._frame_count_cache:
            self._frame_count_cache[row.video_id] = _count_video_frames(self._video_path_for(row))
        return self._frame_count_cache[row.video_id]

    def current_video_path(self) -> Path:
        return self._video_path_for(self.current)

    def current_activity_folder(self) -> Path:
        return self.current_video_path().parent

    def frame_count(self) -> int:
        return self._frame_count_for(self.current)

    def clamp_frame(self, frame_number: int) -> int:
        count = self.frame_count()
        if count <= 0:
            return 0
        return max(0, min(frame_number, count - 1))

    def default_start_frame(self) -> int:
        # v2는 fall_start_frame이 검수 전까지 비어 있으므로, 원본 class 전환
        # 프레임(dataset_fall_label_frame)을 대신 앵커로 쓴다 — 실제 동작 시작은
        # 이 값보다 앞설 가능성이 높으므로 margin만큼 물러선 지점에서 검수를 시작한다.
        candidate = self.current.fall_start_frame
        if candidate is None:
            candidate = self.current.dataset_fall_label_frame
        if candidate is None:
            return 0
        return self.clamp_frame(candidate - self.margin)

    def frame_class_at(self, frame_number: int) -> Optional[str]:
        labels = get_frame_labels(self.current_activity_folder(), self.frame_count())
        if 0 <= frame_number < len(labels):
            return labels[frame_number]
        return None

    def _ensure_avi_capture(self) -> None:
        if self._avi_cap is None or self._avi_cap_video_id != self.current.video_id:
            if self._avi_cap is not None:
                self._avi_cap.release()
            self._avi_cap = cv2.VideoCapture(str(self.current_video_path()))
            self._avi_cap_video_id = self.current.video_id
            self._avi_last_frame_index = -1
            self._avi_last_frame = None

    def avi_frame_at(self, frame_number: int):
        """AVI를 순차 디코딩해 frame_number의 실제 프레임을 반환한다 (evaluate_fall.py와 동일 경로).

        임의 seek(CAP_PROP_POS_FRAMES)은 코덱에 따라 부정확할 수 있어 사용하지
        않는다. 뒤로 이동하면 처음부터 다시 순차 디코딩한다 — 영상 길이가 수백
        프레임 수준이라 매번 다시 읽어도 인터랙티브 사용에 문제없다.
        """
        self._ensure_avi_capture()
        if frame_number < self._avi_last_frame_index:
            self._avi_cap.release()
            self._avi_cap = cv2.VideoCapture(str(self.current_video_path()))
            self._avi_last_frame_index = -1
            self._avi_last_frame = None

        # 이동 없이 R/U 등만 눌러 같은 프레임을 다시 요청하는 경우(while 루프가
        # 한 번도 안 돌아 frame=None을 반환하던 문제) 마지막으로 디코딩한
        # 프레임을 그대로 반환한다.
        if frame_number == self._avi_last_frame_index and self._avi_last_frame is not None:
            return self._avi_last_frame.copy()

        while self._avi_last_frame_index < frame_number:
            ret, decoded = self._avi_cap.read()
            if not ret:
                return None
            self._avi_last_frame = decoded
            self._avi_last_frame_index += 1
        return self._avi_last_frame.copy() if self._avi_last_frame is not None else None

    def png_frame_at(self, frame_number: int):
        """참고용 보조 화면. CAUCAFall이 제공하는 프레임별 PNG를 그대로 읽는다."""
        images = frame_image_files(self.current_activity_folder())[: self.frame_count()]
        if not (0 <= frame_number < len(images)):
            return None
        return cv2.imread(str(images[frame_number]))

    def set_fall_start_frame(self, frame_number: int) -> None:
        self.current.fall_start_frame = self.clamp_frame(frame_number)

    def set_impact_frame(self, frame_number: int) -> None:
        self.current.impact_frame = self.clamp_frame(frame_number)

    def set_lying_start_frame(self, frame_number: int) -> None:
        self.current.lying_start_frame = self.clamp_frame(frame_number)

    def mark_reviewed(self) -> None:
        """fall_start_frame<=impact_frame<=lying_start_frame(입력된 값만) 순서를 검증한 뒤 전이한다.

        V2는 원본 라벨 프레임과 세 동작 시점이 모두 입력됐는지도 검증한다.
        """
        _validate_frame_order(self.current)
        if self.annotation_version == "v2":
            _validate_v2_three_timestamps(self.current)
        self.current.review_status = "reviewed"

    def mark_needs_review(self) -> None:
        self.current.review_status = "needs_review"

    def auto_review_no_fall(self) -> List[str]:
        """no_fall 행 전체를 검사해, 다음을 모두 만족할 때만 reviewed로 자동 처리한다.

            - AVI가 정상적으로 열리고 frame_count > 0
            - txt 개수가 frame_count 이상 (부족하면 검증 자체가 불완전함)
            - 실제로 읽은 class 개수가 frame_count와 정확히 일치
            - 모든 class가 "0"
            - fall_start_frame/impact_frame/lying_start_frame이 전부 비어 있음
              (no_fall 행에 낙상 시점 필드가 남아 있으면 데이터 이상이므로 승인하지 않음)
            - 이미 needs_review로 표시돼 있지 않음 (사람이 이미 내린 판단을 자동으로
              덮어쓰지 않는다)

        `all([])`이 True인 파이썬 특성 때문에, AVI를 못 열거나(frame_count=0) txt가
        하나도 없어 classes가 빈 리스트가 되는 경우에도 예전 구현은 잘못 승인할 수
        있었다 — 위 조건들이 이를 명시적으로 막는다.

        Returns:
            needs_review로 남은(자동 승인되지 않은) video_id 목록.
        """
        flagged: List[str] = []
        for row in self.all_rows:
            if row.label != "no_fall":
                continue
            if row.review_status == "needs_review":
                flagged.append(row.video_id)
                continue

            frame_count = self._frame_count_for(row)
            activity_folder = self._video_path_for(row).parent
            txt_count = len(frame_label_files(activity_folder))
            classes = get_frame_labels(activity_folder, frame_count)

            is_clean = (
                frame_count > 0
                and txt_count >= frame_count
                and len(classes) == frame_count
                and all(c == "0" for c in classes)
                and row.fall_start_frame is None
                and row.impact_frame is None
                and row.lying_start_frame is None
            )

            if is_clean:
                row.review_status = "reviewed"
            else:
                row.review_status = "needs_review"
                flagged.append(row.video_id)
        return flagged

    def go_next_video(self) -> bool:
        if self.index >= len(self.rows) - 1:
            return False
        self.index += 1
        return True

    def go_prev_video(self) -> bool:
        if self.index <= 0:
            return False
        self.index -= 1
        return True

    def save(self) -> None:
        """--label/--video-id로 필터링돼 있어도 항상 전체 행(all_rows)을 저장한다."""
        save_rows(self.all_rows, self.csv_path, self.csv_columns)

    def close(self) -> None:
        if self._avi_cap is not None:
            self._avi_cap.release()
            self._avi_cap = None


def run_interactive(session: ReviewSession) -> None:  # pragma: no cover
    """실제 cv2.imshow 화면과 키 입력 루프. 디스플레이가 있는 환경에서 직접 실행해야 한다."""
    frame_number = session.default_start_frame()
    playing = False
    window_name = "CAUCAFall Annotation Review"
    cv2.namedWindow(window_name)

    try:
        while True:
            if cv2.getWindowProperty(window_name, cv2.WND_PROP_VISIBLE) < 1:
                break  # 창을 X 버튼으로 닫음

            frame = session.avi_frame_at(frame_number)
            row = session.current
            if frame is not None:
                overlay = frame.copy()
                cls = session.frame_class_at(frame_number)
                lines = [
                    f"video_id={row.video_id}  label={row.label}  status={row.review_status}",
                    f"frame={frame_number}/{session.frame_count() - 1}  class={cls}",
                    (
                        f"fall_start={row.fall_start_frame}  impact={row.impact_frame}  "
                        f"lying={row.lying_start_frame}"
                    ),
                    f"dataset_fall_label={row.dataset_fall_label_frame} (원본 class 0->1, 참고용)",
                    "Space play/pause  A/D 10f  S/I/L set  R reviewed  U needs_review  "
                    "N/P video  Q save&quit",
                ]
                for i, text in enumerate(lines):
                    cv2.putText(
                        overlay,
                        text,
                        (10, 20 + i * 20),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.5,
                        (0, 255, 0),
                        1,
                    )
                cv2.imshow(window_name, overlay)

                png = session.png_frame_at(frame_number)
                if png is not None:
                    cv2.imshow(window_name + " (PNG 참고)", png)

            key = cv2.waitKey(30 if playing else 0) & 0xFF

            if key == 255:
                if playing:
                    frame_number = session.clamp_frame(frame_number + 1)
                continue
            if key == ord(" "):
                playing = not playing
            elif key in (81, ord(",")):  # 좌측 방향키(플랫폼별 코드 상이) / 보조키
                frame_number = session.clamp_frame(frame_number - 1)
            elif key in (83, ord(".")):  # 우측 방향키 / 보조키
                frame_number = session.clamp_frame(frame_number + 1)
            elif key in (ord("a"), ord("A")):
                frame_number = session.clamp_frame(frame_number - 10)
            elif key in (ord("d"), ord("D")):
                frame_number = session.clamp_frame(frame_number + 10)
            elif key in (ord("s"), ord("S")):
                session.set_fall_start_frame(frame_number)
            elif key in (ord("i"), ord("I")):
                session.set_impact_frame(frame_number)
            elif key in (ord("l"), ord("L")):
                session.set_lying_start_frame(frame_number)
            elif key in (ord("r"), ord("R")):
                try:
                    session.mark_reviewed()
                    session.save()
                except ValueError as exc:
                    print(f"reviewed 처리 실패: {exc}")
            elif key in (ord("u"), ord("U")):
                session.mark_needs_review()
                session.save()
            elif key in (ord("n"), ord("N")):
                if session.go_next_video():
                    frame_number = session.default_start_frame()
                    playing = False
                    session.save()
            elif key in (ord("p"), ord("P")):
                if session.go_prev_video():
                    frame_number = session.default_start_frame()
                    playing = False
                    session.save()
            elif key in (ord("q"), ord("Q")):
                session.save()
                break
    finally:
        # X 버튼/Ctrl+C/예외 등 어떤 경로로 빠져나가도 마지막 상태를 저장한다.
        # 저장 자체가 실패하면(예: 순서 검증 실패) 원본 CSV는 save_rows()의
        # 임시 파일 방식 덕분에 그대로 보존된다.
        try:
            session.save()
        except ValueError as exc:
            print(f"종료 시 저장 실패 (원본 CSV는 보존됨): {exc}")
        session.close()
        cv2.destroyAllWindows()


def main() -> None:
    args = parse_args()
    videos_dir = Path(args.videos_dir)
    guard_holdout(videos_dir)
    session = ReviewSession(
        Path(args.annotations),
        videos_dir,
        margin=args.margin,
        video_id=args.video_id,
        label=args.label,
        annotation_version=args.annotation_version,
    )

    if args.auto_verify_no_fall:
        flagged = session.auto_review_no_fall()
        session.save()
        total_no_fall = sum(1 for r in session.all_rows if r.label == "no_fall")
        print(f"no_fall {total_no_fall}개 중 {total_no_fall - len(flagged)}개를 reviewed로 자동 처리했습니다.")
        if flagged:
            print(f"class=1이 섞여 있어 needs_review로 남긴 영상 {len(flagged)}개: {flagged}")
        return

    run_interactive(session)


if __name__ == "__main__":
    main()
