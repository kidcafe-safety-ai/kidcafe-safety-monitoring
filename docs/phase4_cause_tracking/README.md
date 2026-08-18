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
| Cause top-1 | 3/5 (60.0%) | 80% 이상 | 미달 |
| `cause=null` specificity | 24/24 (100.0%) | 90% 이상 | 통과 |
| reviewed ID switch | 15건 | - | 완료 |
| ID switch가 유발한 Event 오류 | 0건 | 반복 시 tracker 비교 | 반복 없음 |

Cause top-1은 timely 대표 Event만 사용한다. victim actor와 Cause actor는
독립적으로 채점하므로 victim mismatch가 함께 발생한 1건도 Cause 분모에서
제외하지 않았다. 따라서 완화된 3/4이 아니라 보수적인 3/5를 공식 결과로
사용한다.

ID switch와 Event 오류가 함께 있었지만 인과가 확인되지 않은 1건은
`associated`로 기록했다. `caused` 오류는 0건이지만 Cause top-1이 목표에
미달했고 12편에서 ID switch 15건이 확인됐으므로 ReID 실험을 진행한다.
동일 12편에서 ByteTrack, appearance ReID를 끈 BoT-SORT, ReID를 켠
BoT-SORT를 비교해 tracker 변경과 ReID의 효과를 분리하고, victim·Cause
정확도 개선과 Recall·FPS 유지를 확인한다.

현재 결정은 `ByteTrack 기준선 유지 / BoT-SORT·ReID 실험 도입 / production
채택 대기`다. 비교 결과 없이 ReID를 운영 기본값으로 전환하지 않는다.

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
