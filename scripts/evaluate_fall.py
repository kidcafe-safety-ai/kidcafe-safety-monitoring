"""FallDetector를 CAUCAFall(또는 동일 형식) 영상 세트에 대해 평가한다.

CAUCAFall 자체는 낙상 시작/충격/누운 시점 라벨을 제공하지 않으므로 팀이
직접 검토한 annotation CSV가 필요하다. legacy V1 공통 형식은 다음 7개
컬럼이다.

    video_id,label,video_path,fall_start_frame,impact_frame,lying_start_frame,review_status

CAUCAFall 공식 V2는 `dataset_fall_label_frame`을 추가한 8개 컬럼이며,
`phase4_fall_eval_v1` 공식 모드에서는 reviewed fall 행의 원본 라벨 프레임과
fall_start/impact/lying 세 시점을 모두 요구한다.

    - label: "fall" 또는 "no_fall" (정확히 일치해야 함)
    - video_path: --videos-dir 기준 상대 경로 (절대 경로도 허용)
    - fall_start_frame: label=fall 행은 필수 (정수, 0-base). Event가 이 frame
      이전에 발생하면 "이른 오탐(early false alarm)"으로 집계하고 true
      positive로 인정하지 않는다.
    - impact_frame: 있으면 감지 지연(latency) 계산의 기준 시점으로 사용한다.
      없으면 fall_start_frame을 기준으로 쓴다. (지연 = 첫 유효 Event frame -
      기준 frame. impact_frame이 fall_start_frame보다 뒤이므로, 낙상 시작
      직후 확정되면 지연이 음수로 나올 수 있다 — 이는 오류가 아니라 "충격
      시점보다 먼저 감지했다"는 의미이므로 0으로 자르지 않는다.)
    - lying_start_frame: 참고용, 현재 지표 계산에는 사용하지 않는다.
    - review_status: "reviewed"만 기본적으로 평가에 사용 (--include-unreviewed로 해제)

평가 기준(docs/data_sources.md "Phase 3 평가 기준"):
    Recall >= 75%, False alarm <= 0.2회/분, 평균 감지 지연 <= 2초, 낙상 1회당 Event 1회

Usage:
    .venv/bin/python scripts/evaluate_fall.py \
        --annotations data/annotations/caucafall_v5/development_annotations.csv \
        --videos-dir data/datasets/caucafall/v5/development \
        --split development

주의: Subject 9~10(holdout)은 최종 평가 전까지 사용하지 않는다
(docs/data_sources.md). 아래 세 지점 중 하나라도 경로 구성요소(디렉터리 이름)로
"holdout"을 포함하면 --allow-holdout 없이는 즉시 중단한다: --videos-dir,
--split, 그리고 annotation의 각 video_path를 --videos-dir 기준으로 resolve한
경로. video_id로부터 CAUCAFall Subject 번호를 안정적으로 역산할 방법이 없어
(파일 명명 규칙이 문서화되어 있지 않음), Subject 번호가 아니라 문서에 명시된
디렉터리 구조(docs/data_sources.md: development/validation/holdout)를
근거로 판단한다.
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2

# repo root를 sys.path에 추가한다. `src.main`과 달리 `python scripts/evaluate_fall.py`로
# 직접 실행하는 스크립트라 `python -m` 모듈 실행처럼 자동으로 repo root가 잡히지 않는다.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import fall_evaluation_protocol as evaluation_protocol  # noqa: E402

from src.common.types import Track  # noqa: E402
from src.safety.auxiliary_fall_model import AuxiliaryFallModel  # noqa: E402
from src.safety.fall_detector import FallDetectorConfig  # noqa: E402
from src.safety.fall_model_matching import (  # noqa: E402
    FallModelEvidence,
    match_detections_to_tracks,
)
from src.safety.fall_pipeline import (  # noqa: E402
    AuxiliaryEvidenceCadence,
    FallPipeline,
    should_run_auxiliary_inference,
    validate_auxiliary_inference_interval_frames,
)
from src.safety.pose_features import PoseFeatureExtractor  # noqa: E402
from src.tracking.bytetrack_wrapper import ByteTracker  # noqa: E402
from src.tracking.pose_tracker import PoseTracker  # noqa: E402

_REQUIRED_COLUMNS = {
    "video_id",
    "label",
    "video_path",
    "fall_start_frame",
    "impact_frame",
    "lying_start_frame",
    "review_status",
}
_VALID_LABELS = {"fall", "no_fall"}
_RECOGNIZED_SPLITS = {"development", "validation", "holdout"}


@dataclass
class _AnnotationRow:
    video_id: str
    label: str  # "fall" | "no_fall"
    video_path: str
    fall_start_frame: Optional[int]
    impact_frame: Optional[int]
    lying_start_frame: Optional[int]
    review_status: str
    # V2 annotation에서만 쓰는 참고용 필드.
    # CAUCAFall 원본 class 0->1 전환 프레임을 보존한다 — fall_start_frame이
    # v1에서는 이 값과 같았지만, v2부터는 사람이 검수한 "실제 동작 시작"으로
    # 의미가 바뀐다. 채점(score_fall_video)에는 쓰지 않고 감사/재현용으로만
    # annotation CSV에 함께 저장한다. v1 CSV에는 이
    # 컬럼이 아예 없어도 되므로 _REQUIRED_COLUMNS에는 넣지 않는다.
    dataset_fall_label_frame: Optional[int] = None


@dataclass
class _VideoResult:
    video_id: str
    label: str
    event_count: int
    event_frames: List[int] = field(default_factory=list)
    # 기존(unbounded) 지표 — 역사적 비교를 위해 유지한다. fall_start_frame
    # 이후 아무 때나 온 첫 Event를 TP로 인정한다.
    detected: bool = False
    latency_sec: Optional[float] = None
    early_false_alarms: int = 0
    qualifying_event_count: int = 0  # fall_start_frame 이후에 발생한 Event 개수
    # V2(timely) 지표 — [onset - tolerance, onset + timely_window_sec] 구간
    # 안에 온 Event만 TP로 인정한다. 이 구간을 벗어나 늦게 온 Event는
    # late_detection으로 별도 기록하고, 조용히 TP로 세지 않는다.
    timely_detected: bool = False
    onset_latency_sec: Optional[float] = None  # 첫 timely Event - fall_start_frame
    lead_to_impact_sec: Optional[float] = None  # impact_frame - 첫 timely Event
    late_detection: bool = False  # timely 구간 밖에서만 Event가 온 경우
    duplicate_event: bool = False  # tolerance 허용 시작 이후(구간 안+밖 합산) Event가 2개 이상
    # 진단 필드(Event schema에는 없음, 평가 산출물 전용) — fall 행에서만
    # timely 구간 기준으로 채워진다. no_fall 행이나 window_frame_count=0이면 None.
    # 이 영상의 "대표" timely confirm 하나만 가리킨다 — 늦은 재확정이나
    # no_fall 오탐의 진단은 여기 안 들어간다(event_diagnostics 참고).
    confirm_path: Optional[str] = None  # "bbox" | "pose" | "model"
    candidate_entry_reason: Optional[str] = None  # "dynamic" | "model" | "handoff"
    # 이 영상에서 confirm된 모든 Event의 진단을 frame_number 순서로 남긴다.
    # 대표 timely Event만 담는 위 필드와 달리 no_fall 오탐과 late detection도
    # 포함하며, 길이는 항상 len(event_frames)와 같다.
    event_diagnostics: List[dict] = field(default_factory=list)
    track_coverage: Optional[float] = None  # 구간 내 Track이 있었던 프레임 비율
    no_track_frame_count: Optional[int] = None
    id_switch_count: Optional[int] = None  # 구간 내 관측된 서로 다른 track_id 수 - 1
    pose_valid_frame_ratio: Optional[float] = None
    # 보조 모델 근거 진단 — fall 행에서 보조 모델을 쓴 경우에만 채워진다.
    model_observed_frame_count: Optional[int] = None
    model_fall_frame_count: Optional[int] = None
    model_fall_observed_ratio: Optional[float] = None
    max_consecutive_model_fall_frames: Optional[int] = None
    max_consecutive_model_fall_sec: Optional[float] = None
    duration_sec: float = 0.0
    error: Optional[str] = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--annotations", required=True, help="annotation CSV 경로")
    parser.add_argument("--videos-dir", required=True, help="video_path의 기준 디렉터리")
    parser.add_argument(
        "--split", default="", help="development | validation | holdout (분할 검증에도 사용됨)"
    )
    parser.add_argument("--config", default="configs/fall_detection.json")
    parser.add_argument(
        "--tracker",
        default="pose",
        choices=["bbox", "pose"],
        help=(
            "bbox: ByteTracker(yolo26n.pt), 아무 pose confirm 없이 bbox 경로만 사용. "
            "pose: PoseTracker(yolo26n-pose.pt), keypoints를 채워 pose confirm 경로도 "
            "함께 사용 (기본값)."
        ),
    )
    parser.add_argument(
        "--model",
        default=None,
        help="지정하지 않으면 --tracker에 맞는 기본 모델(yolo26n.pt 또는 yolo26n-pose.pt)을 쓴다.",
    )
    parser.add_argument("--conf", type=float, default=0.5)
    parser.add_argument(
        "--early-tolerance-sec",
        type=float,
        default=0.2,
        help=(
            "fall_start_frame 직전 이 시간(초) 이내의 Event는 이른 오탐이 아니라 "
            "true positive로 인정한다 (annotation 라벨링 오차 허용, score_fall_video "
            "docstring 참고). 기본 0.2초, Development 전체에 동일하게 적용한다."
        ),
    )
    parser.add_argument(
        "--timely-window-sec",
        type=float,
        default=2.0,
        help=(
            "V2 주 지표 timely_recall의 TP 판정 구간 폭(초) — "
            "[fall_start_frame - tolerance, fall_start_frame + 이 값] 밖에서 온 "
            "Event는 late_detection으로만 기록하고 timely TP로 인정하지 않는다. "
            "기본 2.0초, docs/data_sources.md 평균 감지 "
            "지연 목표와 동일하게 둔다."
        ),
    )
    parser.add_argument("--device", default="auto", help="auto | cpu | mps | cuda")
    parser.add_argument(
        "--fall-model-path",
        default=None,
        help=(
            "fine-tuned fall/nofall 2-class detector(fall_detector_v1.pt 등) 경로. "
            "지정하면 AuxiliaryFallModel + IoU 매칭을 통해 model confirm 경로가 "
            "추가로 활성화된다 (src/safety/fall_pipeline.py). 지정하지 않으면 "
            "기존 bbox/pose 전용 동작과 동일하다."
        ),
    )
    parser.add_argument("--fall-model-conf", type=float, default=0.5)
    parser.add_argument("--fall-model-device", default="auto", help="auto | cpu | mps | cuda")
    parser.add_argument(
        "--fall-model-iou-threshold",
        type=float,
        default=0.3,
        help="보조 모델 detection을 Track에 매칭할 최소 IoU (0보다 크고 1 이하).",
    )
    parser.add_argument(
        "--fall-model-interval-frames",
        type=int,
        default=1,
        help="보조 fall/nofall 모델 실행 간격(frame). 1이면 매 frame 실행.",
    )
    parser.add_argument("--output", default="outputs/fall_eval/summary.json")
    parser.add_argument(
        "--include-unreviewed",
        action="store_true",
        help="review_status가 'reviewed'가 아닌 행도 평가에 포함한다.",
    )
    parser.add_argument(
        "--allow-holdout",
        action="store_true",
        help="holdout 데이터를 사용할 때만 명시적으로 허용한다.",
    )
    evaluation_protocol.add_cli_argument(parser)
    return parser.parse_args()


# ----------------------------------------------------------------------
# annotation 로드 및 검증
# ----------------------------------------------------------------------


def _parse_optional_int(value: str) -> Optional[int]:
    value = (value or "").strip()
    return int(value) if value else None


def load_annotations(path: str, include_unreviewed: bool) -> List[_AnnotationRow]:
    with open(path, "r", encoding="utf-8", newline="") as file:
        reader = csv.DictReader(file)
        missing_columns = _REQUIRED_COLUMNS - set(reader.fieldnames or [])
        if missing_columns:
            raise ValueError(f"annotation CSV에 필수 컬럼이 없습니다: {sorted(missing_columns)}")

        rows: List[_AnnotationRow] = []
        for raw in reader:
            review_status = (raw.get("review_status") or "").strip()
            if not include_unreviewed and review_status != "reviewed":
                continue
            rows.append(
                _AnnotationRow(
                    video_id=raw["video_id"].strip(),
                    label=raw["label"].strip(),
                    video_path=raw["video_path"].strip(),
                    fall_start_frame=_parse_optional_int(raw.get("fall_start_frame", "")),
                    impact_frame=_parse_optional_int(raw.get("impact_frame", "")),
                    lying_start_frame=_parse_optional_int(raw.get("lying_start_frame", "")),
                    review_status=review_status,
                    dataset_fall_label_frame=_parse_optional_int(
                        raw.get("dataset_fall_label_frame", "")
                    ),
                )
            )
    return rows


def find_excluded_rows(path: str, include_unreviewed: bool) -> List[Dict[str, str]]:
    """load_annotations()가 review_status 필터로 건너뛴 행을 (video_id, review_status)로 남긴다.

    load_annotations() 자체의 반환 타입은 review_caucafall_annotations.py 등 다른
    호출자와 공유되므로 바꾸지 않는다 — 평가 결과에 "왜 몇 개가 빠졌는지"를 남기려는
    evaluate_fall.py 전용 요구사항이라 별도 함수로 분리했다.
    """
    if include_unreviewed:
        return []
    excluded: List[Dict[str, str]] = []
    with open(path, "r", encoding="utf-8", newline="") as file:
        reader = csv.DictReader(file)
        for raw in reader:
            review_status = (raw.get("review_status") or "").strip()
            if review_status != "reviewed":
                excluded.append(
                    {
                        "video_id": (raw.get("video_id") or "").strip(),
                        "review_status": review_status,
                    }
                )
    return excluded


def validate_annotations(
    rows: List[_AnnotationRow], require_fall_start_frame: bool = True
) -> None:
    """annotation 오류를 조용히 무시하지 않고, 발견된 문제를 모두 모아 한 번에 보고한다.

    require_fall_start_frame=True(기본값, evaluate_fall.py 채점 경로)에서는
    review_status와 무관하게 label=fall 행에 fall_start_frame을 요구한다 —
    --include-unreviewed로 pending 행까지 채점에 넘기면 score_fall_video()가
    `None - int`에서 TypeError로 죽으므로, 그 전에 명확한 오류로 막아야 한다.
    review_caucafall_annotations.py의 자동 저장처럼 아직 검수 중인(onset이
    비어 있어도 되는) 구조 검증만 필요하면 False로 호출한다 — v2 annotation은
    사람이 세 시점을 다 채우기 전까지 pending 상태로 반복 저장되기 때문이다.
    """
    errors: List[str] = []
    seen_ids: Dict[str, int] = {}

    for row in rows:
        if not row.video_id:
            errors.append("video_id가 비어 있는 행이 있습니다.")
            continue
        seen_ids[row.video_id] = seen_ids.get(row.video_id, 0) + 1

        if row.label not in _VALID_LABELS:
            errors.append(
                f"{row.video_id}: label='{row.label}'은(는) {sorted(_VALID_LABELS)} 중 하나여야 합니다."
            )
        if not row.video_path:
            errors.append(f"{row.video_id}: video_path가 비어 있습니다.")

        for name, value in (
            ("fall_start_frame", row.fall_start_frame),
            ("impact_frame", row.impact_frame),
            ("lying_start_frame", row.lying_start_frame),
            ("dataset_fall_label_frame", row.dataset_fall_label_frame),
        ):
            if value is not None and value < 0:
                errors.append(f"{row.video_id}: {name}={value}는 0 이상이어야 합니다.")

        # require_fall_start_frame=False(검수 도구 자동저장)여도 review_status가
        # 이미 reviewed면 예외를 두지 않는다 — pending/needs_review만 onset이
        # 비어 있는 걸 허용하는 게 목적이지, CSV를 손으로 고치거나 손상된 기존
        # 행을 그대로 다시 저장해서 불완전한 reviewed가 남는 걸 봐주면 안 된다.
        if (
            row.label == "fall"
            and row.fall_start_frame is None
            and (require_fall_start_frame or row.review_status == "reviewed")
        ):
            errors.append(f"{row.video_id}: label=fall 행은 fall_start_frame이 필수입니다.")

        ordered_values = [
            (name, value)
            for name, value in (
                ("fall_start_frame", row.fall_start_frame),
                ("impact_frame", row.impact_frame),
                ("lying_start_frame", row.lying_start_frame),
            )
            if value is not None
        ]
        for (name_a, value_a), (name_b, value_b) in zip(ordered_values, ordered_values[1:]):
            if value_a > value_b:
                errors.append(
                    f"{row.video_id}: {name_a}({value_a}) <= {name_b}({value_b})여야 합니다."
                )

    duplicates = sorted(video_id for video_id, count in seen_ids.items() if count > 1)
    if duplicates:
        errors.append(f"중복된 video_id: {duplicates}")

    if errors:
        raise ValueError(
            "annotation 검증 실패 (" + str(len(errors)) + "건):\n  - " + "\n  - ".join(errors)
        )


# ----------------------------------------------------------------------
# holdout 가드
# ----------------------------------------------------------------------


def _contains_holdout_segment(path: Path) -> bool:
    return any(part.lower() == "holdout" for part in path.parts)


def resolve_video_path(row: _AnnotationRow, videos_dir: Path) -> Path:
    """video_path를 절대경로로 만들고 심볼릭 링크를 실제 대상까지 따라간다.

    .resolve()를 호출하지 않으면, development/ 안에 holdout/ 파일을 가리키는
    symlink를 만들어 holdout 가드(_contains_holdout_segment)를 우회할 수 있다.
    """
    video_path = Path(row.video_path)
    if not video_path.is_absolute():
        video_path = videos_dir / video_path
    return video_path.resolve()


def guard_holdout(
    videos_dir: Path, split: str, rows: List[_AnnotationRow], allow_holdout: bool
) -> None:
    # split 이름 자체의 유효성은 allow_holdout과 무관하게 항상 검증한다.
    # allow_holdout=True로 holdout 검사를 건너뛰더라도, 오타난 --split 값까지
    # 조용히 통과시키면 안 되기 때문이다.
    if split and split not in _RECOGNIZED_SPLITS:
        raise SystemExit(
            f"--split='{split}'은(는) {sorted(_RECOGNIZED_SPLITS)} 중 하나여야 합니다."
        )

    if allow_holdout:
        return

    violations: List[str] = []
    if split.lower() == "holdout":
        violations.append("--split holdout")
    if _contains_holdout_segment(videos_dir.resolve()):
        violations.append(f"--videos-dir={videos_dir}")
    for row in rows:
        resolved = resolve_video_path(row, videos_dir)
        if _contains_holdout_segment(resolved):
            violations.append(f"{row.video_id} -> {resolved}")

    if violations:
        raise SystemExit(
            "Subject 9~10(holdout)은 최종 평가 전까지 사용하지 않습니다 "
            "(docs/data_sources.md). 의도한 것이면 --allow-holdout을 지정하세요.\n"
            "감지된 holdout 경로:\n  - " + "\n  - ".join(violations)
        )


# ----------------------------------------------------------------------
# 점수 계산 (cv2/YOLO 없이 단위 테스트 가능한 순수 함수)
# ----------------------------------------------------------------------


def score_fall_video(
    event_frames: List[int],
    fall_start_frame: int,
    impact_frame: Optional[int],
    fps: float,
    early_tolerance_sec: float = 0.0,
) -> Tuple[bool, Optional[float], int, int]:
    """낙상 영상 하나의 Event 목록을 채점한다.

    early_tolerance_sec: fall_start_frame 직전 이 시간(초) 이내의 Event는 이른 오탐이
        아니라 true positive로 인정한다. annotation의 fall_start_frame은 사람이 프레임
        단위로 매긴 라벨이라 실제 낙상 진행 시점과 1~수 프레임 오차가 흔하다 (예:
        S2_fall_sitting frame 79는 라벨 fall_start_frame=81보다 2프레임/0.1초 앞서지만
        직접 확인 결과 이미 낙상이 진행 중인 자세다). 특정 영상 하나만 맞추기 위해
        detector 자체를 늦추면 실제 감지 지연만 나빠지므로, Development 전체에
        동일하게 적용하는 고정값으로 둔다 (기본 0.2초, configs/fall_detection.json
        참고. 라벨링 오차 허용이지 오탐 봐주기가 아니므로 값을 크게 잡지 않는다).

    Returns:
        (detected, latency_sec, early_false_alarms, qualifying_event_count)
        - detected: 허용된 시작 시각 이후 첫 Event가 있으면 True (true positive)
        - latency_sec: 위 첫 Event 기준 감지 지연. impact_frame이 있으면 그 기준,
          없으면 fall_start_frame 기준. 음수를 0으로 자르지 않는다.
        - early_false_alarms: 허용된 시작 시각보다 이전에 발생한 Event 개수
          (낙상이 시작되기도 전에 울린 오탐이므로 true positive로 인정하지 않는다)
        - qualifying_event_count: 허용된 시작 시각 이후 발생한 Event 개수. 이른
          오탐이 섞여 있어도 "낙상 1회당 Event 1회" 판정은 이 값만 봐야 한다
          (early_false_alarms를 포함한 event_count 전체로 판정하면 이른 오탐이
          중복 확정으로 잘못 집계된다).
    """
    tolerance_frames = round(early_tolerance_sec * fps)
    effective_start_frame = fall_start_frame - tolerance_frames

    early_false_alarms = sum(1 for frame in event_frames if frame < effective_start_frame)
    qualifying_frames = [frame for frame in event_frames if frame >= effective_start_frame]

    if not qualifying_frames:
        return False, None, early_false_alarms, 0

    reference_frame = impact_frame if impact_frame is not None else fall_start_frame
    latency_sec = (qualifying_frames[0] - reference_frame) / fps
    return True, latency_sec, early_false_alarms, len(qualifying_frames)


@dataclass
class _TimelyScore:
    timely_detected: bool
    onset_latency_sec: Optional[float]
    lead_to_impact_sec: Optional[float]
    early_false_alarms: int
    late_detection: bool
    duplicate_event: bool
    timely_event_count: int  # within_window(timely 구간 안) Event 개수
    window_start_frame: int
    window_end_frame: int


def score_fall_video_timely(
    event_frames: List[int],
    fall_start_frame: int,
    impact_frame: Optional[int],
    fps: float,
    early_tolerance_sec: float = 0.0,
    timely_window_sec: float = 2.0,
) -> _TimelyScore:
    """평가 프로토콜 V2의 주 지표: [onset - tolerance, onset + timely_window_sec]

    구간 안에 온 Event만 true positive(timely_detected)로 인정한다. 기존
    score_fall_video()는 fall_start_frame 이후 아무 때나 온 Event를 전부
    TP로 인정했는데, 이러면 늦게(예: 10초 뒤) 확정된 Event도 "감지 성공"으로
    잡혀 "낙상 1회당 Event 1회, 제때"라는 실제 운영 요구사항을 반영하지
    못한다. late_detection은 이 경우를 별도로 남기고 TP로 포함하지 않는다.

    early_tolerance_sec의 의미는 score_fall_video()와 동일하다(라벨링 오차 허용).

    duplicate_event는 timely 구간 안으로만 한정하지 않는다 — [정상 timely
    Event, 그 뒤에 늦게 재확정된 Event]도 "낙상 1회당 Event 1회" 계약 위반은
    동일하므로, onset(구간 시작) 이후에 온 Event가 하나라도 더 있으면
    duplicate_event=True다. late_detection은 timely 구간 안에 아무 Event도
    없는데 구간 밖에서만 온 경우로 그대로 유지한다 — 이미
    timely_detected가 True인 영상까지 late로 잘못 잡으면 안 된다.

    Returns:
        _TimelyScore — timely_detected가 True일 때만 onset_latency_sec/
        lead_to_impact_sec가 채워진다.
    """
    if timely_window_sec <= 0:
        raise ValueError(f"timely_window_sec는 0보다 커야 합니다: {timely_window_sec}")
    if early_tolerance_sec < 0:
        raise ValueError(f"early_tolerance_sec는 0 이상이어야 합니다: {early_tolerance_sec}")
    if fps <= 0:
        raise ValueError(f"fps는 0보다 커야 합니다: {fps}")

    tolerance_frames = round(early_tolerance_sec * fps)
    window_frames = round(timely_window_sec * fps)
    window_start_frame = fall_start_frame - tolerance_frames
    window_end_frame = fall_start_frame + window_frames

    early_false_alarms = sum(1 for frame in event_frames if frame < window_start_frame)
    within_window = [
        frame for frame in event_frames if window_start_frame <= frame <= window_end_frame
    ]
    after_window = [frame for frame in event_frames if frame > window_end_frame]
    # early를 제외한 전체 — 시점(구간 안/밖)과 무관하게 onset 이후 Event가
    # 몇 번 왔는지가 "낙상 1회당 Event 1회" 판정 기준이다.
    post_onset_events = within_window + after_window

    timely_detected = bool(within_window)
    late_detection = not timely_detected and bool(after_window)

    onset_latency_sec: Optional[float] = None
    lead_to_impact_sec: Optional[float] = None
    if timely_detected:
        first_frame = within_window[0]
        onset_latency_sec = (first_frame - fall_start_frame) / fps
        if impact_frame is not None:
            lead_to_impact_sec = (impact_frame - first_frame) / fps

    return _TimelyScore(
        timely_detected=timely_detected,
        onset_latency_sec=onset_latency_sec,
        lead_to_impact_sec=lead_to_impact_sec,
        early_false_alarms=early_false_alarms,
        late_detection=late_detection,
        duplicate_event=len(post_onset_events) > 1,
        timely_event_count=len(within_window),
        window_start_frame=window_start_frame,
        window_end_frame=window_end_frame,
    )


_WINDOW_DIAGNOSTICS_POSE_EXTRACTOR = PoseFeatureExtractor()


def summarize_window_diagnostics(
    tracks_by_frame: List[Tuple[int, List[Track]]],
    window_start_frame: int,
    window_end_frame: int,
    pose_min_keypoint_conf: float = 0.3,
) -> Dict[str, Optional[float]]:
    """[window_start_frame, window_end_frame] 구간의 Track 존재/keypoint/ID 안정성을 요약한다.

    tracks_by_frame: (frame_number, tracks) 목록 — _evaluate_video()가 매 프레임
        TrackingResult.tracks를 그대로 모아 넘긴다. cv2/YOLO 실행과 분리해서
        이미 만들어진 Track 목록만 받으므로 순수 함수로 테스트할 수 있다.

    pose_valid는 keypoints 배열이 존재하는지가 아니라, 실제 FallDetector의
    PoseFeatureExtractor가 pose 신호로 채택하는 기준(양쪽 엉덩이 + head
    keypoint 중 하나가 min_keypoint_conf 이상)과 동일하게 판정한다 — 배열만
    있고 신뢰도가 낮아 실제로는 pose confirm 경로에 전혀 쓰이지 못하는
    프레임을 "유효"로 잘못 세지 않기 위함이다. fallen_pose_threshold는
    유효성 판정과 무관해 0.0으로 고정한다 — extract()가 None을 반환하는지만 본다.

    CAUCAFall은 영상당 1인이 기본이라 "낙상 당사자 Track"을 별도로 특정하지
    않고 프레임에 존재하는 모든 Track을 기준으로 계산한다. 다인 상황에서는
    이 근사가 부정확할 수 있다.

    Returns:
        window_frame_count가 0이면(구간이 실제 처리된 프레임과 전혀 안 겹침)
        전부 None을 반환한다 — 0으로 채우면 "Track이 전혀 없었다"와 구분이 안 된다.
    """
    window_frame_count = 0
    no_track_frame_count = 0
    pose_valid_frame_count = 0
    seen_track_ids: List[int] = []

    for frame_number, tracks in tracks_by_frame:
        if not (window_start_frame <= frame_number <= window_end_frame):
            continue
        window_frame_count += 1
        if not tracks:
            no_track_frame_count += 1
            continue
        if any(
            _WINDOW_DIAGNOSTICS_POSE_EXTRACTOR.extract(
                track, fallen_pose_threshold=0.0, min_keypoint_conf=pose_min_keypoint_conf
            )
            is not None
            for track in tracks
        ):
            pose_valid_frame_count += 1
        for track in tracks:
            if track.track_id not in seen_track_ids:
                seen_track_ids.append(track.track_id)

    if window_frame_count == 0:
        return {
            "track_coverage": None,
            "no_track_frame_count": None,
            "id_switch_count": None,
            "pose_valid_frame_ratio": None,
        }

    return {
        "track_coverage": 1.0 - (no_track_frame_count / window_frame_count),
        "no_track_frame_count": no_track_frame_count,
        "id_switch_count": max(0, len(seen_track_ids) - 1),
        "pose_valid_frame_ratio": pose_valid_frame_count / window_frame_count,
    }


def summarize_model_window_diagnostics(
    model_evidence_by_frame: List[Tuple[int, Optional[Dict[int, FallModelEvidence]]]],
    window_start_frame: int,
    window_end_frame: int,
    fps: float,
) -> Dict[str, Optional[float]]:
    """[window_start_frame, window_end_frame] 구간에서 보조 모델 근거가

    얼마나 관측됐고, 그중 fall로 판단된 비율·최장 연속 구간이 얼마인지
    요약한다. 상태머신이 왜 confirm 또는 미확정됐는지 구분하는 데 쓴다:
        - model_fall_observed_ratio가 낮음 -> 모델 fall 신호 자체가 약함
        - track_coverage/id_switch_count(summarize_window_diagnostics)가
          나쁨 -> Track 소실/ID 변경으로 연속성이 끊김
        - model 근거는 충분한데 confirm_path가 model이 아님 -> 상태머신이
          놓침(state machine 쪽 문제)

    CAUCAFall이 영상당 1인 기본이라, 한 프레임에 여러 Track의 evidence가
    있어도 track_coverage와 같은 근사를 쓴다 — 그중 하나라도 label="fall"이면
    그 프레임을 fall로, 하나라도 "fall"|"nofall"(즉 unknown이 아님)이면
    observed로 센다. model_evidence_by_frame이 None인 프레임(보조 모델
    자체를 안 쓴 캐시)은 이 프레임 전체를 관측 대상에서 제외한다.

    Returns:
        window_frame_count가 0이면(구간이 실제 처리된 프레임과 전혀 안 겹침)
        전부 None을 반환한다. 구간 안 모든 프레임의 model_evidence가 None이면
        (보조 모델을 아예 안 쓴 캐시/영상) 마찬가지로 전부 None을 반환한다 —
        "모델을 안 씀"과 "모델은 켜졌지만 전부 unknown(매칭 실패)"을 0으로
        뭉뚱그리면 구분할 수 없다.
    """
    window_frame_count = 0
    observed_frame_count = 0
    fall_frame_count = 0
    max_consecutive_fall_frames = 0
    current_consecutive_fall_frames = 0
    model_used = False

    for frame_number, model_evidence in model_evidence_by_frame:
        if not (window_start_frame <= frame_number <= window_end_frame):
            continue
        window_frame_count += 1
        if model_evidence is not None:
            model_used = True

        labels = [] if model_evidence is None else [e.label for e in model_evidence.values()]
        is_fall = "fall" in labels
        is_observed = is_fall or any(label == "nofall" for label in labels)

        if is_observed:
            observed_frame_count += 1
        if is_fall:
            fall_frame_count += 1
            current_consecutive_fall_frames += 1
            max_consecutive_fall_frames = max(
                max_consecutive_fall_frames, current_consecutive_fall_frames
            )
        else:
            current_consecutive_fall_frames = 0

    if window_frame_count == 0 or not model_used:
        return {
            "model_observed_frame_count": None,
            "model_fall_frame_count": None,
            "model_fall_observed_ratio": None,
            "max_consecutive_model_fall_frames": None,
            "max_consecutive_model_fall_sec": None,
        }

    return {
        "model_observed_frame_count": observed_frame_count,
        "model_fall_frame_count": fall_frame_count,
        "model_fall_observed_ratio": (
            (fall_frame_count / observed_frame_count) if observed_frame_count > 0 else None
        ),
        "max_consecutive_model_fall_frames": max_consecutive_fall_frames,
        "max_consecutive_model_fall_sec": max_consecutive_fall_frames / fps,
    }


# ----------------------------------------------------------------------
# 영상 평가 (실제 cv2/YOLO 파이프라인)
# ----------------------------------------------------------------------


def score_video_from_frame_source(
    row: _AnnotationRow,
    frame_source,
    fps: float,
    config: FallDetectorConfig,
    fall_config_path: Optional[str] = None,
    fall_model_iou_threshold: float = 0.3,
    fall_model_interval_frames: int = 1,
    early_tolerance_sec: float = 0.0,
    timely_window_sec: float = 2.0,
) -> _VideoResult:
    """실제 영상 디코딩(`_evaluate_video`)이든 Signal Cache 재생

    (`scripts/evaluate_fall_from_cache.py`)이든 공통으로 쓰는 채점 경로다.
    두 호출자가 이 함수 하나를 공유해 상태머신 로직이 갈라지지 않게 한다.

    frame_source: (frame_number, tracking_result, raw_detections) 튜플의
        반복자. raw_detections는 보조 모델을 안 쓰면 None(모델 완전
        비활성화와 동일한 의미), 대상 Track이 없었던 프레임이면 빈 리스트
        (모델은 켜져 있지만 매칭할 대상이 없었다는 뜻 — src/safety/fall_pipeline.py
        _compute_model_evidence()와 동일한 구분), 있으면 IoU 매칭 전 원본
        FallDetection 목록이다. 이 함수가 매번 새로 fall_model_iou_threshold로
        매칭하므로, 캐시 재생에서 iou_threshold만 바꿔가며 실험할 수 있다
        (Tracker/matching sweep에서 재사용한다).
    """
    # raw_detections가 있는 프레임에서만 match_detections_to_tracks()가
    # 검증하면, 보조 모델을 안 쓰는 캐시(raw_detections가 매 프레임 None)는
    # 이 값이 끝까지 한 번도 검증되지 않으므로 여기서 먼저 검증한다.
    if not (0.0 < fall_model_iou_threshold <= 1.0):
        raise ValueError(
            f"fall_model_iou_threshold는 0보다 크고 1 이하여야 합니다: "
            f"{fall_model_iou_threshold}"
        )
    validate_auxiliary_inference_interval_frames(fall_model_interval_frames)

    pipeline = FallPipeline(fps=fps, detector_config=config, fall_config_path=fall_config_path)
    evidence_cadence = AuxiliaryEvidenceCadence(fall_model_interval_frames)

    event_frames: List[int] = []
    diagnostics: List[dict] = []
    # Track은 fall/no_fall 둘 다 모은다. no_fall 쪽은 Tracker Sweep에서
    # false Track 증가를 비교하려면 전체 영상 구간의 Track 이력이 필요하다.
    # model evidence는 fall
    # 진단(model_fall_observed_ratio 등) 전용이라 fall 행만 모은다 — no_fall
    # 영상은 길이가 짧아 tracks_by_frame을 늘 모아도 메모리 부담이 크지 않다.
    tracks_by_frame: List[Tuple[int, list]] = []
    model_evidence_by_frame: List[Tuple[int, Optional[Dict[int, FallModelEvidence]]]] = []
    frame_count = 0

    for frame_number, tracking_result, raw_detections in frame_source:
        frame_count += 1
        model_evidence = None
        if raw_detections is not None:
            fresh_evidence = None
            if evidence_cadence.should_infer(frame_number):
                evidence_list = match_detections_to_tracks(
                    tracking_result.tracks, raw_detections, fall_model_iou_threshold
                )
                fresh_evidence = {
                    evidence.track_id: evidence for evidence in evidence_list
                }
            model_evidence = evidence_cadence.resolve(tracking_result, fresh_evidence)
        tracks_by_frame.append((frame_number, tracking_result.tracks))
        if row.label == "fall":
            model_evidence_by_frame.append((frame_number, model_evidence))
        for event in pipeline.process_with_evidence(
            tracking_result, model_evidence, diagnostics=diagnostics
        ):
            event_frames.append(event.frame_number)

    duration_sec = frame_count / fps if fps > 0 else 0.0
    # label과 무관하게 confirm마다 채워진다(FallPipeline.process_with_evidence
    # 호출부, 위 for 루프 참고) — no_fall 오탐과 late_detection의 진단까지
    # 여기서 함께 노출해야 오탐이 model-only 경로인지 결과 JSON만으로
    # 판단할 수 있다.
    event_diagnostics = [
        {
            "frame_number": d["frame_number"],
            "track_id": d["track_id"],
            "confirm_path": d["confirm_path"],
            "candidate_entry_reason": d["candidate_entry_reason"],
            "event_confidence": d["event_confidence"],
            "track_avg_confidence": d["track_avg_confidence"],
            "candidate_duration_sec": d["candidate_duration_sec"],
            "max_descent_score": d["max_descent_score"],
            "horizontal_duration_sec": d["horizontal_duration_sec"],
            "pose_duration_sec": d["pose_duration_sec"],
            "model_duration_sec": d["model_duration_sec"],
            "confirm_aspect_ratio": d["confirm_aspect_ratio"],
            "confirm_height_change_rate": d["confirm_height_change_rate"],
            "confirm_center_vertical_velocity": d["confirm_center_vertical_velocity"],
            "confirm_foot_point_vertical_velocity": d[
                "confirm_foot_point_vertical_velocity"
            ],
        }
        for d in diagnostics
    ]
    video_result = _VideoResult(
        video_id=row.video_id,
        label=row.label,
        event_count=len(event_frames),
        event_frames=event_frames,
        event_diagnostics=event_diagnostics,
        duration_sec=duration_sec,
    )

    if row.label == "fall":
        # validate_annotations()가 label=fall 행의 fall_start_frame 필수를 이미 보장한다.
        detected, latency_sec, early_false_alarms, qualifying_event_count = score_fall_video(
            event_frames, row.fall_start_frame, row.impact_frame, fps, early_tolerance_sec
        )
        video_result.detected = detected
        video_result.latency_sec = latency_sec
        video_result.early_false_alarms = early_false_alarms
        video_result.qualifying_event_count = qualifying_event_count

        timely = score_fall_video_timely(
            event_frames,
            row.fall_start_frame,
            row.impact_frame,
            fps,
            early_tolerance_sec,
            timely_window_sec,
        )
        video_result.timely_detected = timely.timely_detected
        video_result.onset_latency_sec = timely.onset_latency_sec
        video_result.lead_to_impact_sec = timely.lead_to_impact_sec
        video_result.late_detection = timely.late_detection
        video_result.duplicate_event = timely.duplicate_event

        window_diag = summarize_window_diagnostics(
            tracks_by_frame,
            timely.window_start_frame,
            timely.window_end_frame,
            pose_min_keypoint_conf=config.pose_min_keypoint_conf,
        )
        video_result.track_coverage = window_diag["track_coverage"]
        video_result.no_track_frame_count = window_diag["no_track_frame_count"]
        video_result.id_switch_count = window_diag["id_switch_count"]
        video_result.pose_valid_frame_ratio = window_diag["pose_valid_frame_ratio"]

        model_diag = summarize_model_window_diagnostics(
            model_evidence_by_frame, timely.window_start_frame, timely.window_end_frame, fps
        )
        video_result.model_observed_frame_count = model_diag["model_observed_frame_count"]
        video_result.model_fall_frame_count = model_diag["model_fall_frame_count"]
        video_result.model_fall_observed_ratio = model_diag["model_fall_observed_ratio"]
        video_result.max_consecutive_model_fall_frames = model_diag[
            "max_consecutive_model_fall_frames"
        ]
        video_result.max_consecutive_model_fall_sec = model_diag[
            "max_consecutive_model_fall_sec"
        ]

        # timely 구간 안에서 confirm된 이벤트의 진단(candidate 진입 이유/confirm
        # 경로)만 남긴다 — 이른 오탐이나 늦은 재확정의 진단까지 섞이면 "이
        # 낙상이 어떻게 감지됐는가"를 알 수 없다. 여러 개면 그중 첫 번째만 쓴다.
        timely_frames = set(
            range(timely.window_start_frame, timely.window_end_frame + 1)
        )
        matching = [d for d in diagnostics if d["frame_number"] in timely_frames]
        if matching:
            video_result.confirm_path = matching[0]["confirm_path"]
            video_result.candidate_entry_reason = matching[0]["candidate_entry_reason"]
    elif tracks_by_frame:
        # no_fall 행: onset이 없어 timely 구간을 정의할 수 없으므로 영상
        # 전체를 구간으로 쓴다. Tracker Sweep에서 conf를
        # 낮췄을 때 정상 영상에서 false Track(잦은 ID 변경)이 늘어나는지
        # 비교하는 데 쓴다 — confirm_path/candidate_entry_reason처럼 fall
        # 전용인 필드는 채우지 않는다.
        window_diag = summarize_window_diagnostics(
            tracks_by_frame,
            tracks_by_frame[0][0],
            tracks_by_frame[-1][0],
            pose_min_keypoint_conf=config.pose_min_keypoint_conf,
        )
        video_result.track_coverage = window_diag["track_coverage"]
        video_result.no_track_frame_count = window_diag["no_track_frame_count"]
        video_result.id_switch_count = window_diag["id_switch_count"]
        video_result.pose_valid_frame_ratio = window_diag["pose_valid_frame_ratio"]

    return video_result


def _evaluate_video(
    row: _AnnotationRow,
    videos_dir: Path,
    config: FallDetectorConfig,
    tracker,
    early_tolerance_sec: float = 0.0,
    auxiliary_model: Optional[AuxiliaryFallModel] = None,
    fall_model_iou_threshold: float = 0.3,
    fall_model_interval_frames: int = 1,
    fall_config_path: Optional[str] = None,
    timely_window_sec: float = 2.0,
) -> _VideoResult:
    """tracker/auxiliary_model은 호출자가 한 번만 생성해 재사용한다 (YOLO 모델

    로드+warmup 비용을 영상 개수만큼 반복하지 않기 위함). tracker.fps만
    영상별로 갱신한다. auxiliary_model이 None이면(--fall-model-path 미지정)
    기존 bbox/pose 전용 동작과 동일하다 (src/safety/fall_pipeline.py 참고).
    """
    video_path = resolve_video_path(row, videos_dir)

    if not video_path.exists():
        return _VideoResult(
            video_id=row.video_id, label=row.label, event_count=0, error=f"파일 없음: {video_path}"
        )

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return _VideoResult(
            video_id=row.video_id,
            label=row.label,
            event_count=0,
            error=f"영상을 열 수 없음: {video_path}",
        )

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    tracker.fps = fps
    tracker.reset()  # 이전 영상의 track ID/추적 이력이 섞이지 않도록 초기화

    def _live_frame_source():
        frame_number = 0
        try:
            while True:
                ret, frame = cap.read()
                if not ret:
                    break
                result = tracker.update(frame, frame_number, row.video_id)
                raw_detections = None
                if auxiliary_model is not None and auxiliary_model.enabled:
                    # Track이 없으면 매칭할 대상도 없다 — 빈 리스트로 "모델은
                    # 켜져 있지만 이번 프레임엔 대상이 없었다"를 표현한다
                    # (src/safety/fall_pipeline.py _compute_model_evidence()와
                    # 동일한 구분. None과 다르다 — None은 모델 완전 비활성화).
                    should_infer = should_run_auxiliary_inference(
                        frame_number, fall_model_interval_frames
                    )
                    raw_detections = (
                        auxiliary_model.infer(frame)
                        if result.tracks and should_infer
                        else []
                    )
                yield frame_number, result, raw_detections
                frame_number += 1
        finally:
            cap.release()

    return score_video_from_frame_source(
        row,
        _live_frame_source(),
        fps,
        config,
        fall_config_path=fall_config_path,
        fall_model_iou_threshold=fall_model_iou_threshold,
        fall_model_interval_frames=fall_model_interval_frames,
        early_tolerance_sec=early_tolerance_sec,
        timely_window_sec=timely_window_sec,
    )


def video_result_to_dict(result: _VideoResult) -> dict:
    """결과 JSON의 "videos" 배열 원소 하나. `main()`과

    `scripts/evaluate_fall_from_cache.py`가 동일한 출력 형식을 쓰도록
    공유한다(둘 중 하나만 고쳐서 형식이 갈라지는 걸 막기 위함).
    """
    return {
        "video_id": result.video_id,
        "label": result.label,
        "event_count": result.event_count,
        "event_frames": result.event_frames,
        "event_diagnostics": result.event_diagnostics,
        "duration_sec": result.duration_sec,
        "detected": result.detected,
        "latency_sec": result.latency_sec,
        "early_false_alarms": result.early_false_alarms,
        "qualifying_event_count": result.qualifying_event_count,
        "timely_detected": result.timely_detected,
        "onset_latency_sec": result.onset_latency_sec,
        "lead_to_impact_sec": result.lead_to_impact_sec,
        "late_detection": result.late_detection,
        "duplicate_event": result.duplicate_event,
        "confirm_path": result.confirm_path,
        "candidate_entry_reason": result.candidate_entry_reason,
        "track_coverage": result.track_coverage,
        "no_track_frame_count": result.no_track_frame_count,
        "id_switch_count": result.id_switch_count,
        "pose_valid_frame_ratio": result.pose_valid_frame_ratio,
        "model_observed_frame_count": result.model_observed_frame_count,
        "model_fall_frame_count": result.model_fall_frame_count,
        "model_fall_observed_ratio": result.model_fall_observed_ratio,
        "max_consecutive_model_fall_frames": result.max_consecutive_model_fall_frames,
        "max_consecutive_model_fall_sec": result.max_consecutive_model_fall_sec,
        "error": result.error,
    }


def _summarize(results: List[_VideoResult]) -> dict:
    fall_results = [r for r in results if r.label == "fall" and r.error is None]
    no_fall_results = [r for r in results if r.label == "no_fall" and r.error is None]
    errored = [r for r in results if r.error is not None]

    detected = [r for r in fall_results if r.detected]
    recall = (len(detected) / len(fall_results)) if fall_results else None

    # true positive(qualifying_event_count) 이후 추가로 발생한 Event만 "중복 확정"으로
    # 집계한다. event_count(전체)를 쓰면 이른 오탐이 섞인 영상도 중복으로 잘못 잡힌다.
    multi_event_falls = [r for r in fall_results if r.detected and r.qualifying_event_count > 1]
    total_early_false_alarms = sum(r.early_false_alarms for r in fall_results)

    total_no_fall_minutes = sum(r.duration_sec for r in no_fall_results) / 60.0
    total_false_alarms = sum(r.event_count for r in no_fall_results)
    false_alarm_per_min = (
        (total_false_alarms / total_no_fall_minutes) if total_no_fall_minutes > 0 else None
    )

    latencies = [r.latency_sec for r in detected if r.latency_sec is not None]
    avg_latency_sec = statistics.mean(latencies) if latencies else None

    # --- V2(timely) 주 지표. 기존 unbounded
    # recall/latency는 위에서 그대로 유지하고, 아래는 별도 키로 추가한다.
    timely_detected = [r for r in fall_results if r.timely_detected]
    timely_recall = (
        (len(timely_detected) / len(fall_results)) if fall_results else None
    )
    onset_latencies = [
        r.onset_latency_sec for r in timely_detected if r.onset_latency_sec is not None
    ]
    avg_onset_latency_sec = statistics.mean(onset_latencies) if onset_latencies else None
    lead_to_impact_values = [
        r.lead_to_impact_sec for r in timely_detected if r.lead_to_impact_sec is not None
    ]
    avg_lead_to_impact_sec = (
        statistics.mean(lead_to_impact_values) if lead_to_impact_values else None
    )
    late_detections = [r for r in fall_results if r.late_detection]
    duplicate_events = [r for r in fall_results if r.duplicate_event]

    # 영상 처리 자체가 실패한 오류가 하나라도 있으면, 분모에서 제외됐다는 이유로
    # 목표 달성 여부를 신뢰할 수 없다. evaluation_valid=False일 때는 목표 달성
    # 플래그를 전부 False로 강제해 "일부만 성공했는데 목표 달성"으로 오인하지 않게 한다.
    evaluation_valid = len(errored) == 0
    recall_meets_target = evaluation_valid and recall is not None and recall >= 0.75
    false_alarm_meets_target = (
        evaluation_valid and false_alarm_per_min is not None and false_alarm_per_min <= 0.2
    )
    latency_meets_target = (
        evaluation_valid and avg_latency_sec is not None and avg_latency_sec <= 2.0
    )
    timely_recall_meets_target = (
        evaluation_valid and timely_recall is not None and timely_recall >= 0.75
    )

    return {
        "evaluation_valid": evaluation_valid,
        "fall_videos": len(fall_results),
        "no_fall_videos": len(no_fall_results),
        "skipped_with_error": len(errored),
        "recall": recall,
        "false_alarm_per_min": false_alarm_per_min,
        "avg_detection_latency_sec": avg_latency_sec,
        "falls_with_multiple_events": len(multi_event_falls),
        "early_false_alarms_in_fall_videos": total_early_false_alarms,
        "recall_meets_target_75pct": recall_meets_target,
        "false_alarm_meets_target_0.2": false_alarm_meets_target,
        "latency_meets_target_2sec": latency_meets_target,
        "timely_recall": timely_recall,
        "timely_recall_meets_target_75pct": timely_recall_meets_target,
        "avg_onset_latency_sec": avg_onset_latency_sec,
        "avg_lead_to_impact_sec": avg_lead_to_impact_sec,
        "late_detections": len(late_detections),
        "duplicate_events": len(duplicate_events),
    }


def _build_live_protocol_metadata(
    args,
    annotation_schema_version: str,
    tracker,
    tracker_model_path: str,
    auxiliary_model,
) -> dict:
    tracker_config = {
        "tracker_type": args.tracker,
        "model_path": tracker_model_path,
        "model_sha256": evaluation_protocol.sha256_file(tracker_model_path),
        "conf": args.conf,
        "tracker_config": getattr(tracker, "tracker_config", "bytetrack.yaml"),
        "tracker_config_sha256": evaluation_protocol.sha256_file(
            getattr(tracker, "tracker_config", "bytetrack.yaml")
        ),
    }
    return evaluation_protocol.build_metadata(
        annotation_schema_version=annotation_schema_version,
        model_sha256=evaluation_protocol.sha256_file(args.fall_model_path),
        config_path=args.config,
        tracker=args.tracker,
        tracker_config=tracker_config,
        device={
            "tracker": getattr(tracker, "_device", args.device),
            "auxiliary_model": getattr(
                auxiliary_model, "_device", args.fall_model_device
            ),
            "evaluation": "live",
        },
    )


def main() -> None:
    args = parse_args()

    # score_fall_video_timely()도 이 값들을 검증하지만, 그건 영상 개수만큼
    # YOLO를 다 돌린 뒤(_evaluate_video 안에서)에야 처음 호출된다 — CLI 오타는
    # 모델 로딩·영상 처리 전에 여기서 바로 잡아야 몇 분을 낭비하지 않는다.
    if args.timely_window_sec <= 0:
        raise SystemExit(f"--timely-window-sec는 0보다 커야 합니다: {args.timely_window_sec}")
    if args.early_tolerance_sec < 0:
        raise SystemExit(f"--early-tolerance-sec는 0 이상이어야 합니다: {args.early_tolerance_sec}")
    try:
        validate_auxiliary_inference_interval_frames(args.fall_model_interval_frames)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    try:
        annotation_schema_version = evaluation_protocol.validate_protocol_request(
            args.evaluation_protocol_version,
            args.annotations,
            args.early_tolerance_sec,
            args.timely_window_sec,
            args.include_unreviewed,
        )
    except (OSError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc

    videos_dir = Path(args.videos_dir)
    config = FallDetectorConfig.from_file(args.config)
    try:
        rows = load_annotations(args.annotations, include_unreviewed=args.include_unreviewed)
        excluded_rows = find_excluded_rows(
            args.annotations, include_unreviewed=args.include_unreviewed
        )
        if not rows:
            raise ValueError("평가할 annotation 행이 없습니다 (review_status='reviewed' 확인).")
        validate_annotations(rows)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    guard_holdout(videos_dir, args.split, rows, args.allow_holdout)

    print(f"[{args.split or videos_dir.name}] {len(rows)}개 영상 평가 시작")

    # tracker는 전체 실행에서 한 번만 만든다 (YOLO 모델 로드+warmup 비용을
    # 영상 개수만큼 반복하지 않기 위함). fps=30.0은 첫 영상 처리 시 실제
    # fps로 바로 덮어써지는 placeholder일 뿐이다.
    tracker_cls = PoseTracker if args.tracker == "pose" else ByteTracker
    default_model = "yolo26n-pose.pt" if args.tracker == "pose" else "yolo26n.pt"
    model_path = args.model or default_model
    tracker = tracker_cls(model_path=model_path, conf=args.conf, fps=30.0, device=args.device)

    # --fall-model-path를 지정한 경우에만 만든다 (전체 실행에서 한 번만 만들어
    # tracker와 마찬가지로 영상마다 재로딩하지 않는다). 지정하지 않으면 None —
    # FallPipeline이 이를 기존 bbox/pose 전용 동작으로 취급한다.
    auxiliary_model = None
    if args.fall_model_path is not None:
        auxiliary_model = AuxiliaryFallModel(
            model_path=args.fall_model_path,
            conf=args.fall_model_conf,
            device=args.fall_model_device,
            enabled=True,
        )

    protocol_metadata = {}
    if annotation_schema_version is not None:
        try:
            protocol_metadata = _build_live_protocol_metadata(
                args,
                annotation_schema_version,
                tracker,
                model_path,
                auxiliary_model,
            )
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc

    results: List[_VideoResult] = []
    for i, row in enumerate(rows, start=1):
        print(f"  ({i}/{len(rows)}) {row.video_id} [{row.label}] 처리 중...")
        result = _evaluate_video(
            row,
            videos_dir,
            config,
            tracker,
            early_tolerance_sec=args.early_tolerance_sec,
            auxiliary_model=auxiliary_model,
            fall_model_iou_threshold=args.fall_model_iou_threshold,
            fall_model_interval_frames=args.fall_model_interval_frames,
            fall_config_path=args.config,
            timely_window_sec=args.timely_window_sec,
        )
        if result.error:
            print(f"    스킵: {result.error}")
        results.append(result)

    summary = _summarize(results)
    summary.update(protocol_metadata)
    summary["split"] = args.split or videos_dir.name
    # 재현성: 이 결과를 만든 조건을 함께 남긴다 (같은 annotation이라도 model/conf/config가
    # 다르면 다른 결과가 나올 수 있으므로).
    summary["run_config"] = {
        "tracker": args.tracker,
        "model": model_path,
        "conf": args.conf,
        "device": args.device,
        "config_path": args.config,
        "annotations_path": args.annotations,
        "videos_dir": str(videos_dir),
        "early_tolerance_sec": args.early_tolerance_sec,
        "timely_window_sec": args.timely_window_sec,
        "fall_model_path": args.fall_model_path,
        "fall_model_conf": args.fall_model_conf if args.fall_model_path else None,
        "fall_model_device": args.fall_model_device if args.fall_model_path else None,
        "fall_model_iou_threshold": (
            args.fall_model_iou_threshold if args.fall_model_path else None
        ),
        "fall_model_interval_frames": (
            args.fall_model_interval_frames if args.fall_model_path else None
        ),
    }
    summary["excluded_from_evaluation"] = {
        "count": len(excluded_rows),
        "videos": excluded_rows,
    }
    summary["videos"] = [video_result_to_dict(r) for r in results]

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as file:
        json.dump(summary, file, ensure_ascii=False, indent=2)

    print("\n=== 결과 요약 ===")
    print(f"  평가 유효성(오류 영상 없음): {summary['evaluation_valid']}")
    print(f"  Recall: {summary['recall']} (목표 >= 0.75)")
    print(f"  False alarm/분: {summary['false_alarm_per_min']} (목표 <= 0.2)")
    print(f"  평균 감지 지연(초, 기존 unbounded): {summary['avg_detection_latency_sec']} (목표 <= 2.0)")
    print(f"  낙상 확정 후 중복 Event 발생한 영상 수(기존 unbounded): {summary['falls_with_multiple_events']}")
    print(f"  낙상 시작 전 이른 오탐: {summary['early_false_alarms_in_fall_videos']}건")
    print(f"  스킵된 영상: {summary['skipped_with_error']}")
    print(
        f"  timely_recall: {summary['timely_recall']} "
        f"(목표 >= 0.75, window={args.timely_window_sec}초)"
    )
    print(f"  평균 onset 지연(초): {summary['avg_onset_latency_sec']}")
    print(f"  평균 impact까지 lead time(초): {summary['avg_lead_to_impact_sec']}")
    print(f"  timely 구간 밖 늦은 확정(late_detection): {summary['late_detections']}건")
    print(f"  낙상당 중복 확정(duplicate_event): {summary['duplicate_events']}건")
    if excluded_rows:
        excluded_ids = ", ".join(f"{r['video_id']}({r['review_status']})" for r in excluded_rows)
        print(f"  review_status로 평가에서 제외된 영상 {len(excluded_rows)}건: {excluded_ids}")
    print(f"\n결과 저장: {output_path}")

    if not summary["evaluation_valid"]:
        raise SystemExit(
            f"{summary['skipped_with_error']}개 영상 처리 실패로 평가 결과를 신뢰할 수 "
            "없습니다 (목표 달성 여부는 모두 False로 처리됨). 결과 파일에서 error를 "
            "확인해 원인을 해결한 뒤 다시 실행하세요."
        )


if __name__ == "__main__":
    main()
