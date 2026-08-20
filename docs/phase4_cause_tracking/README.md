# Phase 4 Cause·Tracking 평가

## 범위

E1 selected profile과 실제 촬영 diagnostic cache를 고정하고 다음을 평가했다.

- 다중 인원 12편: `contact_fall` 8편, `near_pass` 3편,
  `occluded_cross` 1편
- Cause 후보 없음 보조 평가 24편: A01·A02 단독 낙상
- Track·Actor segment 68개와 ID switch 15개 검수

no-fall 영상도 audit coverage에서 빠지지 않도록 Event가 없으면
`true_negative`, Event가 있으면 `false_alarm`으로 기록한다. no-fall 결과는
FAR와 Event 오류에 사용하며 Cause 지표 분모에는 포함하지 않는다.

## 결과

| 지표 | 결과 | 목표 | 판정 |
|---|---:|---:|---|
| Cause top-1 | 3/8 (37.5%) | 80% 이상 | 미달 |
| `cause=null` specificity | 24/24 (100.0%) | 90% 이상 | 통과 |
| reviewed ID switch | 15건 | - | 완료 |
| ID switch가 유발한 Event 오류 | 0건 | 반복 시 tracker 비교 | 반복 없음 |

Cause top-1의 분모는 Tracker arm이 바뀌어도 동일하도록 다중 인원 고정 cohort
중 `cause_candidate_exists=true`인 8편으로 고정한다. timely 대표 Event가 있는
5편 중 3편은 Cause top-1이 맞았고, 나머지 3편은 missed fall 2편과 late fall
1편으로 분류돼 모두 고정 분모에 포함된다. victim actor와 Cause actor는 독립적으로
채점하므로 victim mismatch가 함께 발생한 1건도 분모에서 제외하지 않는다.

Actor별 결과는 A01 `3/4 (75.0%)`, A02 `0/4 (0.0%)`이며, 결과 artifact에는
matched Event·missed fall·late fall을 함께 남긴다. 따라서 Tracker를 바꿔도
낙상을 놓친 arm이 Cause top-1을 더 좋아 보이게 만드는 비교를 허용하지 않는다.

Tracker 비교 트리거는 공식 낙상 점수의 protocol을 변경하지 않는 후속 진단
정책이며, `phase4_tracker_comparison_policy_v1`로 별도 기록한다. 공식 낙상
지표의 protocol version은 `phase4_fall_eval_v1`로 유지한다.

ID switch와 Event 오류가 함께 있었지만 인과가 확인되지 않은 1건은
`associated`로 기록했다. `caused` 오류는 0건이지만 Cause top-1이 목표에
미달했고 12편에서 ID switch 15건이 확인됐으므로 ReID 실험을 진행한다.
동일 12편에서 ByteTrack, appearance ReID를 끈 BoT-SORT, ReID를 켠
BoT-SORT를 비교해 tracker 변경과 ReID의 효과를 분리하고, victim·Cause
정확도 개선과 Recall·FPS 유지를 확인한다.

현재 결정은 `ByteTrack 기준선 유지 / BoT-SORT·ReID 실험 도입 / production
채택 대기`다. 비교 결과 없이 ReID를 운영 기본값으로 전환하지 않는다.

### A03 annotation revision

최종 A03 test 검수에서 `P4_S01_A03_kneel_01_cam01`은 무릎 동작으로 끝나는
no-fall이 아니라 통제된 전방 무릎 낙상 재연으로 확인돼
`P4_S01_A03_fall_forward_knees_04_cam01`로 재분류했다. 영상 바이트와
SHA-256은 동일하고, 변경된 것은 계약 파일명·scenario·label·낙상 frame
annotation이다. 정정 후 A03 test는 `fall 15 / no_fall 3`으로 평가했으며,
정정 전 파일은 `data/annotations/phase4/history/a03_pre_label_correction/`
에 보존한다.

이 실험에서 ReID의 목표는 다음과 같다.

- 사람끼리 겹치거나 detector bbox가 잠깐 끊긴 뒤 다시 검출됐을 때 기존
  Track ID로 재연결
- victim·Cause actor가 새 ID로 바뀌어 attribution이 끊기는 문제 감소
- 낙상 candidate state 유실과 같은 사람의 중복 Event 감소

ReID는 detection이 없는 프레임에 bbox를 새로 만드는 기능이 아니다. 짧은
공백은 tracker buffer가 유지하고, detection이 돌아왔을 때 appearance feature가
기존 Track과의 재연결을 돕는다. 장기 퇴장 후 재입장, 영구 ID, cross-camera
ReID는 이번 Phase 4 비교 범위가 아니다.

기계 판독 결과는 [summary.json](summary.json)에 보존한다.

## 재현

아래 명령은 모델 추론을 다시 하지 않고 동결된 cache를 재생한다. replay는
selected profile의 모델·tracker·config·dataset SHA-256과 cache 생성 revision을
입력 처리 전에 검증한다.

`--official-eval`에는 같은 selected profile과 cache로 생성한 공식 결과만 넣는다.
공식 결과를 다시 만들 때는 selected profile의 실행 필드와 cache manifest
SHA-256을 함께 기록하도록 다음 옵션을 포함한다. 실행 profile SHA-256은
`model`·`inference`·`recorded_dataset`·`evaluation_protocol`을 canonical JSON으로
계산한다. 결과 artifact SHA는 `results.recorded_diagnostic.artifact_sha256` 등에
들어 있으므로, 순환 참조를 막기 위해 최상위 `results` subtree 전체를 제외한다.

```bash
python scripts/evaluate_fall_from_cache.py \
  --annotations data/annotations/phase4/fall_cause_annotations.csv \
  --recordings-manifest data/annotations/phase4/recordings_manifest.csv \
  --cache-dir outputs/phase4_recorded_eval/cache/e1_diagnostic_pose_conf05_recorded_mps \
  --split diagnostic \
  --config configs/fall_detection.json \
  --fall-model-iou-threshold 0.3 \
  --fall-model-interval-frames 3 \
  --fall-pose-normal-gate-enabled \
  --evaluation-protocol-version phase4_fall_eval_v1 \
  --selected-profile configs/fall_e1_selected.json \
  --cache-source-manifest \
    data/annotations/phase4/history/a03_pre_label_correction/recordings_manifest.csv \
  --cache-source-annotations \
    data/annotations/phase4/history/a03_pre_label_correction/fall_cause_annotations.csv \
  --output outputs/phase4_recorded_eval/results/e1_diagnostic_actor_comparison.json
```

현재 cache는 A03 label 정정 전에 생성됐지만 정정된 행은 `test` split에만 있다.
평가기에서는 위 history snapshot의 SHA-256이 cache manifest와 일치하고, 평가하는
`diagnostic` 46개 행이 현재 revision과 완전히 같을 때만 기존 cache를 허용한다.
대상 행이 하나라도 다르면 공식 결과 생성을 거부한다.

```bash
python scripts/replay_phase4_multiperson_events.py \
  --manifest data/annotations/phase4/recordings_manifest.csv \
  --annotations data/annotations/phase4/fall_cause_annotations.csv \
  --cache-dir outputs/phase4_recorded_eval/cache/e1_diagnostic_pose_conf05_recorded_mps \
  --output outputs/phase4_recorded_eval/results/multiperson_events.json

python scripts/replay_phase4_multiperson_events.py \
  --manifest data/annotations/phase4/recordings_manifest.csv \
  --annotations data/annotations/phase4/fall_cause_annotations.csv \
  --cache-dir outputs/phase4_recorded_eval/cache/e1_diagnostic_pose_conf05_recorded_mps \
  --scenario fall_backward \
  --scenario fall_forward \
  --scenario fall_forward_knees \
  --scenario fall_side \
  --output outputs/phase4_recorded_eval/results/cause_null_events.json

python scripts/summarize_phase4_cause_tracking.py \
  --manifest data/annotations/phase4/recordings_manifest.csv \
  --annotations data/annotations/phase4/fall_cause_annotations.csv \
  --multiperson-events outputs/phase4_recorded_eval/results/multiperson_events.json \
  --cause-null-events outputs/phase4_recorded_eval/results/cause_null_events.json \
  --official-eval outputs/phase4_recorded_eval/results/e1_diagnostic_actor_comparison.json \
  --event-review data/annotations/phase4/event_attribution_review.csv \
  --switches data/annotations/phase4/track_id_switches.csv \
  --selected-profile configs/fall_e1_selected.json \
  --output docs/phase4_cause_tracking/summary.json \
  --force
```
