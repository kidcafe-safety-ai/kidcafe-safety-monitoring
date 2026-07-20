"""Development 영상에서 여러 tracker confidence 값을 비교한다.

한 번에 하나의 변수만 비교하기 위해 이 도구는 ``--conf-values``만 바꾼다.
ByteTrack 설정 비교는 별도 캐시 디렉터리에서 수행해야 한다. 모델 선택과 최종
평가의 데이터 경계를 지키기 위해 Subject 1~6 이외의 입력은 거부한다.

conf 값마다 다음을 순서대로 한다:
    1. scripts/cache_fall_signals.py로 <cache-base-dir>/conf_<C>/ 캐싱 (처리
       FPS도 이때 timing_report.json으로 함께 기록됨)
    2. scripts/evaluate_fall_from_cache.py로 그 캐시를 평가

둘 다 기존 CLI를 서브프로세스로 재사용하며 평가 로직을 복제하지 않는다.

측정값:
    - fall 영상 timely 구간 평균 track_coverage / id_switch_count
    - no_fall 영상 전체 구간 평균 id_switch_count(false Track 비율의 근사)
    - Recall(timely) / false_alarm_per_min
    - 처리 FPS(cold-start 포함, 이번 실행에서 전체 영상을 새로 캐싱했을 때만
      신뢰할 수 있다 — 일부만 새로 캐싱됐으면 N/A로 표시한다)

Usage:
    .venv/bin/python scripts/tracker_sweep.py \
        --annotations data/annotations/caucafall_v5/development_annotations_v2.csv \
        --videos-dir data/datasets/caucafall/v5/development \
        --split development \
        --conf-values 0.5,0.25,0.1 \
        --fall-model-path outputs/fall_training/models/fall_detector_v1.pt \
        --cache-base-dir outputs/fall_eval/cache/tracker_sweep \
        --output outputs/fall_eval/tracker_sweep_summary.json
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

_SCRIPTS_DIR = Path(__file__).resolve().parent
# docs/data_sources.md Subject 분할의 단일 기준(configs/caucafall_v5_split.json)과
# 어긋나지 않아야 하지만, 이 스크립트는 최소한의 안전장치로 development
# Subject 목록을 하드코딩해 둔다 — video_id 접두사(S1~S6)만으로 충분히
# 검증되므로 설정 파일까지 읽는 번거로움을 피한다.
_DEVELOPMENT_SUBJECTS = {1, 2, 3, 4, 5, 6}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--annotations", required=True)
    parser.add_argument("--videos-dir", required=True)
    parser.add_argument("--split", default="")
    parser.add_argument(
        "--conf-values",
        required=True,
        help="쉼표로 구분한 tracker conf 목록, 예: 0.5,0.25,0.1",
    )
    parser.add_argument("--tracker", default="pose", choices=["bbox", "pose"])
    parser.add_argument("--model", default=None)
    parser.add_argument("--device", default="auto")
    parser.add_argument("--fall-model-path", default=None)
    parser.add_argument("--fall-model-conf", type=float, default=0.5)
    parser.add_argument("--fall-model-device", default="auto")
    parser.add_argument("--fall-model-iou-threshold", type=float, default=0.3)
    parser.add_argument("--config", default="configs/fall_detection.json")
    parser.add_argument("--early-tolerance-sec", type=float, default=0.2)
    parser.add_argument("--timely-window-sec", type=float, default=2.0)
    parser.add_argument("--cache-base-dir", required=True)
    parser.add_argument("--output", default="outputs/fall_eval/tracker_sweep_summary.json")
    parser.add_argument("--include-unreviewed", action="store_true")
    # --allow-holdout은 의도적으로 없다 — 이 스크립트는 Development(Subject
    # 1~6) 전용이고 guard_development_only()가 그 외 video_id를 전부
    # 거부하므로 holdout을 허용하는 옵션도 제공하지 않는다.
    parser.add_argument(
        "--force", action="store_true", help="conf별 캐시 디렉터리를 전부 다시 생성한다."
    )
    return parser.parse_args()


def _subject_number(video_id: str) -> Optional[int]:
    """"S7_fall_backwards" -> 7. 접두사가 S<숫자>_ 형식이 아니면 None."""
    if not video_id.startswith("S"):
        return None
    digits = ""
    for char in video_id[1:]:
        if char.isdigit():
            digits += char
        else:
            break
    return int(digits) if digits else None


def guard_development_only(split: str, annotations_path: str) -> None:
    """Tracker Sweep 입력을 Development(Subject 1~6)로 제한한다.

    ``--split`` 문자열뿐 아니라 annotation의 실제 ``video_id``도 확인해
    잘못 지정한 분할이 조용히 통과하지 않게 한다.
    """
    if split != "development":
        raise SystemExit(
            f"--split='{split}'는 허용되지 않습니다. Tracker Sweep은 Development에서만 "
            "돌립니다 — Validation(Subject 7~8)을 conf 비교·선택에 쓰면 그 자체가 "
            "Validation으로 튜닝하는 것과 같습니다. 설정을 정한 뒤에는 "
            "scripts/evaluate_fall_from_cache.py로 Validation을 딱 한 번만 평가하세요."
        )

    with open(annotations_path, "r", encoding="utf-8", newline="") as file:
        reader = csv.DictReader(file)
        offending = sorted(
            {
                row["video_id"]
                for row in reader
                if _subject_number(row["video_id"]) not in _DEVELOPMENT_SUBJECTS
            }
        )
    if offending:
        raise SystemExit(
            f"{annotations_path}에 Development(Subject 1~6)가 아닌 video_id가 있습니다: "
            f"{offending[:5]}{'...' if len(offending) > 5 else ''}. --split=development와 "
            "일치하는 annotation CSV를 쓰세요."
        )


def _parse_conf_values(raw: str) -> List[float]:
    values = []
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        value = float(token)
        if not (0.0 < value <= 1.0):
            raise ValueError(f"--conf-values 항목은 0보다 크고 1 이하여야 합니다: {value}")
        values.append(value)
    if not values:
        raise ValueError("--conf-values에 값이 하나도 없습니다.")
    return values


def _run(cmd: List[str]) -> int:
    print(f"  $ {' '.join(cmd)}")
    result = subprocess.run(cmd)
    return result.returncode


def _cache_dir_for(cache_base_dir: Path, conf: float) -> Path:
    return cache_base_dir / f"conf_{conf}"


def run_one_conf(conf: float, args: argparse.Namespace) -> dict:
    cache_dir = _cache_dir_for(Path(args.cache_base_dir), conf)

    cache_cmd = [
        sys.executable,
        str(_SCRIPTS_DIR / "cache_fall_signals.py"),
        "--annotations", args.annotations,
        "--videos-dir", args.videos_dir,
        "--split", args.split,
        "--tracker", args.tracker,
        "--conf", str(conf),
        "--device", args.device,
        "--cache-dir", str(cache_dir),
    ]
    if args.model:
        cache_cmd += ["--model", args.model]
    if args.fall_model_path:
        cache_cmd += [
            "--fall-model-path", args.fall_model_path,
            "--fall-model-conf", str(args.fall_model_conf),
            "--fall-model-device", args.fall_model_device,
        ]
    if args.include_unreviewed:
        cache_cmd += ["--include-unreviewed"]
    if args.force:
        cache_cmd += ["--force"]

    # 기존 timing_report.json을 지우지 않으면, 이번 실행에서 캐시가 전부
    # 이미 있어(cache_fall_signals.py가 아무것도 새로 캐싱하지 않아) 새
    # timing_report.json을 안 쓰는 경우 지난 실행(다른 하드웨어 상태·다른
    # conf 재사용 전)의 FPS가 이번 결과인 것처럼 남는다.
    timing_path = cache_dir / "timing_report.json"
    timing_path.unlink(missing_ok=True)

    cache_rc = _run(cache_cmd)
    if cache_rc != 0:
        return {"conf": conf, "error": f"cache_fall_signals.py 실패(exit={cache_rc})"}

    eval_output = cache_dir / "eval_summary.json"
    eval_cmd = [
        sys.executable,
        str(_SCRIPTS_DIR / "evaluate_fall_from_cache.py"),
        "--annotations", args.annotations,
        "--cache-dir", str(cache_dir),
        "--split", args.split,
        "--config", args.config,
        "--early-tolerance-sec", str(args.early_tolerance_sec),
        "--timely-window-sec", str(args.timely_window_sec),
        "--fall-model-iou-threshold", str(args.fall_model_iou_threshold),
        "--output", str(eval_output),
    ]
    if args.include_unreviewed:
        eval_cmd += ["--include-unreviewed"]

    # eval_output이 이전 실행(다른 conf 재사용 전, 또는 실패한 과거 실행)의
    # 결과일 수 있다 — subprocess가 main() 시작 전에(예: 인자 검증) 죽으면
    # 새로 안 써지므로 실행 전에 지우고 새로 생성됐는지 확인한다. exit code가
    # 0이 아니어도 evaluation_valid=False 결과 파일은 생성될 수 있다.
    eval_output.unlink(missing_ok=True)
    eval_rc = _run(eval_cmd)
    if not eval_output.exists():
        return {
            "conf": conf,
            "error": f"evaluate_fall_from_cache.py가 결과 파일을 만들지 못함(exit={eval_rc})",
        }

    summary = json.loads(eval_output.read_text())
    # exit code와 evaluation_valid를 모두 확인해 불완전한 결과를 거부한다.
    if eval_rc != 0 or not summary["evaluation_valid"]:
        return {
            "conf": conf,
            "error": (
                f"평가 실패(exit={eval_rc}, evaluation_valid={summary['evaluation_valid']}, "
                f"skipped_with_error={summary['skipped_with_error']}) — 결과 파일: {eval_output}"
            ),
        }

    timing = json.loads(timing_path.read_text()) if timing_path.exists() else None
    # 일부 영상만 이번 실행에서 새로 캐싱됐으면(나머지는 건너뜀) FPS가 이번
    # conf의 처리 속도를 대표하지 못하므로 N/A로 남긴다.
    fps_avg = timing["fps_avg"] if timing and timing.get("skipped_count", 0) == 0 else None

    fall_videos = [v for v in summary["videos"] if v["label"] == "fall" and v["error"] is None]
    no_fall_videos = [
        v for v in summary["videos"] if v["label"] == "no_fall" and v["error"] is None
    ]
    track_coverages = [
        v["track_coverage"] for v in fall_videos if v["track_coverage"] is not None
    ]
    fall_id_switches = [
        v["id_switch_count"] for v in fall_videos if v["id_switch_count"] is not None
    ]
    no_fall_id_switches = [
        v["id_switch_count"] for v in no_fall_videos if v["id_switch_count"] is not None
    ]

    return {
        "conf": conf,
        "cache_dir": str(cache_dir),
        "evaluation_valid": summary["evaluation_valid"],
        "skipped_with_error": summary["skipped_with_error"],
        "recall": summary["recall"],
        "timely_recall": summary["timely_recall"],
        "false_alarm_per_min": summary["false_alarm_per_min"],
        "avg_fall_track_coverage": (
            statistics.mean(track_coverages) if track_coverages else None
        ),
        "avg_fall_id_switch_count": (
            statistics.mean(fall_id_switches) if fall_id_switches else None
        ),
        "avg_no_fall_id_switch_count": (
            statistics.mean(no_fall_id_switches) if no_fall_id_switches else None
        ),
        "fps_avg": fps_avg,
    }


def main() -> None:
    args = parse_args()
    conf_values = _parse_conf_values(args.conf_values)
    guard_development_only(args.split, args.annotations)

    results = []
    for i, conf in enumerate(conf_values, start=1):
        print(f"[{i}/{len(conf_values)}] conf={conf}")
        results.append(run_one_conf(conf, args))

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as file:
        json.dump({"split": args.split, "results": results}, file, ensure_ascii=False, indent=2)

    print("\n=== Tracker Sweep 비교 ===")
    header = (
        f"{'conf':>6} {'timely_recall':>13} {'FAR/min':>9} {'fall_track_cov':>15} "
        f"{'fall_id_sw':>10} {'no_fall_id_sw':>13} {'FPS':>8}"
    )
    print(header)
    for r in results:
        if "error" in r:
            print(f"{r['conf']:>6} 오류: {r['error']}")
            continue

        def _fmt(value: Optional[float], digits: int = 3) -> str:
            return "N/A" if value is None else f"{value:.{digits}f}"

        far = _fmt(r["false_alarm_per_min"], 2)
        track_cov = _fmt(r["avg_fall_track_coverage"])
        fall_sw = _fmt(r["avg_fall_id_switch_count"], 2)
        no_fall_sw = _fmt(r["avg_no_fall_id_switch_count"], 2)
        fps = _fmt(r["fps_avg"], 1)
        print(
            f"{r['conf']:>6} {_fmt(r['timely_recall']):>13} {far:>9} "
            f"{track_cov:>15} {fall_sw:>10} {no_fall_sw:>13} {fps:>8}"
        )
    print(f"\n결과 저장: {output_path}")

    failed = [r for r in results if "error" in r]
    if failed:
        raise SystemExit(
            f"{len(failed)}/{len(results)}개 conf가 실패/무효였습니다 — 결과 파일에서 "
            "error를 확인하세요. 비교표의 나머지 행은 그대로 신뢰할 수 있습니다."
        )


if __name__ == "__main__":
    main()
