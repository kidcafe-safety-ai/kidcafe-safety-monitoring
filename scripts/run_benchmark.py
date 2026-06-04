"""
YOLO 모델 벤치마크 스크립트

Usage:
    .venv-benchmark/bin/python scripts/run_benchmark.py \
        --model yolov8n \
        --video data/videos/test1.mp4 \
        --zones data/zones/no_zones.json

출력:
    outputs/benchmark/{model}/{video}/metrics.json
    outputs/benchmark/{model}/{video}/result.mp4
"""

import argparse
import json
import time
from pathlib import Path

import cv2
import numpy as np
from shapely.geometry import Point, Polygon


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True, help="yolov8n | yolov8s | yolo26n | yolo26s")
    parser.add_argument("--video", required=True, help="data/videos/test1.mp4")
    parser.add_argument("--zones", required=True, help="data/zones/no_zones.json or benchmark_v3.json")
    parser.add_argument("--conf", type=float, default=0.3)
    parser.add_argument("--device", default="", help="'' = auto | cpu | mps | cuda")
    return parser.parse_args()


def load_zones(path: str) -> list:
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)

    zones = []
    for z in raw:
        if z.get("type") == "polygon" and z.get("points"):
            zones.append({
                "zone_id": z["zone_id"],
                "name": z.get("name", z["zone_id"]),
                "polygon": Polygon(z["points"]),
                "dwell_threshold_sec": z.get("rules", {}).get("dwell_threshold_sec", 5),
            })
    return zones


def draw_zones(frame: np.ndarray, zones: list, width: int, height: int) -> np.ndarray:
    for z in zones:
        pts = np.array(
            [(int(x * width), int(y * height)) for x, y in z["polygon"].exterior.coords[:-1]],
            dtype=np.int32,
        )
        cv2.polylines(frame, [pts], isClosed=True, color=(0, 255, 0), thickness=2)
        cv2.putText(frame, z["name"], tuple(pts[0]), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
    return frame


def main():
    args = parse_args()

    # ── 출력 경로 ──────────────────────────────────────────────────────────────
    video_stem = Path(args.video).stem
    out_dir = Path("outputs/benchmark") / args.model / video_stem
    out_dir.mkdir(parents=True, exist_ok=True)

    # ── Zone 로드 ──────────────────────────────────────────────────────────────
    zones = load_zones(args.zones)
    print(f"Zone: {len(zones)}개 로드됨  ({Path(args.zones).name})")

    # ── 영상 열기 ──────────────────────────────────────────────────────────────
    cap = cv2.VideoCapture(args.video)
    if not cap.isOpened():
        raise RuntimeError(f"영상을 열 수 없습니다: {args.video}")

    src_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    out_video = cv2.VideoWriter(
        str(out_dir / "result.mp4"),
        cv2.VideoWriter_fourcc(*"mp4v"),
        src_fps,
        (width, height),
    )

    # ── 모델 로드 (FPS 측정 제외) ──────────────────────────────────────────────
    print(f"모델 로딩: {args.model}.pt ...")
    from ultralytics import YOLO
    model = YOLO(f"{args.model}.pt")
    print("모델 로딩 완료. 벤치마크 시작.\n")

    # ── 상태 ──────────────────────────────────────────────────────────────────
    frame_times: list[float] = []
    all_track_ids: set[int] = set()
    total_detections = 0
    events = {"ENTER": 0, "DWELL": 0, "EXIT": 0}

    # zone 상태: track_id → set of zone_id
    track_zone_state: dict[int, set] = {}
    # dwell 타이머: (track_id, zone_id) → 진입 시각
    dwell_enter_time: dict[tuple, float] = {}
    dwell_fired: set[tuple] = set()

    frame_idx = 0
    benchmark_start = time.perf_counter()

    # ── 메인 루프 ─────────────────────────────────────────────────────────────
    while True:
        ret, frame = cap.read()
        if not ret:
            break

        t0 = time.perf_counter()

        results = model.track(
            frame,
            persist=True,
            conf=args.conf,
            classes=[0],
            verbose=False,
            device=args.device,
        )

        frame_time = time.perf_counter() - t0
        frame_times.append(frame_time)

        result = results[0]
        current_ids: set[int] = set()

        if result.boxes is not None and result.boxes.id is not None:
            for i, tid in enumerate(result.boxes.id.int().tolist()):
                total_detections += 1
                all_track_ids.add(tid)
                current_ids.add(tid)

                # foot_point (정규화)
                x1, y1, x2, y2 = result.boxes.xyxy[i].tolist()
                foot = Point((x1 + x2) / 2 / width, y2 / height)

                inside: set[str] = {z["zone_id"] for z in zones if z["polygon"].covers(foot)}
                prev: set[str] = track_zone_state.get(tid, set())

                for zid in inside - prev:
                    events["ENTER"] += 1
                    dwell_enter_time[(tid, zid)] = time.perf_counter()

                for zid in prev - inside:
                    events["EXIT"] += 1
                    dwell_enter_time.pop((tid, zid), None)
                    dwell_fired.discard((tid, zid))

                for zid in inside:
                    threshold = next(z["dwell_threshold_sec"] for z in zones if z["zone_id"] == zid)
                    key = (tid, zid)
                    if key not in dwell_enter_time:
                        dwell_enter_time[key] = time.perf_counter()
                    if (time.perf_counter() - dwell_enter_time[key] >= threshold
                            and key not in dwell_fired):
                        events["DWELL"] += 1
                        dwell_fired.add(key)

                track_zone_state[tid] = inside

        # 사라진 트랙 EXIT 처리
        for tid in set(track_zone_state) - current_ids:
            for zid in track_zone_state[tid]:
                events["EXIT"] += 1
                dwell_enter_time.pop((tid, zid), None)
                dwell_fired.discard((tid, zid))
            del track_zone_state[tid]

        # ── 프레임 오버레이 ──────────────────────────────────────────────────
        annotated = result.plot()
        annotated = draw_zones(annotated, zones, width, height)

        fps_now = 1.0 / frame_time if frame_time > 0 else 0
        cv2.putText(annotated, f"FPS:{fps_now:.1f}", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)
        cv2.putText(annotated, f"IDs:{len(all_track_ids)}", (10, 60),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)

        out_video.write(annotated)
        frame_idx += 1

        if frame_idx % 50 == 0:
            print(f"  [{frame_idx:>4}/{total_frames}] FPS:{fps_now:.1f}  IDs:{len(all_track_ids)}")

    total_time = time.perf_counter() - benchmark_start
    cap.release()
    out_video.release()

    # ── 지표 계산 ─────────────────────────────────────────────────────────────
    fps_measured = frame_idx / total_time if total_time > 0 else 0
    avg_ms = (sum(frame_times) / len(frame_times) * 1000) if frame_times else 0
    avg_det = total_detections / frame_idx if frame_idx > 0 else 0

    metrics = {
        "model": args.model,
        "video": video_stem,
        "zones_file": Path(args.zones).name,
        "conf": args.conf,
        "device": args.device or "auto",
        "total_frames": frame_idx,
        "fps_measured": round(fps_measured, 2),
        "avg_frame_time_ms": round(avg_ms, 2),
        "total_time_sec": round(total_time, 2),
        "total_detections": total_detections,
        "avg_detections_per_frame": round(avg_det, 2),
        "unique_track_ids": len(all_track_ids),
        "id_switch_proxy": "unique_track_ids 낮을수록 추적 안정",
        "events": {**events, "total": sum(events.values())},
    }

    metrics_path = out_dir / "metrics.json"
    with open(metrics_path, "w", encoding="utf-8") as f:
        json.dump(metrics, f, ensure_ascii=False, indent=2)

    # ── 결과 출력 ─────────────────────────────────────────────────────────────
    sep = "=" * 52
    print(f"\n{sep}")
    print(f"  모델:            {args.model}")
    print(f"  영상:            {video_stem}")
    print(f"  FPS:             {fps_measured:.2f}")
    print(f"  avg frame time:  {avg_ms:.1f} ms")
    print(f"  total time:      {total_time:.1f} s")
    print(f"  unique IDs:      {len(all_track_ids)}  ← ID switch proxy")
    print(f"  avg det/frame:   {avg_det:.2f}")
    print(f"  ENTER/DWELL/EXIT:{events['ENTER']}/{events['DWELL']}/{events['EXIT']}")
    print(f"  결과 저장:       {out_dir}")
    print(sep)


if __name__ == "__main__":
    main()
