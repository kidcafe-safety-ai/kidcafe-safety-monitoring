"""FallDetector를 CAUCAFall(또는 동일 형식) 영상 세트에 대해 평가한다.

CAUCAFall 자체는 낙상 시작/충격/누운 시점 라벨을 제공하지 않으므로
(docs/roadmap.md, 마스터 가이드 7번 참고), 팀이 직접 검토해 만든 annotation
CSV가 필요하다. CSV 형식 (7개 컬럼 모두 필수, 값은 비워둘 수 있음):

    video_id,label,video_path,fall_start_frame,impact_frame,lying_start_frame,review_status

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

주의: Subject 9~10(holdout)은 PR4 최종 평가 전까지 사용하지 않는다
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

from src.safety.auxiliary_fall_model import AuxiliaryFallModel  # noqa: E402
from src.safety.fall_detector import FallDetectorConfig  # noqa: E402
from src.safety.fall_pipeline import FallPipeline  # noqa: E402
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


@dataclass
class _VideoResult:
    video_id: str
    label: str
    event_count: int
    event_frames: List[int] = field(default_factory=list)
    detected: bool = False
    latency_sec: Optional[float] = None
    early_false_alarms: int = 0
    qualifying_event_count: int = 0  # fall_start_frame 이후에 발생한 Event 개수
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


def validate_annotations(rows: List[_AnnotationRow]) -> None:
    """annotation 오류를 조용히 무시하지 않고, 발견된 문제를 모두 모아 한 번에 보고한다."""
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
        ):
            if value is not None and value < 0:
                errors.append(f"{row.video_id}: {name}={value}는 0 이상이어야 합니다.")

        if row.label == "fall" and row.fall_start_frame is None:
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
            "Subject 9~10(holdout)은 PR4 최종 평가 전까지 사용하지 않습니다 "
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


# ----------------------------------------------------------------------
# 영상 평가 (실제 cv2/YOLO 파이프라인)
# ----------------------------------------------------------------------


def _evaluate_video(
    row: _AnnotationRow,
    videos_dir: Path,
    config: FallDetectorConfig,
    tracker,
    early_tolerance_sec: float = 0.0,
    auxiliary_model: Optional[AuxiliaryFallModel] = None,
    fall_model_iou_threshold: float = 0.3,
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
    pipeline = FallPipeline(
        fps=fps,
        detector_config=config,
        auxiliary_model=auxiliary_model,
        iou_threshold=fall_model_iou_threshold,
    )

    event_frames: List[int] = []
    frame_number = 0
    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            result = tracker.update(frame, frame_number, row.video_id)
            for event in pipeline.process(frame, result):
                event_frames.append(event.frame_number)
            frame_number += 1
    finally:
        cap.release()

    duration_sec = frame_number / fps if fps > 0 else 0.0
    video_result = _VideoResult(
        video_id=row.video_id,
        label=row.label,
        event_count=len(event_frames),
        event_frames=event_frames,
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

    return video_result


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
    }


def main() -> None:
    args = parse_args()

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
        )
        if result.error:
            print(f"    스킵: {result.error}")
        results.append(result)

    summary = _summarize(results)
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
        "fall_model_path": args.fall_model_path,
        "fall_model_conf": args.fall_model_conf if args.fall_model_path else None,
        "fall_model_device": args.fall_model_device if args.fall_model_path else None,
        "fall_model_iou_threshold": (
            args.fall_model_iou_threshold if args.fall_model_path else None
        ),
    }
    summary["excluded_from_evaluation"] = {
        "count": len(excluded_rows),
        "videos": excluded_rows,
    }
    summary["videos"] = [
        {
            "video_id": r.video_id,
            "label": r.label,
            "event_count": r.event_count,
            "event_frames": r.event_frames,
            "duration_sec": r.duration_sec,
            "detected": r.detected,
            "latency_sec": r.latency_sec,
            "early_false_alarms": r.early_false_alarms,
            "qualifying_event_count": r.qualifying_event_count,
            "error": r.error,
        }
        for r in results
    ]

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as file:
        json.dump(summary, file, ensure_ascii=False, indent=2)

    print("\n=== 결과 요약 ===")
    print(f"  평가 유효성(오류 영상 없음): {summary['evaluation_valid']}")
    print(f"  Recall: {summary['recall']} (목표 >= 0.75)")
    print(f"  False alarm/분: {summary['false_alarm_per_min']} (목표 <= 0.2)")
    print(f"  평균 감지 지연(초): {summary['avg_detection_latency_sec']} (목표 <= 2.0)")
    print(f"  낙상 확정 후 중복 Event 발생한 영상 수: {summary['falls_with_multiple_events']}")
    print(f"  낙상 시작 전 이른 오탐: {summary['early_false_alarms_in_fall_videos']}건")
    print(f"  스킵된 영상: {summary['skipped_with_error']}")
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
