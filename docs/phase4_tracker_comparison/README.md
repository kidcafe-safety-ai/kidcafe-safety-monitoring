# Phase 4 Tracker 3-way 비교

## 목적

E1 selected profile의 detector·낙상 설정·평가 protocol을 고정하고 association
tracker만 다음 세 arm으로 비교한다.

| arm | association | appearance ReID |
|---|---|---|
| `bytetrack_baseline` | ByteTrack | OFF |
| `botsort_without_reid` | BoT-SORT | OFF |
| `botsort_with_reid` | BoT-SORT | ON |

Production tracker는 결과가 확정되기 전까지 변경하지 않는다. 모든 후보가 채택
기준을 통과하지 못하면 ByteTrack을 유지하고 ReID를 미채택한다.

## 고정 조건

`configs/phase4_tracker_comparison.json`이 다음 값을 동결한다.

- E1 auxiliary fall model과 SHA-256
- YOLO Pose tracker model과 SHA-256
- confidence·IoU·interval·Pose NORMAL gate
- `phase4_fall_eval_v1`
- diagnostic 46편, 다중 인원 12편, Cause 후보 고정 분모 8편
- Cause-null 보조 세트 24편
- 세 tracker YAML과 SHA-256
- ReID 모델 경로와 SHA-256

arm마다 diagnostic 46편을 새로 추론한다. 따라서 Cause 12편뿐 아니라 Recall,
timely Recall, no-fall false Event, duplicate, latency와 FPS도 동일 cohort에서
비교한다.

## ReID 모델 준비

ReID ON arm은 `model: auto`를 금지한다. Ultralytics의 Pose tracker에서 auto를
사용하면 별도 classification model을 실행 중 내려받을 수 있어 동일 artifact를
보장할 수 없기 때문이다.

실험 전에 공식 release artifact를 명시적으로 내려받고 SHA-256을 확인한다.

```bash
mkdir -p outputs/phase4_tracker_comparison/models

curl -fL --retry 3 \
  -o outputs/phase4_tracker_comparison/models/yolo26n-cls.pt \
  https://github.com/ultralytics/assets/releases/download/v8.4.0/yolo26n-cls.pt

printf '%s  %s\n' \
  0dd6f8dbc448870ac98a3cbb7156f923f7ce21fed3755d4019169ffffd279e81 \
  outputs/phase4_tracker_comparison/models/yolo26n-cls.pt \
  | shasum -a 256 -c -
```

모델은 `outputs/` 아래에 두며 Git에 포함하지 않는다. 실행기는 파일이 없거나
SHA-256이 다르면 영상과 모델을 열기 전에 중단한다.

## arm 추론

각 명령은 46편 진행도를 계속 출력한다. FPS 비교를 위해 arm마다 새 cache를
만들며, 일부 영상을 건너뛴 timing 결과는 최종 비교에서 거부한다.
최종 실행은 깨끗한 단일 Git commit에서만 허용하며, 세 arm의 evaluator commit이
다르면 최종 요약을 만들지 않는다.

먼저 세 arm의 파일·SHA-256·cohort와 실행 명령만 확인할 수 있다.

```bash
for ARM in bytetrack_baseline botsort_without_reid botsort_with_reid; do
  python scripts/run_phase4_tracker_arm.py \
    --arm-id "$ARM" \
    --preflight-only
done
```

```bash
source .venv/bin/activate

python -u scripts/run_phase4_tracker_arm.py \
  --arm-id bytetrack_baseline \
  --device mps \
  --fall-model-device mps

python -u scripts/run_phase4_tracker_arm.py \
  --arm-id botsort_without_reid \
  --device mps \
  --fall-model-device mps

python -u scripts/run_phase4_tracker_arm.py \
  --arm-id botsort_with_reid \
  --device mps \
  --fall-model-device mps
```

Windows CUDA 환경에서는 두 device 값을 `0`으로 바꾼다. 세 arm은 같은 장비에서
연속 실행해야 FPS 비교가 유효하다.

각 arm은 다음 파일을 만든다.

```text
outputs/phase4_tracker_comparison/arms/<arm_id>/
├── cache/
├── official_eval.json
├── multiperson_events.json
├── cause_null_events.json
├── track_actor_segments.csv
└── arm_run_manifest.json
```

## Track·Actor 검수

각 arm의 `track_actor_segments.csv`를 다중 인원 12편에서 별도로 검수한다.
Tracker가 달라지면 Track ID도 달라지므로 baseline 검수 결과를 후보 arm에 복사하지
않는다.

```bash
ARM=botsort_without_reid
VIDEO_ID=P4_S01_A01_contact_fall_01_cam01

python scripts/review_phase4_track_actor_segments.py \
  --manifest data/annotations/phase4/recordings_manifest.csv \
  --segments outputs/phase4_tracker_comparison/arms/$ARM/track_actor_segments.csv \
  --cache-dir outputs/phase4_tracker_comparison/arms/$ARM/cache \
  --video-id "$VIDEO_ID"
```

12편의 `video_id`는 다음 명령으로 확인한다.

```bash
python - <<'PY'
import csv

scenarios = {'contact_fall', 'near_pass', 'occluded_cross'}
with open('data/annotations/phase4/recordings_manifest.csv', encoding='utf-8') as f:
    for row in csv.DictReader(f):
        if row['scenario_type'] in scenarios and row['primary_actor_id'] in {'A01', 'A02'}:
            print(row['video_id'])
PY
```

검수 완료 후 arm별 ID switch와 Event attribution 초안을 만든다.

```bash
ARM=botsort_without_reid
ROOT=outputs/phase4_tracker_comparison/arms/$ARM

python scripts/derive_phase4_track_id_switches.py \
  --manifest data/annotations/phase4/recordings_manifest.csv \
  --segments "$ROOT/track_actor_segments.csv" \
  --output "$ROOT/track_id_switches.csv" \
  --force

python scripts/generate_phase4_event_attribution_review.py \
  --manifest data/annotations/phase4/recordings_manifest.csv \
  --annotations data/annotations/phase4/fall_cause_annotations.csv \
  --events "$ROOT/multiperson_events.json" \
  --official-eval "$ROOT/official_eval.json" \
  --segments "$ROOT/track_actor_segments.csv" \
  --switches "$ROOT/track_id_switches.csv" \
  --selected-profile configs/fall_e1_selected.json \
  --run-id "$ARM" \
  --output "$ROOT/event_attribution_review.csv" \
  --force
```

`needs_review` ID switch와 pending Event attribution을 영상으로 확인한 뒤에만
`reviewed`로 바꾼다. missed·late 영상도 Cause top-1 고정 분모 8편에 실패로
포함한다.

## arm별 Cause summary

```bash
ARM=botsort_without_reid
ROOT=outputs/phase4_tracker_comparison/arms/$ARM

python scripts/summarize_phase4_cause_tracking.py \
  --manifest data/annotations/phase4/recordings_manifest.csv \
  --annotations data/annotations/phase4/fall_cause_annotations.csv \
  --multiperson-events "$ROOT/multiperson_events.json" \
  --cause-null-events "$ROOT/cause_null_events.json" \
  --official-eval "$ROOT/official_eval.json" \
  --event-review "$ROOT/event_attribution_review.csv" \
  --switches "$ROOT/track_id_switches.csv" \
  --selected-profile configs/fall_e1_selected.json \
  --tracker-comparison-config configs/phase4_tracker_comparison.json \
  --tracker-arm-id "$ARM" \
  --output "$ROOT/cause_tracking_summary.json" \
  --force
```

세 arm 모두 완료한 뒤 최종 판정을 생성한다.

```bash
python scripts/summarize_phase4_tracker_comparison.py \
  --output outputs/phase4_tracker_comparison/summary.json \
  --force
```

## 채택 기준

- Cause top-1 `7/8` 이상
- Cause-null specificity 90% 이상
- Recall·timely Recall 저하 없음
- false Event·duplicate 증가 없음
- victim mismatch와 reviewed ID switch 감소
- 평균 onset latency 증가 0.2초 이내
- FPS 하락률 20% 이내

하나라도 미달하면 해당 후보는 채택하지 않는다. 여러 후보가 모두 통과하면 Cause
정답 수, victim mismatch, ID switch, FPS 순으로 비교하며 동률이면 ReID가 없는
단순한 arm을 우선한다.

## `track_buffer=60` 후속 진단

최초 3-way 비교의 `track_buffer=30`은 Ultralytics 기본값을 고정한 값이다. 실제
영상에서 30 frame을 넘는 검출 공백이 확인되어, 기존 결과를 보존한 채
`configs/phase4_tracker_buffer60_comparison.json`으로 동일 세 arm을 다시 비교한다.

- 변경 변수: `track_buffer` 30 -> 60
- 고정 변수: detector, E1 model, threshold, 평가 cohort, ReID model과 나머지
  tracker 설정
- 출력 경로: `outputs/phase4_tracker_buffer60_comparison`
- 해석 범위: buffer 증가 효과와 현재 `yolo26n-cls.pt` 기반 ReID 효과를 분리해
  진단하며, 사람 전용 ReID 모델의 일반적 효용을 기각하지 않는다.

```bash
for ARM in bytetrack_baseline botsort_without_reid botsort_with_reid; do
  python scripts/run_phase4_tracker_arm.py \
    --comparison-config configs/phase4_tracker_buffer60_comparison.json \
    --output-root outputs/phase4_tracker_buffer60_comparison \
    --arm-id "$ARM" \
    --preflight-only
done
```
