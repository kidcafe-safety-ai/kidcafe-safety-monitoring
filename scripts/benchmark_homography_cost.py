"""Homography 경로가 Zone 판정에 더하는 frame당 비용을 측정한다.

`homography_acceptance_v1`의 `max_added_latency_ms_per_frame`(1.0ms)을 보기
위한 microbenchmark다. 촬영 데이터와 무관하게 Zone 판정 연산만 잰다.

**FPS 하락률은 이 스크립트로 측정할 수 없다.** 계약은 하락률을
`(기존 FPS - 후보 FPS) / 기존 FPS`로 정의하는데, 두 FPS 모두 같은 영상을 같은
조건으로 실행해 얻은 실측값이어야 한다. 여기서 내는 값은 추가 비용을
`--baseline-fps`가 나타내는 frame 예산에 더해 역산한 **추정치**이고, 출력에
`measurement_type: "estimated"`로 표시한다. 공식 FPS 판정에 쓰지 않는다.

실측을 하려면 image-coordinate 경로와 Homography 경로가 모두 production
파이프라인에 연결돼 있어야 하는데, `FloorZoneChecker`는 `src/main.py`에
연결돼 있지 않다. ADR-023이 production 확장을 채택 이후 별도 PR로 미뤘고
이번 PoC는 미채택이므로 그 연결을 만들지 않는다.

비교 대상은 Track 하나의 `foot_point`를 Zone 판정까지 보내는 경로 전체다.

- 기존: 픽셀 foot point를 정규화해 image polygon으로 판정
- Homography: 픽셀 foot point를 floor 좌표로 변환해 floor polygon으로 판정

두 Zone은 `pick_zone_polygon.py`가 같은 클릭에서 만든 파일을 써야 한다. 서로
다른 클릭으로 만든 Zone을 비교하면 판정 비용이 아니라 폴리곤 복잡도 차이를
재게 된다.

부호 규칙은 `docs/homography_calibration.md` 6절을 따른다. 추가 비용과 FPS
하락률은 기준선 대비 차이라 Homography 경로가 더 빠르면 음수가 나오며, 그대로
기록한다.

사용 예:

    python scripts/benchmark_homography_cost.py \\
        --calibration configs/camera_calibration/cam01_clip00_orig.json \\
        --floor-zones data/zones/floor_cam01.json \\
        --image-zones data/zones/image_cam01.json \\
        --tracks-per-frame 3 \\
        --frames 2000 \\
        --baseline-fps 25 \\
        --output outputs/homography/cost_benchmark.json

`--baseline-fps`는 실측 FPS가 아니라 추정에 쓰는 가정값이다.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import statistics
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable, List, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.common.types import Track  # noqa: E402
from src.geofencing.floor_plane import FloorPlaneTransformer, load_calibration  # noqa: E402
from src.geofencing.floor_zone import FloorZoneChecker, load_floor_zones  # noqa: E402
from src.geofencing.zone_checker import ZoneChecker  # noqa: E402
from src.geofencing.zone_loader import load_zones  # noqa: E402

WARMUP_FRAMES = 200
REPEATS = 5


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--calibration", required=True)
    parser.add_argument("--floor-zones", required=True)
    parser.add_argument("--image-zones", required=True)
    parser.add_argument("--tracks-per-frame", type=int, default=3)
    parser.add_argument("--frames", type=int, default=2000)
    parser.add_argument(
        "--baseline-fps",
        type=float,
        default=25.0,
        help="FPS 하락률 산정 기준. 촬영·운영에서 목표로 하는 처리 FPS.",
    )
    parser.add_argument("--seed", type=int, default=20260807)
    parser.add_argument("--output", required=True)
    return parser.parse_args()


def make_foot_points(
    count: int, width: int, height: int, seed: int
) -> List[Tuple[float, float]]:
    """화면 하단 2/3에 균일하게 뿌린 foot point.

    Zone 안팎이 섞여야 판정 분기가 한쪽만 타지 않는다.
    """
    rng = random.Random(seed)
    return [
        (rng.uniform(0.0, width - 1), rng.uniform(height / 3.0, height - 1))
        for _ in range(count)
    ]


def time_path(work: Callable[[], None], frames: int) -> dict:
    """frame당 소요를 ms로 재고 반복 표본을 모두 돌려준다.

    최솟값은 그 환경에서 달성 가능한 하한이라 GC·스케줄러 노이즈가 빠지지만,
    일반적인 runtime보다 낙관적이다. 중앙값을 대표값으로 쓰고 최솟값은 진단으로
    함께 남겨 둘을 비교할 수 있게 한다.
    """
    for _ in range(WARMUP_FRAMES):
        work()
    samples = []
    for _ in range(REPEATS):
        start = time.perf_counter()
        for _ in range(frames):
            work()
        samples.append((time.perf_counter() - start) * 1000.0 / frames)
    return {
        "median_ms_per_frame": statistics.median(samples),
        "min_ms_per_frame": min(samples),
        "max_ms_per_frame": max(samples),
        "samples_ms_per_frame": samples,
    }


def write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as file:
            json.dump(payload, file, ensure_ascii=False, indent=2)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(temp_name, path)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise


def main() -> None:
    args = parse_args()
    if args.tracks_per_frame <= 0 or args.frames <= 0:
        raise SystemExit("--tracks-per-frame과 --frames는 1 이상이어야 합니다.")
    if not (args.baseline_fps > 0):
        raise SystemExit("--baseline-fps는 0보다 커야 합니다.")

    calibration = load_calibration(args.calibration)
    transformer = FloorPlaneTransformer(calibration)
    floor_checker = FloorZoneChecker(load_floor_zones(args.floor_zones))
    image_checker = ZoneChecker(
        load_zones(args.image_zones),
        calibration.frame_width,
        calibration.frame_height,
    )

    width = calibration.frame_width
    height = calibration.frame_height
    points: Sequence[Tuple[float, float]] = make_foot_points(
        args.tracks_per_frame, width, height, args.seed
    )
    # 기존 경로는 Track을 받아 내부에서 정규화한다. 같은 입력으로 비교해야
    # 정규화 비용까지 포함된 실제 차이가 나온다.
    tracks = [
        Track(track_id=index, bbox=[x - 30.0, y - 160.0, x + 30.0, y],
              foot_point=[x, y], confidence=0.9)
        for index, (x, y) in enumerate(points)
    ]

    def baseline() -> None:
        for track in tracks:
            image_checker.check(track)

    def candidate() -> None:
        for point in points:
            floor_checker.check_point(transformer.transform(list(point)))

    base = time_path(baseline, args.frames)
    cand = time_path(candidate, args.frames)

    base_ms = base["median_ms_per_frame"]
    cand_ms = cand["median_ms_per_frame"]
    added_ms = cand_ms - base_ms
    added_ms_min = cand["min_ms_per_frame"] - base["min_ms_per_frame"]

    # 추정치다. frame 예산 전체가 --baseline-fps로 결정되고 추가 비용이 선형으로
    # 얹힌다고 가정한 값이며, 두 파이프라인을 실제로 돌려 잰 FPS가 아니다.
    baseline_budget_ms = 1000.0 / args.baseline_fps
    estimated_candidate_fps = 1000.0 / (baseline_budget_ms + added_ms)
    estimated_drop = (args.baseline_fps - estimated_candidate_fps) / args.baseline_fps

    payload = {
        "tracks_per_frame": args.tracks_per_frame,
        "frames": args.frames,
        "repeats": REPEATS,
        "baseline": base,
        "homography": cand,
        "added_latency_ms_per_frame": added_ms,
        "added_latency_ms_per_frame_min": added_ms_min,
        "thresholds": {"max_added_latency_ms_per_frame": 1.0},
        "passes_added_latency": added_ms <= 1.0,
        "fps_drop": {
            "measurement_type": "estimated",
            "is_official": False,
            "assumed_baseline_fps": args.baseline_fps,
            "estimated_candidate_fps": estimated_candidate_fps,
            "estimated_fps_drop_ratio": estimated_drop,
            "note": (
                "계약의 FPS 하락률은 두 경로를 같은 영상·같은 조건으로 실행해 얻은 "
                "실측 FPS로 계산해야 한다. 이 값은 microbenchmark의 추가 비용을 "
                "frame 예산에 더해 역산한 추정치이므로 공식 판정에 쓰지 않는다."
            ),
        },
    }
    write_json_atomic(Path(args.output), payload)

    print(f"기존 경로      중앙값 {base_ms:.4f} / 최소 {base['min_ms_per_frame']:.4f} ms")
    print(f"Homography 경로 중앙값 {cand_ms:.4f} / 최소 {cand['min_ms_per_frame']:.4f} ms")
    print(
        f"추가 비용      {added_ms:+.4f} ms/frame (최소 기준 {added_ms_min:+.4f}) "
        f"[기준 1.0 이하 → {'통과' if payload['passes_added_latency'] else '미달'}]"
    )
    print(
        f"FPS 하락률     {estimated_drop * 100:+.3f}% "
        f"(baseline {args.baseline_fps:g}fps 가정) -- 추정치, 공식 판정 불가"
    )
    print(f"-> {args.output}")


if __name__ == "__main__":
    main()
