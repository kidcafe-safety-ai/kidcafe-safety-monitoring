# Phase 3 FALL_SUSPECT 평가 기록

낙상 감지 코어의 실측 평가 기록이다. 데이터·설정·결과를 버전과 함께 남겨
같은 조건을 재현하고 회귀를 확인할 수 있게 한다.

## 1. 데이터셋

- 데이터셋: CAUCAFall V5 (DOI 10.17632/7w7fccy7ky.5, CC BY 4.0)
- 상세 라이선스·체크섬: [docs/data_sources.md](data_sources.md)
- 분할 (docs/data_sources.md, configs/caucafall_v5_split.json과 동일):
  - Development (Subject 1-6): 60개 영상 — fall 30, no_fall 30
  - 진단·튜닝 (Subject 7-8, 디렉터리명 `validation`): 20개 영상 — fall 10, no_fall 10
  - Holdout (Subject 9-10): 최종 평가 전까지 미사용

## 2. Annotation 생성·검수

초기 V1 annotation은 `scripts/generate_caucafall_annotations.py`가 프레임별
YOLO 라벨(`class 0=nofall, 1=fall`)의 0→1 전환을 `fall_start_frame`으로
사용했다. 이 값은 데이터셋 분류 라벨의 시작점이지 실제 동작 onset과 항상
같지는 않으므로, V1 결과는 역사적 기준선으로만 유지한다.

현재 평가는 `scripts/generate_caucafall_annotations_v2.py`가 만든 V2 CSV를
사용한다. 원본 0→1 전환은 `dataset_fall_label_frame`에 보존하고, 사람이 AVI를
순차 디코딩하며 아래 세 시점을 별도로 기록했다.

- `fall_start_frame`: 균형을 잃고 낙상이 시작된 첫 프레임
- `impact_frame`: 신체가 바닥과 충돌한 첫 프레임
- `lying_start_frame`: 넘어진 자세가 안정적으로 유지되기 시작한 프레임

Development 60개와 Subject 7-8 20개, 총 80개 행을 모두 `reviewed`로 확정했고
구조 검증을 통과했다. no_fall 40개는 실제 AVI 프레임 범위의 class가 모두 0인지
자동 검증한 뒤 표본을 사람이 확인했다. 현재 공식 기준선은
`development_annotations_v2.csv`와 `validation_annotations_v2.csv`를 사용한다.

txt 파일명 숫자는 실제 frame 번호가 아니므로 정렬 순서(0-base)를 사용한다.
txt가 AVI 프레임보다 많은 경우 초과분을 뒤에서 제외하고 생성 리포트에 남긴다.

## 3. 초기 V1 상태머신 설계 변경 (Tune 1)

최초 구현은 "하강 속도 / 높이 수축률 / 수평 자세" 3개 근거 중 2개 이상이 **같은
프레임에** 동시에 있어야 candidate에 진입했다. Subject 1 Fall backwards로
확인한 결과, 실제 낙상은 하강/수축이 먼저 나타나고(frame 68-71) 수평 자세는
한참 뒤(frame 75+)에야 나타나 두 근거가 겹치지 않았고, 그 결과 개발 60개 중
26개가 `event_count=0`으로 아예 candidate에 진입하지 못했다.

**변경**: candidate 진입 조건을 "하강 속도 OR 높이 수축률"(단일 동적 근거)로
완화하고, 수평 자세는 confirm 단계(진입 후 `fall_confirm_sec` 이상 지속)에서만
사용하도록 시간적으로 분리했다. `_is_recovered()`도 이에 맞춰 유지한다
(`src/safety/fall_detector.py` 모듈 docstring 참고).

## 4. 초기 V1 Development 평가 결과

동결된 설정: [configs/fall_detection.json](../configs/fall_detection.json)

| 실행 | 구조 | Recall | False alarm/min | 평균 지연(초) | 중복 Event | 비고 |
|---|---|---:|---:|---:|---:|---|
| Baseline | 근거 2/3 동시 요구 | 13.3% (4/30) | 0.0 | 4.30 | 0 | `outputs/fall_eval/development_baseline.json` |
| Tune 1 | 시간차 근거 분리 | 16.7% (5/30) | 0.0 | 1.92 | 0 | `outputs/fall_eval/development_tune_01_temporal_evidence.json` |
| Tune 2 | + Pose torso_angle (폐기) | 20.0% (6/30) | 0.0 | 0.88 | 0 | `outputs/fall_eval/development_tune_02_pose_confirmation.json` |
| Tune 2b | + Pose head_hip_diff_norm | 30.0% (9/30) | 0.0 | 1.14 | 1 | `outputs/fall_eval/development_tune_02b_pose_head_hip.json` |
| Tune 3 | + cooldown pose 반영 + early tolerance 0.2초 | 34.5% (10/29) | 0.0 | 1.02 | 1 | `outputs/fall_eval/development_tune_04_final.json` |
| Tune 5 | + fine-tuned fall/nofall 보조 모델 | 58.6% (17/29) | 0.0 | 0.60 | 1 | `outputs/fall_eval/development_tune_05_model.json` |
| Tune 7 | `model_confirm_sec=0.2` | 62.1% (18/29) | 0.0 | 0.35 | 1 | `outputs/fall_eval/development_tune_07_mc02.json` |
| Tune 11 | bounded temporal voting | 58.6% (17/29) | 0.0 | 0.30 | 0 | `outputs/fall_eval/development_tune_11_temporal_vote.json` |
| Tune 12 | + model-assisted candidate 진입 | 82.8% (24/29) | 0.0 | 0.78 | 2 | `outputs/fall_eval/development_tune_12_model_candidate.json` |
| **Tune 13 (최종 동결)** | + 공간 기반 cooldown 승계 | **82.8% (24/29)** | **0.0** | **0.78** | **0** | `outputs/fall_eval/development_tune_13_spatial_cooldown.json` |

Tune 3부터는 `S6_fall_backwards`가 `needs_review`로 제외돼 fall 모수가 29개다.
모든 표의 실행은 `evaluation_valid=true`, `skipped_with_error=0`이며,
early tolerance는 0.2초로 고정했다.

**Development 결론**: bbox+pose 규칙만으로는 Recall 34.5%에 머물렀지만,
fine-tuned 2-class detector와 시간·상태 제어를 결합한 Tune 13은 Development
목표(Recall 75% 이상, false alarm 0.2/분 이하, 평균 지연 2초 이하, 중복 Event
0건)를 모두 만족했다. 이 수치는 Subject 1-6 개발 데이터에서 설정을 고른
결과이므로, 운영 성능의 증명은 아니며 Subject 7-8 초기 Validation 결과와 분리해
해석한다.

## 5. 알려진 한계: 낙상 방향에 따른 미검출

Tune 1에서도 Recall이 목표(≥75%)에 크게 못 미친다. 놓친 25개 영상을 직접
추적한 결과, 두 가지 서로 다른 원인이 확인됐다.

### 5.1 aspect_ratio가 낙상 방향에 따라 성립하지 않음

`Subject 1 Fall forward`는 영상 전체(190프레임)에서 `aspect_ratio`가 **0.48을
넘지 않는다** (`horizontal_aspect_ratio_threshold=1.3`에 한참 못 미침). 반면
`foot_point_vertical_velocity`(1.54)·`height_change_rate`(-2.00)는 임계값을
넘어 candidate 진입은 되지만, confirm 조건(수평 자세 지속)을 끝내 만족하지
못한다. Subject 1의 5개 낙상 방향으로 확인한 `max aspect_ratio`:

| 방향 | max aspect_ratio | 1.3 도달 |
|---|---:|:---:|
| Fall backwards | 약 1.60 | O |
| Fall right | 1.71 | O |
| Fall sitting | 1.77 | O |
| Fall left | 0.71 | X |
| Fall forward | 0.48 | X |

카메라 각도상 앞/좌측으로 쓰러지면 bbox가 넓어지지 않는 것으로 보인다. 임계값을
낮추는 방식으로는 해결할 수 없다 (forward의 최댓값 0.48보다 낮은 임계값은
오탐 위험이 너무 크다).

### 5.2 bbox 기반 대체 신호(높이/중심 하강) 검토 및 폐기

절대 화면 좌표 대신 Track 자신의 낙상 전 상태(candidate 진입 직전 0.75초
구간의 height/center_y 중앙값) 대비 상대적 높이 비율(`height_ratio`)과 중심
하강량(`center_drop_norm`)을 confirm의 대체 경로로 시도했다. Development
60개 전체에서 두 신호의 fall/no_fall 분포를 비교한 결과:

| 신호 | fall (n=27) 중앙값 | no_fall (n=27) 중앙값 | 비고 |
|---|---:|---:|---|
| `min_height_ratio_to_reference` | 0.517 | 0.756 | 개별 영상 단위로 크게 겹침 |
| `max_center_drop_norm` | 0.473 | 0.492 | 사실상 동일 분포, 판별력 없음 |

특히 `S6_pick_up_object`(height_ratio=0.52)와 `S1_kneel`(0.53)은 fall 그룹
중앙값보다도 낮다 — 물건 줍기·무릎 꿇기가 낙상만큼 bbox 높이를 줄인다. 어떤
임계값을 잡아도 일상 동작 다수가 오탐으로 잡히거나 낙상을 못 잡거나 둘 중
하나이므로, 이 경로는 **폐기**했다 (코드에 포함하지 않음).

### 5.3 Pose 기반 보완

`yolo26n-pose.pt`(COCO 17 keypoint)로 `Subject 1 Fall forward`를 재확인한
결과, `nose_y - hip_y`가 서 있을 때는 음수(-52에서 -67 사이)였다가 쓰러진 뒤에는
양수(+57)로 부호가 뒤집힌다 — bbox aspect_ratio로는 잡지 못한 자세 변화를
keypoint 관계로는 명확하게 포착한다.

**1차 시도(폐기): 어깨-엉덩이 벡터 각도(torso_angle)**. 수직 기준 각도가
`pose_horizontal_angle_threshold_deg` 이상 지속되면 confirm하는 방식으로
구현·평가했으나(Recall 20%, `development_tune_02_pose_confirmation.json`),
`S1_fall_forward`를 프레임 단위로 직접 추적한 결과 각도가 60° 이상으로
올라가는 프레임이 사실상 1개(frame 142, 37.5-71.8° 순간 스파이크)뿐이었다.
원인은 카메라를 향해/멀어지는 방향(깊이 방향)으로 쓰러지면 몸 전체가 2D
영상에 압축 투영되어 어깨-엉덩이 벡터도 수직에 가깝게 남는다는 것 —
앞서 확인한 aspect_ratio와 동일한 카메라 각도 문제가 골격 각도에도 그대로
나타난다. 이는 CAUCAFall 공식 데이터셋 문서(`Dataset details.xlsx`,
Figure8)로도 교차 확인됐다: `S1 Fall forward`의 공식 낙상 각도는 화면 기준
**271.4°**로 기록되어 있어, 카메라 평면상 거의 수직에 가까운 각도로 촬영된
낙상임이 확정된다. 공식 참고 구현(Figure2/3)도 단일 각도가 아니라 전신
관절 구성을 함께 쓴다.

**2차 시도(채택): 머리-엉덩이 상대 높이(head_hip_diff_norm)**.
`(head_y - hip_y) / bbox_height`로 정의하며, 머리 keypoint는 코 신뢰도가
자세 변화 중 자주 떨어지므로(관측: 0.9 → 0.16-0.48) 코 → 눈 평균 → 귀 평균
순 fallback을 쓴다. Subject 1 Development 실측 결과 낙상 지속 구간
최소값(약 0.24)과 일상 동작 최댓값(약 0.16)이 겹치지 않아 벡터 각도보다 훨씬
안정적으로 분리된다. `_advance_candidate`의 confirm 조건에 수평 자세
경로와 OR로 추가했고(`pose_duration_sec >= fall_confirm_sec`), 다음 보조
규칙을 함께 넣었다:

- **recovery 억제**: pose가 "쓰러진 자세"로 보는 동안에는 회복 조건이
  성립해도 candidate를 초기화하지 않는다 (`_is_recovered`). 그렇지 않으면
  aspect_ratio가 낮게 유지되는 깊이 방향 낙상에서 회복 조건이 자주 만족돼
  pose confirm 진행이 중간에 끊긴다.
- **recovery debounce**: 회복 조건은 단일 프레임이 아니라
  `recovery_confirm_sec`(0.3초) 이상 지속돼야 실제로 NORMAL로 되돌린다 —
  bbox 속도/자세의 순간적인 검출 jitter로 candidate가 바로 초기화되지
  않게 하기 위함이다.
- **pose gap tolerance**: keypoint 신뢰도 부족 등으로 한 프레임의
  `pose_features`가 없으면 `pose_duration_sec`을 0으로 초기화하지 않고
  그대로 유지한다. 짧은 인식 실패로 이미 쌓인 지속시간이 사라지지 않게
  하기 위함이며, `fall_candidate_timeout_sec`가 candidate 전체의 상한을
  건다.
- **cooldown pose 반영**: `_advance_cooldown`도 bbox `is_horizontal_posture`
  뿐 아니라 pose `is_fallen_pose`를 함께 확인한다. 처음에는 bbox만 봤는데,
  깊이 방향 낙상에서 pose는 여전히 쓰러진 자세로 보는 동안 bbox가
  한 번도 수평으로 판정되지 않아 cooldown이 조기 만료되고, 같은 낙상이
  다시 candidate로 잡혀 중복 Event가 발생했다 (`S4_fall_forward`, frame
  41과 149 두 번 확정). recovery와 동일한 pose 우선 규칙을 적용해 고쳤다.

머리-엉덩이 신호 도입 후 Development Recall은 30%(9/30)까지 올랐으나
(`development_tune_02b_pose_head_hip.json`), 위 cooldown 버그로 인한 중복
확정 1건이 섞여 있었다. 최종 규칙 기반 결과는 Development 평가 표에 기록했다.

### 5.4 Early tolerance: annotation 라벨링 오차 허용

`S2_fall_sitting`에서 `fall_start_frame=81`보다 2프레임(0.1초) 이른 frame
79에 Event가 발생했다. frame 76·79·81·84를 직접 확인한 결과 frame 79는
이미 사람이 의자에서 내려와 양손·무릎으로 바닥을 짚는 낙상 진행 상태였다 —
detector가 틀린 것이 아니라 사람이 매긴 `fall_start_frame` 라벨이 실제
낙상 시작보다 몇 프레임 늦게 찍힌 것으로 판단된다. 이 사례 하나만 보고
detector를 늦추면(예: 임계값 완화 반대 방향) 전체 감지 지연만 나빠지므로,
`evaluate_fall.py`에 `early_tolerance_sec`(기본 0.2초, `--early-tolerance-sec`
로 조정 가능)를 추가해 `fall_start_frame` 직전 0.2초 이내 Event는 이른
오탐이 아니라 true positive로 인정하도록 했다 (`score_fall_video` 참고).
Development 전체에 동일하게 적용하는 고정값이며, 특정 영상 하나만 맞추기
위한 annotation 수정은 하지 않았다.

### 5.5 데이터 무결성: S6_fall_backwards AVI 손상

annotation 생성 시 `S6_fall_backwards`의 txt 라벨 개수(257)가 로컬 AVI
디코딩 프레임 수(234)보다 23개 많아, 최초에는 "txt 초과분"으로 보고 뒤에서
잘라냈다. 이후 CAUCAFall 공식 문서(`Dataset details.xlsx`)를 확인한 결과
이 영상의 공식 프레임 수는 **257**로, PNG(257)·txt(257)와 정확히 일치한다.
`ffprobe`(`nb_frames=234`, `duration=11.7s`, `r_frame_rate=20/1` →
11.7×20=234)와 `cv2.VideoCapture`(`CAP_PROP_FRAME_COUNT=234.0`, 실제
디코딩도 234) 두 독립 도구로 재검증한 결과도 234로 일치해, **로컬 AVI
파일 자체가 257프레임 중 234개만 담고 있는(하위 23프레임 손실) 손상
파일**임이 확정됐다. 즉 원래 프레임을 앞서 있었던 "txt가 23개 많다"는
해석은 방향이 반대였다.

`data/datasets/`는 원본 다운로드 데이터라 임의로 덮어쓰거나 재인코딩하지
않고, `S6_fall_backwards`의 `review_status`를 `needs_review`로 변경해
현재 평가에서 제외했다 (`development_annotations.csv`). 재개봉 전까지
Development 평가 모수는 fall 29개(원래 30개 중 1개 제외)다. 후속 조치로
Mendeley 원본 재다운로드 또는 257개 PNG로부터 AVI를 재구성하는 방안이
필요하며, 아직 실행하지 않았다.

### 5.6 Track 소실과 ID 변경에 대한 cooldown 보완

Tune 3의 `S4_fall_forward` 중복 Event는 candidate/pose 신호가 아니라,
COOLDOWN 상태에서 Track이 0.5초 grace period보다 오래 소실된 뒤 같은
`track_id`로 다시 검출되며 상태가 NORMAL로 초기화된 문제였다. COOLDOWN
상태는 `cooldown_until_sec`까지 보존하고, 그 시각이 지난 뒤에도 Track이
소실 상태일 때만 제거하도록 수정했다. 이로써 같은 ID가 잠시 사라졌다가
돌아오는 경우의 중복 확정을 막는다.

model-assisted candidate 진입을 추가한 Tune 12에서는 별도의 ID switch 문제가
나타났다. `S2_fall_forward`, `S3_fall_right`에서 같은 사람이 새 `track_id`로
재검출되면 기존 Track의 cooldown을 알 수 없어 두 번째 Event가 발생했다.
정식 ReID는 이번 범위가 아니므로, 확인 시점의 bbox와 만료 시각을
`_CooldownTombstone`으로 남기고 같은 `video_source`의 새 Track이 IoU 0.3
이상 겹칠 때만 남은 cooldown을 승계하는 경량 보완을 적용했다.

이 방식은 위치 기반 휴리스틱이며 외형 특징을 비교하는 ReID를 대체하지 않는다.
다중 인원이 가까이 겹친 장면에서는 다른 아동의 새 Track bbox도 tombstone과
IoU 기준을 만족할 수 있다. 이 경우 실제로 새로 발생한 다른 아동의 낙상까지
cooldown을 승계해 `FALL_SUSPECT`를 억제하는 false negative 위험이 있다.
현재 평가는 단일 대상 중심 데이터이므로 이 근접 다중 인원 상황을 정량 검증하지
않았다. 따라서 밀집 장면에서의 ReID 검증과 IoU 임계값 재평가는 Phase 4 후속
작업으로 남긴다. Development에서는 Tune 13에서 중복 Event가 0건으로 줄었고,
다른 위치 Track의 독립 감지와 만료 tombstone 정리만 단위 테스트로 확인했다.

## 6. 초기 V1 Validation (Subject 7-8)

Tune 13 설정과 `fall_detector_v1.pt`를 동결한 뒤 Subject 7-8 20개 영상에서
한 번 실행했다. 이 초기 Validation 단계에서는 결과를 확인한 뒤 임계값·모델을
다시 조정하지 않았다. 이후 Track handoff 오류 분석부터는 10장에 명시한 대로
Subject 7-8을 tuning/diagnostic 데이터로 전환했다.

| 지표 | 결과 | 목표 | 판정 |
|---|---:|---:|---|
| Recall | 70.0% (7/10) | 75% 이상 | 미달 |
| False alarm/min | 2.92 | 0.2 이하 | 미달 |
| 평균 감지 지연 | 0.40초 | 2초 이하 | 통과 |
| 중복 Event 영상 수 | 1 | 0 | 미달 |
| 평가 오류 영상 수 | 0 | 0 | 통과 |

결과 파일은 `outputs/fall_eval/validation_final.json`이다. 놓친 낙상은
`S7_fall_backwards`, `S7_fall_sitting`, `S8_fall_right` 3개이며, 이 영상들은
실제 낙상 시점 전에 발생한 Event가 cooldown으로 이어져 실제 낙상 구간의
Event를 막은 사례를 포함한다. no-fall 영상의 false alarm은
`S7_sit_down`에서 2건 발생했고, `S8_fall_backwards`는 Event가 2건 발생했다.

따라서 Development에서의 목표 달성만으로 운영 사용 가능하다고 판단하지 않는다.
초기 평가에서는 개발/검증 분리 원칙을 지켜 이 결과를 보고 재튜닝하지 않았고,
`--fall-detection-enabled`의 기본값을 `false`로 유지했다. 실제 키즈카페/IP
카메라 데이터와 temporal 동작 분류를 포함한 후속 검증이 필요하다.

## 7. Subject 9-10 사용 확인

Subject 9-10 holdout은 로컬 원본 데이터에 존재하더라도 학습,
체크포인트 선택, 임계값 튜닝, Development/Validation 평가에 사용하지 않았다.
`generate_caucafall_annotations.py`와 `evaluate_fall.py`는 holdout split을 코드
수준에서 차단한다(`guard_holdout`, `_contains_holdout_segment`). Holdout 평가는
설정 동결 후 최종 평가까지 보류한다.

## 8. Fine-tuning 및 파이프라인 통합

### 8.1 Subject 단위 fine-tuning

bbox+pose 규칙만으로 깊이 방향 낙상을 안정적으로 구분하기 어려워,
CAUCAFall의 프레임별 `nofall`/`fall` bbox 라벨로 `yolo26n.pt`를 2-class
**detector**로 fine-tuning했다. 기존 사람 탐지·ByteTrack/PoseTracker를
대체하는 모델이 아니라, `FALL_SUSPECT` 판단에 보조 근거를 주는 모델이다.

학습/평가 분할은 인접 프레임이 서로 다른 split에 섞이지 않도록 Subject 단위로
고정했다.

| Subject | 역할 |
|---|---|
| 1-5 | fine-tuning 학습 |
| 6 | 내부 검증(val), 모델 선택·early stopping |
| 7-8 | 초기 Event-level Validation, 이후 진단·튜닝 데이터 |
| 9-10 | 최종 Holdout, 접근 금지 |

`best.pt`는 Subject 1-6 전체로 재학습하지 않고, Subject 6 internal validation
기준으로 선택된 체크포인트를 그대로 사용했다. 학습 데이터 준비에서는 손상된
`S6_fall_backwards` AVI가 아니라 PNG/txt 라벨만 사용한다.

학습 데이터 생성 과정에서는 원본 파일·라벨 이상 3건을 재현 가능하게 처리했다.
`prepare_fall_training_data.py`가 PNG/txt 쌍을 모으는 과정에서 CAUCAFall
원본 파일명은 변경하지 않는다.

- `Subject.2/Fall backwards/cas200091 - copia.png`: 대응 라벨이
  `cas200091.txt`(" - copia" 접미사 없음)로 존재한다. 정확한 stem 매칭이
  실패하면 이 접미사만 제거해 재시도하고, 복구 후보가 정확히 1개일 때만
  연결한다(숫자 기반 추측 매칭은 하지 않음). 실제 실행에서 1건 복구됨.
- `Subject.5/Kneel/ars500236.png`, `Subject.6/Walk/cams600260.png`: 라벨이
  실제로 존재하지 않는다. `--missing-label-policy=skip`으로 실행하면 해당
  프레임만 제외한다(기본값은 `error`로 조용히 넘기지 않음). 실제 실행에서
  2건 제외됨.

`--dest`에 남는 `dataset_manifest.json`에 입력 PNG 수, 매칭 수, copia 복구
경로, 라벨 누락 제외 경로, train/val Subject, split별 클래스 프레임 수를
모두 기록한다. 실제 생성 결과(Subject 1-5 train / Subject 6 val):

| split | 프레임 수 | nofall | fall |
|---|---:|---:|---:|
| train | 9,115 | 6,431 | 2,684 |
| val | 2,181 | 1,425 | 756 |

Colab 학습은 15 epoch에서 early stopping으로 끝났으며, Subject 6 프레임 단위
검증에서 `fall` 클래스 Recall 82.8%, mAP50 90.2%, mAP50-95 68.5%를 기록했다.
이는 프레임 단위 detector 지표이며, 영상당 `FALL_SUSPECT` 생성 여부를 보는
Event-level Recall과 같은 값이 아니다.

PoC 실행용 보조 모델은 `outputs/fall_training/models/fall_detector_v1.pt`이며 SHA-256은
다음과 같다.

```text
5985d5a24db8b69bf0d231644a4c7a71f6a1143724ed7df2be6d669373c83da7
```

학습 run 산출물은 `outputs/fall_training/colab_run/fall_detector/`에 보관하며,
팀 공유본은 Google Drive `kidcafe-data/fall-training/`에 모델 파일과 run archive를
함께 보관한다. `run_manifest.json`은 모델 SHA-256, 학습 설정, 환경 정보를 기록한다.

### 8.2 Track-모델 매칭과 bounded temporal voting

`AuxiliaryFallModel`은 fine-tuned detector의 fall/nofall bbox를 만들고,
`match_detections_to_tracks()`가 같은 프레임의 Track과 IoU 0.3 이상일 때만
연결한다. 이 매칭 결과는 `FallPipeline`을 통해 `FallDetector.process()`에
Track별 `FallModelEvidence`로 전달한다.

프레임 단위 `nofall` 한 번으로 누적 근거가 사라지는 문제를 피하기 위해,
최근 0.5초 안의 `fall` 근거 시간을 합산하는 bounded temporal voting을 사용한다.
합계가 0.2초 이상일 때 model confirm 조건을 만족한다. `nofall`/`unknown`은
즉시 누적값을 초기화하지 않으며, 오래된 근거만 윈도우 밖으로 만료된다.
모델 경로를 전달하지 않으면 이 근거는 완전히 비활성화되어 기존 bbox+pose
동작을 유지한다.

### 8.3 Model-assisted candidate 진입

Tune 11에서 놓친 영상 12개 중 11개는 `fall_start_frame`에 활성 Track이 없었다.
낙상 후 새 Track이 이미 누운 상태로 재획득되면 bbox 동적 변화가 없어 기존
candidate 진입 조건을 만족할 수 없다. 이를 해결하기 위해 모델의 최근 fall
근거가 0.1초 이상이면 bbox 동적 근거 없이도 `FALLING_CANDIDATE`에 진입하도록
보완했다. 모델 1프레임만으로 Event를 만드는 것이 아니라, 이후 0.2초 model
confirm 또는 기존 bbox/pose confirm을 추가로 통과해야 한다.

이 변경으로 Development Event Recall은 58.6%에서 82.8%로 상승했다. Track이
전혀 없는 프레임에서는 여전히 Event를 만들지 않으며, 정식 ReID는 이번 범위에
포함하지 않는다.

### 8.4 공간 기반 cooldown 승계

새 Track ID가 기존 cooldown을 잃어 같은 낙상을 다시 확정하는 문제는
`_CooldownTombstone`과 IoU 기반 cooldown 승계로 완화했다. 설정값
`cooldown_inherit_iou_threshold=0.3`은 같은 video source 안에서만 적용하며,
만료된 tombstone은 매 프레임 정리한다. Tune 12의 중복 Event 2건은 Tune 13에서
0건으로 감소했고 Recall, false alarm, 지연값은 유지됐다.

### 8.5 초기 Development 동결 설정과 해석

Development 최종 평가는 아래 설정을 사용한다.

```text
fall_model_conf = 0.5
fall_model_iou_threshold = 0.3
model_vote_window_sec = 0.5
model_candidate_entry_sec = 0.1
model_confirm_sec = 0.2
cooldown_inherit_iou_threshold = 0.3
```

이 값은 초기 V1 실험에서 Subject 1-6 Development로 고정했고 첫 Subject 7-8
평가 뒤에는 변경하지 않았다. 이후 Annotation V2와 Track handoff 안정화 결과는
10절에 별도로 기록한다. 오탐 목표를 충족하지 못했으므로 현재 모델은 실시간
PoC의 선택적 기능이지 운영 환경에서 기본으로 켜는 기능은 아니다.

### 8.6 `main.py` 통합

`--fall-detection-enabled`를 명시한 경우에만 `FallPipeline`을 생성한다. 기본값은
`false`이며, 기본 실행은 기존 `yolo26n.pt` + `ByteTracker` 경로를 그대로 사용한다.
낙상 감지를 켜면 기본 tracker는 `yolo26n-pose.pt` + `PoseTracker`로 바뀌고,
`--fall-model-path`를 지정하면 fine-tuned 보조 모델까지 함께 사용한다.

확정된 `FALL_SUSPECT` Event는 기존 `EventWriter` 로컬 저장과 비차단 API
dispatcher 경로를 재사용한다. CAUCAFall `S1_fall_backwards` 파일을
`--fall-detection-enabled`와 `fall_detector_v1.pt`로 실행한 짧은 E2E에서
`FALL_SUSPECT` 1건이 로컬 JSONL, FastAPI 이벤트 조회, SQLite `events` 테이블,
React Dashboard 이벤트 화면까지 전달되는 것을 확인했다. 실행 중 Live Frame도
Dashboard에 표시되는 것을 확인했다. 이는 파일 입력 기준의 연결 검증이며,
장시간 실행, IP 카메라 hard-negative 평가, Holdout 및 외부 데이터 평가는 후속
범위로 남긴다.

같은 영상·720x480·MPS·FastAPI·Live Frame 조건에서 `--fall-detection-enabled`만
제외한 기본 경로(`yolo26n.pt` + ByteTracker)도 한 번 실행했다. 워밍업 이후
progress 출력(frame 31/61/91/121)의 단순 평균은 기본 경로 12.5 FPS, 낙상 opt-in
경로(`yolo26n-pose.pt` + PoseTracker + 보조 detector) 7.9 FPS로 기록됐다.
짧은 파일의 4개 표본 기준 약 4.6 FPS(36.9%) 차이이며, 모델·tracker가 함께
바뀌는 실제 opt-in 기능 전체의 비교다. 이 값은 장시간 성능 벤치마크나 IP 카메라
성능을 대표하지 않는다. 동일 능동 인원 영상을 3회 반복한 정식 통합 측정은
11.2절에 기록하며, 장시간/IP 카메라 평가는 Phase 4로 이관한다.

## 9. `FALL_SUSPECT.cause` 외부 접촉 원인 후보 추정

### 9.1 설계 요지

`src/safety/fall_cause_attributor.py`(`FallCauseAttributor`)가
`FALL_CONFIRMED` 순간에만 호출된다. 매 프레임 별도 추론이나 모델 호출을
하지 않으며, `FallDetector`가 낙상 판정에 쓰는 `MultiTrackHistory`와는
완전히 독립된 자체 이력(Track별 foot_point·bbox 높이·시각)을 갖는다 —
attribution에 필요한 lookback을 위해 낙상 판정용 이력 window를 늘리면
이미 튜닝·동결한 속도/변화율 계산과 평가 수치가
조용히 바뀔 위험이 있었기 때문이다(`docs/decisions.md` ADR-016 참고).

낙상 시작 시각은 confirm 시각이 아니라 `FALLING_CANDIDATE` 진입 시각을
쓴다(운영상 onset proxy이지 임상적 충돌 시점이 아니다). `FallDetector.
_confirm_fall()`은 이 값(`state.candidate_since_sec`)을 cleanup 중 `None`으로
리셋하므로, attribution에 넘기기 전에 반드시 로컬 변수로 먼저 꺼내둔다 —
순서를 반대로 하면 항상 `None`이 들어가 `cause`가 절대 채워지지 않는다.

후보 조건(전부 만족해야 함): 같은 `video_source`, 피해 Track 자신 아님,
lookback 구간(`[fall_start_sec - lookback_sec, fall_start_sec]`, 기본
1.0초) 안에 피해자·후보 모두 최소 샘플 수 이상, 후보의 전체 이력 중 가장
오래된 샘플이 `fall_start_sec` 이전(낙상 시작 "뒤"에 처음 등장한 Track은
제외), 정규화 최소 거리가 `distance_threshold`(기본 1.5, victim bbox 높이
기준 정규화) 이내, 순 접근 속도(정규화)가 `min_closing_speed_norm`(기본
0.1) 이상(멀어지거나 정지한 경우는 제외). 점수는 근접도와 접근 속도의
가중합이며, 동점은 (score 내림차순 → min_distance_norm 오름차순 →
track_id 오름차순)으로 결정적으로 처리한다.

`configs/fall_detection.json`의 `"cause_attribution"` 하위 섹션에서
설정을 로드한다(`FallDetectorConfig`와는 독립된 `FallCauseAttributorConfig`
가 이 섹션만 읽고, `FallDetectorConfig.from_file()`은 반대로 이 섹션을
걸러내 서로 간섭하지 않는다). `4.0초`인 `history_window_sec`/
`track_grace_sec`는 기본 `fall_candidate_timeout_sec`(2.0초) + lookback
(1.0초) + 여유를 덮도록 정했다 — candidate가 타임아웃 근처까지 버티다
confirm돼도 lookback 구간 이력이 이미 잘려나가지 않게 하기 위함이다.

### 9.2 main.py/evaluate_fall.py 연동 범위

`FallPipeline`은 `fall_config_path` keyword 인자를 받아 그 경로의
`"cause_attribution"` 섹션을 로드한다. `src/main.py`(`--fall-config`가
가리키는 경로)와 `scripts/evaluate_fall.py`(`--config`가 가리키는 경로)
모두 이미 갖고 있던 그 경로를 `FallPipeline(...)` 호출에 그대로 한 번 더
전달하도록 배선했다 — 새 CLI 옵션이나 새 계약을 추가한 것이 아니라, 기존
`FallDetectorConfig`용 경로를 `FallCauseAttributorConfig`에도 재사용한
것이다. 따라서 `configs/fall_detection.json`의 `"cause_attribution"`
섹션(`enabled`, 각 threshold, history/grace, score weight 등)을 고치면
`main.py`/`evaluate_fall.py` 실행 모두에 그대로 반영된다.

### 9.3 검증 데이터 정책

구현 자체에는 외부 데이터셋이 필요 없었다. 정식 자동 테스트는
`tests/test_fall_cause_attributor.py`(후보 탐색·점수 계산·tie-break·
독립 이력 유지 범위를 합성 시나리오로 검증)와 `tests/test_fall_detector.py`
·`tests/test_fall_pipeline_module.py`(candidate 진입 시각 캡처, 실제 낙상
confirm 시 cause 연결까지 mock 없이 end-to-end로 검증)로 커버했다.

CAUCAFall은 주로 단일 인원 낙상 데이터라 원인 후보 정확도를 증명하는
데이터가 아니다. Phase 3에서는 합성 multi-track 시나리오로 후보 생성,
자기 Track 제외, 근거 부족 시 `cause=null` 계약을 검증한다. 구현 당시
MPFDD 공개 샘플의 파일명·설명을 검토했지만 원인 Track 라벨과 라이선스가
명확하지 않아 실제 평가나 임계값 선택에는 사용하지 않았다. 실제 접촉 원인
후보 정확도(precision/recall, false attribution)는 Phase 4에서 안전하게
재연하고 정답 Track·접촉·낙상 시점을 라벨링한 영상 또는 권한과 원인 라벨이
명확한 외부 데이터로 평가한다.

### 9.4 알려진 한계

- 2D 화면상 근접은 실제 접촉을 보장하지 않는다 — `cause`는 "외부 접촉
  의심 후보"이지 충돌·인과관계를 확정하는 기능이 아니다.
- ReID가 없어 Track ID가 낙상 직전 바뀌면(재획득) 후보 연속성이 끊길 수
  있다 — 그 Track의 이력 시작 시각이 `fall_start_sec` 이후라면 설계 요지의
  "낙상 시작 뒤에 처음 등장한 Track 제외" 규칙에 걸려 후보에서 빠진다.
- 다중 인원이 근접한 상황에서 false cause(원인이 없는데 후보가 잡히는
  경우) 가능성이 있다 — 정량 평가는 Phase 4로 남겨뒀다.
- `distance_threshold`·`closing_speed_threshold`·`score_threshold` 등은
  튜닝된 값이 아니라 초기 PoC 기본값이다.

## 10. Track ID 안정화와 잔존 오탐 진단

동결한 상태머신·cause attribution 로직 자체는 바꾸지 않고,
ByteTrack/PoseTracker의 ReID 부재로 Track ID가 바뀌는 경우에 대한 견고성만
보강한다. Annotation V2(2절의 onset/impact/lying-start 재라벨링), 평가
프로토콜 V2(`timely_recall` 주 지표, `scripts/evaluate_fall.py`의
`event_diagnostics` — Event별 `track_id`/`confirm_path`/
`candidate_entry_reason`을 label·timely 구간과 무관하게 기록), Signal
Cache(`scripts/cache_fall_signals.py` + `scripts/evaluate_fall_from_cache.py`,
YOLO 추론과 상태머신 평가를 분리해 설정을 바꿔가며 반복 평가할 때 재추론을
피함) 위에서 구현·검증했다.

### 10.1 Candidate Handoff

confirm 이전(`FALLING_CANDIDATE`) 단계에서 Track을 놓치면 새 Track은
NORMAL부터 다시 시작해 최소 지속시간을 다시 채우지 못해 Event를 놓칠 수
있다. Track이 사라진 바로 그 프레임에 tombstone(`_CandidateTombstone`,
`src/safety/fall_detector.py`)을 등록하고, IoU·정규화된 foot_point 거리를
모두 만족하는 새 Track에 `candidate_since_sec`·`max_descent_score`를
승계한다(정적 지속시간 필드는 승계하지 않아 즉시 확정을 막는다). 승계
과정에서 발견·수정한 실제 버그:

- 승계 성공 후 원본 `_TrackState`를 지우지 않으면 다음 프레임에
  tombstone이 재생성돼 다른 Track이 같은 candidate를 중복 승계할 수 있다.
- `1 → 2 → 1`처럼 alias가 원래 track_id로 돌아오는 경우, 전체 alias를
  무조건 삭제하면 방금 승계받은 현재 Track의 상태까지 지워진다 —
  `source_track_id`(tombstone을 만든 바로 그 소실 시점 id)만 재등장
  취소 대상으로 삼고, 그 외 alias는 정상 승계 경로로 처리해야 한다.
- tombstone 재등장 취소 로직이 "source_track_id가 재등장하면 자기 상태가
  살아있다"고 무조건 가정했는데, `track_grace_sec`이
  `candidate_handoff_ttl_sec`보다 짧은(둘 다 기본값 사용 시 0.5s <
  1.0s) 설정에서는 그 가정이 깨진다 — 소실 중 자기 상태가 이미
  `_forget_lost_tracks()`로 지워진 뒤 재등장하면 "취소"가 아니라 handoff로
  재구성해야 한다.

### 10.2 Cause attribution 호환(victim_track_id_aliases)

`FallCauseAttributor`는 `FallDetector`와 완전히 독립된 자체 이력을 쓴다
(9절의 설계 요지 참고). Candidate Handoff로 피해자의 track_id가 승계 전후로 바뀌면, 확정
시 최종 track_id만 넘길 경우 lookback 구간(`fall_start_sec` 기준 최대
`lookback_sec` 이전)이 handoff 이전 시각까지 걸쳐 있어도 그 구간의 victim
샘플을 못 찾아 근거가 있어도 잘못 `cause=None`이 될 수 있다.
`_confirm_fall()`이 `state.origin_track_ids`를 리셋 전에 캡처해
`attribute()`의 `victim_track_id_aliases`로 함께 넘기고,
`FallCauseAttributor`는 그 alias들의 이력도 victim 샘플에 병합하고
후보(가해자 의심 Track) 목록에서는 제외한다(자기 자신의 예전 track_id를
스스로의 낙상 원인으로 지목하는 자기 참조 방지). 기존 호출은 새 파라미터의
기본값(빈 집합)으로 완전히 하위 호환된다.

### 10.3 Cooldown Handoff

confirm 이후(`COOLDOWN`) 단계에서도 같은 문제가 발생한다. 기존 공간 기반
cooldown 승계(8.4절, `_try_inherit_cooldown`)는 confirm 시점 bbox를 IoU로만
비교하고, tombstone도 `cooldown_until_sec`이 지나면 함께 만료된다. 두
가지 실패 모드를 Subject 7-8 진단(S7_fall_right, S8_fall_backwards)에서
확인했다.

- **S7_fall_right**(같은 track_id 재확정): Track이 소실된 채로
  `cooldown_until_sec`을 넘기면 `_forget_lost_tracks()`가 COOLDOWN 예외
  보존을 거둬 `_TrackState`를 지운다. 그 뒤 같은 track_id가 재등장하면
  "회복했다"는 근거 없이 새 NORMAL부터 시작해 재확정된다.
- **S8_fall_backwards**(다른 track_id로 재확정): 재검출 시 자세가 조금
  바뀌어 confirm 시점 bbox 기준 IoU(0.2466)가
  `cooldown_inherit_iou_threshold`(0.3)에 못 미친다.

Candidate Handoff와 같은 패턴으로 별도 tombstone(`_CooldownHandoffTombstone`)
을 두되, 두 지점을 다르게 설계했다.

- 만료를 `cooldown_until_sec`이 아니라 **`max(cooldown_until_sec,
  last_seen_sec + cooldown_handoff_ttl_sec)`**로 판정한다. TTL만 쓰면
  cooldown이 아직 한참 남았는데도 먼저 만료될 수 있다 — S8_fall_backwards의
  실제 소실 간격은 3.1초(마지막 관측 frame95 → 재등장 두 번째 관측
  frame157, `FallFeatureExtractor`가 history 샘플 2개를 요구하므로 첫
  관측이 아니라 두 번째 관측 시점이 실제 판정 프레임이다)로 최초 TTL
  기본값(2.0초)보다 길었지만, 그 시점 `cooldown_until_sec`(confirm 시점
  기준 아직 안 지남)이 하한이 되어 커버됐다. TTL 자체(기본 3.5초)는
  cooldown이 짧게 설정된 경우를 위한 추가 여유분이다.
- IoU(`cooldown_handoff_iou_threshold`, 0.2 — 기존 0.3보다 낮음)와
  정규화된 foot_point 거리(`cooldown_handoff_max_foot_distance_norm`,
  0.5)를 Candidate Handoff와 동일하게 **AND**로 결합한다. OR 조건은 근처에
  선 다른 Track에도 foot 거리만으로 COOLDOWN을 잘못 승계할 수 있다.
- 소실 직전 마지막 관측 bbox(`last_bbox`) 기준으로 비교하면 confirm 시점
  bbox보다 정확하다 — S8_fall_backwards 실측 기준 last_bbox 비교 시 IoU
  0.68, foot 거리 정규화 0.069로 여유 있게 통과한다(confirm 시점 bbox
  기준 0.2466/0.3763보다 훨씬 낫다).
- Candidate Handoff와 동일한 재등장-취소 가정 오류(source_track_id
  재등장 시 자기 상태가 살아있다는 가정이, COOLDOWN 예외 보존 기간이 지난
  뒤에는 깨짐)가 여기서도 있어 함께 고쳤다(Candidate Handoff의 세 번째 항목과 동일한
  버그).

**추가로 발견한 별개 버그(S6_fall_backwards)**: `_advance_cooldown()`이
`_advance_candidate()`의 회복 판정(`_is_recovered` + `recovery_duration_sec`
+ `recovery_confirm_sec` 지속 요구)과 달리, cooldown 만료 후 단일 프레임만
"쓰러지지 않음"으로 보여도(모델이 한 프레임만 `"unknown"`을 반환한 경우
포함) 즉시 NORMAL로 전이했다. 그 프레임의 실제 `aspect_ratio`는 1.087로
`normal_aspect_ratio_threshold`(0.9)에도 못 미쳐 실제 회복이 아니었다 —
곧바로 모델이 다시 fall을 반환하며 재확정돼 중복 Event가 생겼다.
`_advance_cooldown()`도 동일한 `_is_recovered`/`recovery_duration_sec`
로직을 쓰도록 통일했다.

### 10.4 V2 캐시 재평가 결과 (`configs/fall_detection.json` 동결)

| 지표 | 안정화 중간 기준 | 현재 동결 기준 |
|---|---:|---:|
| Development Recall | 83.3% (25/30) | 83.3% (25/30) |
| Development timely Recall | 63.3% (19/30) | 66.7% (20/30) |
| Development 중복 Event | 1건(S6_fall_backwards) | 0건 |
| Subject 7-8 Recall | 100% (10/10) | 100% (10/10) |
| Subject 7-8 timely Recall | 90% (9/10) | 90% (9/10) |
| Subject 7-8 FAR | 2.92/min | 2.34/min |
| Subject 7-8 중복 Event | 2건(S7_fall_right, S8_fall_backwards) | 0건 |

Development timely Recall 상승(S5_fall_sitting: late frame103 →
timely frame82, `candidate_entry_reason="handoff"`)은 Cooldown Handoff가
아니라 Candidate Handoff의 재등장-취소 버그 수정이 원인이다 — Track이
candidate 진행 중 한 번 소실됐다가 같은 track_id로 재등장했을 때, 예전엔
tombstone이 잘못 취소돼 진행 상황이 사라지고 NORMAL부터 다시 쌓여야 했던
것이 정상 복구됐다. Subject 7-8 FAR 개선(S7_sit_down 오탐 2건 중 1건의
재확정 억제)은 Cooldown Handoff 자체의 효과다.

### 10.5 잔존 오탐 4건과 규칙 기반 게이트를 보류한 이유

Cooldown Handoff 이후 Subject 7-8에 남은 오탐은 전부 no_fall 영상 4개
(S7_kneel, S7_pick_up_object, S7_sit_down, S8_sit_down)에서 각 1건씩,
모두 `candidate_entry_reason="model"` · `confirm_path="model"`이다.
temporal vote(K-of-N + max-gap) 확장과 약한 motion 게이트(aspect_ratio
하한, 속도 하한)를 캐시 데이터로 직접 검증했으나 둘 다 채택하지 않았다.

- 이미 `model_vote_window_sec`(0.5초) 기반 bounded temporal voting을
  쓰고 있다. Event를 유발한 최초 연속 오분류 구간은 5-28프레임이고,
  영상 전체의 최장 연속 오분류 구간은 5-85프레임이다. 짧게 흩어진
  confidence 흔들림이 아니라 모델이 해당 동작(무릎 꿇기·줍기·앉기)을
  지속적으로 `fall`로 오분류한 것이므로 temporal vote를 더 엄격하게
  만들어도 근본적으로 걸러지지 않는다.
- 진짜 model-only TP인 S8_fall_forward의 `aspect_ratio`(0.34-0.4)가
  오탐인 S7_sit_down의 `aspect_ratio`(0.33-0.41)와 사실상 구분되지
  않는다. 속도도 마찬가지로 겹친다(일부 정상 앉기 동작이 실제 낙상보다
  순간 속도가 더 크다). 단순 aspect_ratio/속도 하한 게이트는 오탐 제거가
  아니라 진짜 TP를 잃는 교환에 가깝다.
- 최근 bbox/Pose 보조 근거(예: 최근 0.5초 Pose 값 0.2 이상)를 model→model
  confirm에 추가로 요구하는 규칙을 캐시 기반 오프라인 분석으로 비교한 결과, Subject 7-8
  FAR는 0/min까지 떨어지지만 Development의 `S4_fall_sitting`
  TP(`aspect_ratio` 약 0.49, Pose 약 -0.31, 강한 동적 근거도 없음)를
  함께 잃는다(Development Recall 83.3%→76.7%, timely Recall
  66.7%→63.3%). 오탐 제거가 아니라 Precision-Recall 교환이다.

즉 잔존 문제는 임계값이 부정확한 게 아니라, 보조 fine-tuned 모델이
"앉기·무릎 꿇기·줍기"와 "낙상"을 bbox/Pose 수준의 정적·동적 특징만으로는
의미적으로 구분하지 못하는 것이다. 규칙을 더 얹기보다 실제 오탐 구간을
선별한 hard-negative 재학습이나 Phase 4의 경량 temporal classifier로
전환하는 쪽이 맞다 — 이 결정에 따라 규칙 기반 게이트는 구현하지 않았다
(기본 비활성 실험 옵션으로도 추가하지 않기로 함, 불필요한 표면적을 늘리지
않기 위함).

**중요한 방법론적 주의**: 이 진단 과정에서 S7·S8(Validation) 영상을 직접
보고 규칙을 설계·검증했다 — 즉 이 시점부터 `validation/` split은 더 이상
"보지 않은 최종 검증 데이터"가 아니라 **tuning/diagnostic 데이터**로
전환됐다. Cooldown Handoff까지의 설정을 최종 동결한 뒤에는 Subject 9-10
(holdout) 또는 별도 외부 데이터로 최종 평가해야 하며, Subject 7-8 수치를
그대로 "최종 성능"으로 보고하면 안 된다.

### 10.6 전체 활동 프레임 hard-negative 재학습 결과 (미채택)

Phase 3 종료 전 추가 실험으로 Subject 7·8의 무릎 꿇기·물건 집기·앉기
활동 전체 프레임을 `nofall` 학습 데이터로 보강하고, 반대 Subject에서
교차 평가했다.

| 실험 | 교차 평가 | Recall | timely Recall | false Event | 판정 |
|---|---|---:|---:|---:|---|
| Subject 7 보강 | Subject 8 | 60% (기준 100%) | 40% (기준 80%) | 0건 (기준 1건) | 미채택 |
| Subject 8 보강 | Subject 7 | 100% | 100% | 2건 (기준 3건) | 단독 통과 |

한쪽 Fold에서 실제 낙상 Recall이 크게 하락했고, 다른 Fold도 운영 FAR 목표를
충족하지 못했다. 따라서 두 가중치와 전체 활동 프레임 보강 방식은 채택하지
않고 기존 `fall_detector_v1.pt`를 유지한다. 연속된 활동 전체 프레임 대신
실제 false Event 주변 구간만 선별하는 방식은 Phase 4 후보로 남긴다.
Subject 9-10 holdout은 이 실험에서도 사용하지 않았다.

## 11. Phase 3 통합 검증

2026-07-22에 동결 모델과 `configs/fall_detection.json`을 그대로 사용해
실행 경로, 계약 전파, 성능 및 API 장애 안정성을 확인했다. 상세 실행 조건과
운영 결과는 `docs/realtime_test.md`의 같은 날짜 항목에 기록한다.

### 11.1 계약과 회귀

- CAUCAFall `S7_fall_backwards` 전체 252프레임에서 frame 83의
  `FALL_SUSPECT` 1건이 JSONL, FastAPI, SQLite, Dashboard에 동일하게
  전달됐다.
- 단일 인원 낙상의 `cause=null`이 유지됐다.
- 고정 `NEARBY_TRACK` fixture는 API, SQLite `cause_json`, Dashboard의
  `외부 접촉 의심 · Track #11` 표시까지 일치했다. 이는 attribution 모델의
  정확도 검증이 아니라 계약 전파 검증이다.
- 실행 중 Live Frame은 JPEG 640×480으로 조회됐고, 종료 후 stale TTL이
  지나면 계약대로 `204`를 반환했다.
- Signal Cache 재생 결과는 Development Recall 83.3%, timely Recall 66.7%,
  FAR 0.0/min, 중복 0건과 S7-8 진단 Recall 100%, timely Recall 90%,
  FAR 2.34/min, 중복 0건으로 동결 기준과 일치했다.

S7-8은 이미 반복 분석에 사용한 tuning/diagnostic split이며 최종 Validation이
아니다. Subject 9-10 holdout은 이번 통합에서도 사용하지 않았다.

### 11.2 성능 판정

동일한 능동 인원 영상에서 각 조건을 warm-up 후 3회 실행하고, frame loop의
최초 30프레임을 제외한 steady-state 중앙값을 비교했다.

| 조건 | FPS | avg latency | p95 latency | max latency |
| --- | ---: | ---: | ---: | ---: |
| 낙상 OFF, API 정상 | 9.461 | 0.106초 | 0.177초 | 0.270초 |
| 낙상 ON, API 정상 | 5.098 | 0.196초 | 0.303초 | 0.461초 |
| 낙상 ON, API 장애 | 4.919 | 0.203초 | 0.345초 | 0.460초 |

낙상 ON의 FPS 감소는 46.1%로 목표(20% 이내)를 충족하지 못했다. 현재 경로는
PoseTracker와 보조 detector를 함께 사용하므로 기능을 opt-in·기본 비활성으로
유지하고, 모델 호출과 추적 비용 최적화는 Phase 4로 이관한다.

API 장애의 추가 FPS 감소는 낙상 ON 정상 대비 3.5%였다. 세 장애 실행 모두
252프레임을 완료했고, 전송 실패 Event는 실행별 실패 JSONL에 보존됐다.
따라서 비차단 전송과 실패 보존 게이트는 통과했다.

`data/videos/test1.mp4`의 첫 600프레임 비교는 유효한 인원 경로가 없어 보조
모델이 lazy load되지 않았으므로 no-person idle path 확인으로만 분류했다.
낙상 기능 비용과 운영 판단은 위 능동 인원 결과를 기준으로 한다.

### 11.3 최종 범위 판정

Phase 3의 낙상 기능은 **정량 한계를 공개한 opt-in PoC**로 통합 게이트를
통과했다. 실제 원인 후보 정확도, 외부 데이터 일반화, Subject 9-10 최종
holdout, 장시간 IP 카메라 안정성, 능동 인원 FPS 최적화는 Phase 4 범위다.

## 12. Pose NORMAL 기반 runtime 최적화

통합 PR 이후 남은 일정에서 모델이나 `FallDetector` 임계값을 바꾸지 않고
보조 detector 호출 비용을 줄이는 opt-in 경로를 검증했다. 모든 active Track이
충분히 관측된 유효 Pose이며 직립·비하강 상태일 때만 RGB 보조 detector를
생략한다. Track 하나라도 신규·Pose 미확인·하강·비정상 자세이면 즉시 원래
보조 경로로 복귀하고, fallback 안에서는 마지막 Track별 evidence를 최대
`interval-1` frame만 유지한다.

이 방식은 ADR-020에서 기각한 Event 확정용 Pose 규칙과 다르다. Event 임계값을
강화하지 않지만, 안전한 정상 frame의 모델 evidence를 `nofall`로 대체하므로
결과 변화 가능성은 전체 Signal Cache로 다시 측정했다.

### 12.1 전체 캐시 회귀

모델과 Track 캐시는 그대로 두고 Pose NORMAL gate와 interval `3`만 적용했다.

| 지표 | Development 기준 | Development 최적화 | S7-8 기준 | S7-8 최적화 |
| --- | ---: | ---: | ---: | ---: |
| Recall | 83.3% | 83.3% | 100% | 100% |
| timely Recall | 66.7% | 66.7% | 90% | 90% |
| False alarm/min | 0.0 | 0.0 | 2.34 | 1.75 |
| 평균 onset latency | 1.006초 | 1.098초 | 0.906초 | 1.006초 |
| 중복 Event 영상 | 0 | 0 | 0 | 0 |

Development에서는 active Track frame의 20.8%, S7-8에서는 24.4%에서만 보조
detector evidence를 새로 사용했다. gate 자체의 평균 계산 시간은 frame당
0.01ms 미만이었다. S7-8 FAR는 약 25% 감소했지만 운영 목표 0.2/min은 여전히
충족하지 못한다. S7-8은 tuning/diagnostic split이며 최종 Validation이 아니다.
Subject 9-10 holdout은 열람하거나 평가하지 않았다.

### 12.2 M1/MPS 단일 파일 측정

`S7_fall_backwards` 252프레임을 API·Live Frame 없이 실행하고 최초 30프레임을
제외한 steady-state를 비교했다. `--infer-device mps`와
`--fall-model-device mps`를 명시했다. 먼저 아래 단일 실행으로 interval 후보를
선택했다.

| 프로파일 | FPS | avg latency | p95 latency | max latency | Event frame |
| --- | ---: | ---: | ---: | ---: | ---: |
| 낙상 OFF | 14.571 | 0.0686초 | 0.0889초 | 0.1307초 | - |
| 낙상 ON, 매 frame 보조 모델 | 7.663 | 0.1305초 | 0.2468초 | 0.4586초 | 83 |
| Pose gate + interval 2 | 12.498 | 0.0800초 | 0.1197초 | 0.1543초 | 87 |
| **Pose gate + interval 3** | **13.568** | **0.0737초** | **0.1178초** | **0.1581초** | **87** |
| Pose gate + interval 4 | 13.755 | 0.0727초 | 0.1150초 | 0.1900초 | 87 |

Interval `4`의 interval `3` 대비 추가 이득은 약 1.4%로 실행 편차 수준이고,
전체 캐시 평균 지연과 evidence 최신성은 interval `3`이 더 보수적이다.
Interval `2`는 같은 frame에 Event를 만들면서 더 느렸다. 따라서 검증
프로파일은 interval `3`으로 고정했다.

선택한 프로파일은 실행 순서 영향을 줄이기 위해 OFF/ON 순서를 교차해 각각
3회 다시 측정했다.

| 조건 | steady-state FPS 중앙값 | OFF 대비 하락률 | Event 재현 |
| --- | ---: | ---: | --- |
| 낙상 OFF | 14.5712 | - | 3회 모두 0건 |
| Pose gate + interval 3 | 13.511 | 7.3% | 3회 모두 frame 87에서 1건 |

절대 목표 11.66 FPS와 상대 하락률 20% 이내를 모두 충족했다. 다만 API·Live
Frame을 제외한 단일 파일 측정이므로 장시간 실행, 다른 하드웨어와 전체 E2E에서
재검증해야 한다. 최적화 프로파일을 채택해도 낙상 기능과 두 최적화 옵션은
기본 비활성이다.

## 13. Phase 4 평가 프로토콜 동결

Phase 4의 공식 평가는 `phase4_fall_eval_v1`을 사용한다. 이 절이 평가
분자·분모의 기준이며, API·artifact schema는 각각 `docs/api_contract.md`,
`docs/interfaces.md`, `docs/data_sources.md`를 따른다.

### 13.1 E0 기준선

```text
model: fall_detector_v1.pt
fall config: configs/fall_detection.json
Pose NORMAL gate: enabled
auxiliary model interval: 3
Development: Subject 1-6
tuning/diagnostic: Subject 7-8
final holdout: Subject 9-10
```

| 지표 | Development | S7-8 tuning/diagnostic |
| --- | ---: | ---: |
| Recall | 83.3% | 100% |
| timely Recall | 66.7% | 90% |
| FAR | 0.0/min | 1.75/min |
| 중복 Event 영상 | 0 | 0 |

S7-8은 학습하지 않는다. S9-10은 모델·tracker·config·threshold·평가 protocol과
evaluator commit을 동결한 뒤 한 번만 평가한다.

공식 결과 JSON에는 다음 실행 조건을 기록한다.

```text
contract_version=phase4_contract_v1
evaluation_protocol_version=phase4_fall_eval_v1
annotation_schema_version
evaluator_git_commit
model_sha256
config_sha256
tracker
tracker_config
device
early_tolerance_sec
timely_window_sec
event_matching_rule
duplicate_rule
far_denominator_rule
```

`annotation_schema_version`은 CAUCAFall 평가에서
`caucafall_annotation_v2`, 직접 촬영 평가에서 `phase4_fall_cause_v1`이다.
평가 규칙 식별자는 다음 값으로 고정한다.

```text
event_matching_rule=first_fall_suspect_in_closed_timely_window_v1
duplicate_rule=second_fall_suspect_from_window_start_to_video_end_v1
far_denominator_rule=processed_no_fall_frames_over_fps_v1
```

### 13.2 Timely·중복·FAR

- timely 인정 구간은
  `[fall_start_frame - round(0.2 * fps), fall_start_frame + round(2.0 * fps)]`
  이며 양 끝을 포함한다.
- 구간 안 첫 `FALL_SUSPECT`만 대표 timely Event로 매칭한다.
- 허용 구간 시작 이후 영상 종료 전 추가 Event는 duplicate로 기록한다.
- FAR는 오류 없이 처리된 no-fall 영상의 모든 `FALL_SUSPECT` 수를
  `processed_frame_count / fps` 합계 분으로 나눈다.
- 오류·스킵 영상이 하나라도 있으면 `evaluation_valid=false`다.

### 13.3 Cause·Track 평가

- Cause는 raw Track ID가 아닌 reviewed actor mapping으로 채점한다.
- reviewed ground truth에 매칭된 대표 Event만 Cause 지표 분모에 포함한다.
- 후보 없음의 `cause=null`, 후보 있음의 actor top-1을 각각 측정한다.
- 분모가 0인 지표는 `null/not_evaluable`이며 목표 통과로 해석하지 않는다.
- ID switch 자체가 아니라 missed·late·duplicate·victim·cause 오류를 실제로
  유발한 경우만 tracker 문제로 판정한다.
- 다중 ID switch는 `track_id_switches.csv`에 전환별로 기록한다.
- 관련 구간에 ID switch와 Event 오류가 함께 있지만 인과가 확인되지 않으면
  `associated`로 기록한다.
- alias 연결 재생 또는 state diagnostic으로 오류가 해소되는 경우에만
  `caused`로 기록한다.
- Event 오류가 없으면 같은 영상에 ID switch가 있어도 `none`으로 기록한다.
- Tracker 비교는 `caused` 오류가 반복 재현될 때만 진행한다.

```text
cause_null_specificity =
  correct_null_count
  / reviewed matched Event 중 cause_candidate_exists=false인 건수

cause_top1_accuracy =
  correct_top1_count
  / reviewed matched Event 중 cause_candidate_exists=true인 건수

false_attribution_rate =
  false_attribution_count
  / cause 평가 가능한 reviewed matched Event 전체
```

후보 있음인데 대표 Event의 `cause=null`이면 `missed_cause_count`에 포함한다.
대표 Event가 없는 낙상은 fall detection miss로 기록하고 Cause 분모에서는
제외한다.

### 13.4 Protocol 변경

Holdout 열람 후 평가 규칙이나 threshold를 변경하지 않는다. 치명적인 평가기
오류를 수정해야 하면 protocol version을 올리고 기존 결과를 보존한 뒤
Development와 S7-8을 전체 재평가한다. 수정된 S9-10 결과에는
`post-hoc protocol correction`을 표시하며 모델 선택에 사용하지 않는다.

### 13.5 공식 평가 실행

현재 `scripts/evaluate_fall.py`와 `scripts/evaluate_fall_from_cache.py`의
공식 모드는 CAUCAFall E0 및 CAUCAFall 회귀 평가 전용이다. 결과는 live
evaluator 또는 Signal Cache replay에 다음 옵션을 명시해 생성한다.

```text
--evaluation-protocol-version phase4_fall_eval_v1
```

이 옵션을 사용하면 CAUCAFall annotation V2, reviewed-only, early tolerance
0.2초, timely window 2.0초를 강제한다. CSV 전체의 상태·구조를 먼저 검증하고,
reviewed fall 행에는 원본 라벨 프레임과 onset·impact·lying 시점을 모두 요구한다.
결과 JSON root에는 13.1의 provenance와 `evaluator_git_dirty`를 함께 기록한다.
`evaluator_git_dirty=true`인 결과는 개발 중 확인용이며, 공식 기준선은 변경 사항을
커밋한 evaluator로 다시 생성한다.

공식 cache replay는 tracker와 보조 모델의 실제 inference device 및 각 모델의
SHA-256을 가진 새 Signal Cache만 허용한다. 이 정보가 없는 Phase 3 legacy cache는
비공식 비교에는 계속 사용할 수 있지만 `phase4_fall_eval_v1` 결과에는 사용할 수
없다. Subject 9-10 cache는 최종 동결 전 생성하지 않는다.

직접 촬영 데이터의 `phase4_fall_cause_v1`·Cause·Track 평가는 촬영 후 전용
annotation loader와 evaluator에서 구현하며, CAUCAFall 전용 CLI가 해당 schema를
처리한다고 해석하지 않는다.

## 14. Phase 4 A2 실제 RGB 데이터 전환

### 14.1 OF-Synthetic 진단 결과와 종료

OF-Synthetic는 실제 학습 전에 E0 취약점을 넓게 찾는 stress test로 사용했다.

| split | 영상 | false Event | FAR | confirm 경로 |
| --- | ---: | ---: | ---: | --- |
| random Train mining cohort | 569 | 125 | 2.6037/min | bbox 84, model 38, pose 3 |
| 독립 synthetic validation | 187 | 41 | 2.5985/min | bbox 26, model 15 |

Train false Event 125건을 사람이 검수한 결과는 hard-negative 111건, 시각적 합성
artifact 13건, 판단 보류 1건이었다. 별도 validation에서도 41건 중 37건이
`lie_down` 또는 `lying`에서 발생했다. 따라서 눕기 동작 취약점은 재현됐지만,
실제 RGB 일반화 성능을 증명한 결과는 아니다.

또한 synthetic validation의 model confirm 15건을 전부 제거한다고 가정해도
rule/bbox 경로 26건이 남아 FAR는 약 1.65/min이다. 보조 모델 재학습 하나만으로
운영 목표 0.2/min을 달성할 수 있다는 가설도 이 결과로 기각한다.

OF-Synthetic는 학습에 넣지 않고 진단을 종료한다. 산출물은 stress-test 이력으로
보존하되 production model 선택에는 사용하지 않는다.

### 14.2 외부 실제 RGB 분할과 판정

실제 RGB 개선 경로는 다음처럼 subject 단위로 고정한다.

| 데이터 | train-candidate | validation | 용도 |
| --- | --- | --- | --- |
| UP-Fall | Subject 1-8, fall 39개·ADL 24개 | Subject 9-10, fall 10개·ADL 6개 | 외부 낙상 Recall·ADL FAR |
| GMDCSA24 | Subject 1-3, 123개 | Subject 4, 37개 | 외부 진단 전용, §14.6 이후 미채택 |

UP-Fall E0 외부 진단 결과는 train-candidate Recall 23.1%, timely Recall 7.7%,
FAR 0.1191/min이고 validation Recall 40.0%, timely Recall 30.0%, FAR 0.0/min이다.
두 분할 모두 중복 Event는 0건이었다. no-fall FAR는 낮았지만 낙상 Recall이 크게
하락했으므로, 이 결과는 CAUCAFall 기반 E0의 카메라·동작 도메인 일반화 한계를
확인한 진단으로만 사용한다. 새 모델이나 runtime 설정을 채택한 결과가 아니다.

`train_candidate`에서만 E0 false Event를 mining하고 사람이 `hard_negative`로
확정한 Event 중 `confirm_path=model` 또는 `candidate_entry_reason=model`인
구간만 보조 모델 학습 후보로 만든다. rule-only Event는 보조 모델 학습으로
해결됐다고 주장하지 않고 별도 temporal/state-machine 분석으로 보낸다.

Validation Subject의 영상을 hard-negative로 추출하거나 학습에 넣지 않는다.
E1 후보와 학습 설정을 동결한 뒤 E0와 E1을 같은 validation에 비교한다.
CAUCAFall Subject 9-10 최종 holdout은 이 외부 validation과 별개로 계속
열람하지 않는다.

### 14.3 실행 도구와 채택 순서

```text
materialize_up_fall_cohort.py
-> train-candidate E0 Signal Cache
-> analyze_real_rgb_false_events.py
-> materialize_real_rgb_false_event_review.py
-> 사람이 검수한 model-involved hard-negative만 E1 후보화
-> CAUCAFall positive replay를 유지해 재학습
-> CAUCAFall Development·S7-8 회귀
-> 실제 RGB validation 비교
-> 설정 동결 후 CAUCAFall S9-10 최종 1회 평가
```

UP-Fall·GMDCSA24 평가는 외부 진단/validation이며 CAUCAFall 전용 공식 모드
`phase4_fall_eval_v1`을 붙이지 않는다. 평가 규칙의 시간 창과 FAR 계산 의미는
동일하게 유지하되, 결과에는 데이터셋·cohort manifest·모델·config checksum을
함께 기록한다.

### 14.4 E1 학습 설계

E1은 실제 RGB 영상 전체를 프레임 단위로 대량 추가하는 실험이 아니다. 먼저
E0로 `train_candidate` Subject를 실행한 뒤 사람이 실제 오탐으로 확정한 Event
중 보조 모델이 후보 진입 또는 확정에 관여한 구간만 사용한다. 쉬운 frame에
학습이 지배되지 않게 실제 오류를 만든 sample을 우선하는 방식은
[OHEM](https://arxiv.org/abs/1604.03540)의 hard-example 선별 원칙과 같다.

학습 데이터 구성:

- CAUCAFall Subject 1-5의 fall frame 전량 positive replay
- CAUCAFall nofall은 Subject·활동별 동일 quota와 시간 간격으로 축소
- UP-Fall `train_candidate`의 reviewed hard-negative
- 직접 촬영 diagnostic에서는 A01 단독 영상만 학습 후보로 사용
- A01 낙상은 onset 직전 nofall과 onset부터 lying 직후까지의 fall frame을 함께 사용
- A01 일상 동작은 검수된 nofall frame으로 사용
- A02는 subject-disjoint diagnostic 비교에만 사용하고 학습하지 않음
- A03 test는 모델·tracker·config 동결 전까지 접근하지 않음
- Event 전후 1초 안에서 실제 auxiliary `fall` detection이 Track에 매칭된 frame
- 최대 3 FPS, Event당 최대 7 frame
- 외부 실제 RGB supplement에는 class 0 `nofall`만 허용
- 직접 촬영 A01 supplement에는 검수 annotation에서 만든 class 0·1을 허용
- CAUCAFall Subject 6 validation은 변경하지 않음

`fall_detector_v1.pt`에서 시작해 낮은 learning rate와 초기 layer freeze를 적용한다.
인접 frame 대량 투입, S7-8 학습, 외부 validation 학습, synthetic 혼합은 하지
않는다. UP-Fall과 직접 촬영 데이터는 모두 통제된 성인 재연 데이터이므로,
아동이 있는 실제 키즈카페 운영 성능으로 일반화하지 않는다.
[UP-Fall 원 논문](https://pmc.ncbi.nlm.nih.gov/articles/PMC6539235/)

E1 채택 조건:

- CAUCAFall Development Recall 83.3% 이상
- CAUCAFall Development timely Recall 66.7% 이상
- CAUCAFall Development FAR 0.0/min 유지
- S7-8 Recall 100%, timely Recall 90% 유지
- S7-8 FAR 1.75/min 이하
- 실제 RGB validation의 false Event 30% 이상 감소
- 실제 RGB validation fall Recall 감소 없음
- 실제 RGB validation timely TP 감소 없음
- false cause 증가 없음
- 중복 Event 증가 없음
- 평균 감지 지연 증가는 0.2초 이내
- 동일 환경 기준 FPS 하락률 20% 이내

Fall 라벨을 가진 외부 실제 RGB validation은 GMDCSA24가 유일했으나 §14.6에서
카메라 구도 불일치로 미채택했다(`docs/data_sources.md` GMDCSA24 진단 종료
판정 참고). 위 두 실제 RGB validation 조건은 8월 7일 직접 촬영 데이터의
manifest·annotation·split을 동결한 뒤 재평가한다.

E1이 auxiliary-model 경로를 줄였지만 실제 RGB 전체 FAR가 남으면 그 결과를
실패로 덮지 않는다. `rule_or_temporal` 경로를 별도 cohort로 고정하고 Pose·bbox
시계열을 쓰는 경량 verifier를 E2로 비교한다. 영상 기반 Pose 시계열이 단일
frame 외형보다 동작 전이를 구분하는 근거는 다음 선행 연구와도 일치한다.
[Video Based Fall Detection Using Human Poses](https://arxiv.org/abs/2107.14633/),
[Falls Prediction Based on Body Keypoints and Seq2Seq](https://openaccess.thecvf.com/content_ICCVW_2019/papers/HBU/Hua_Falls_Prediction_Based_on_Body_Keypoints_and_Seq2Seq_Architecture_ICCVW_2019_paper.pdf)

### 14.5 E1 산출물 흐름

```text
실제 RGB cohort
-> E0 Signal Cache와 split별 평가
-> false Event 원인 분석
-> 짧은 검수 clip과 완료 CSV
-> 검수본 SHA-256 동결
-> 외부 데이터는 model-involved train_candidate nofall supplement
-> 직접 촬영은 A01 단독 영상의 annotation 기반 nofall/fall supplement
-> CAUCA positive replay 학습 목록
-> 낮은 learning rate fine-tuning
-> CAUCA·S7-8·A02 diagnostic 동일 조건 비교
-> 사전 기준 통과 시 A03 test 최종 1회 평가
```

관련 도구:

- `freeze_real_rgb_false_event_review.py`: 완료 검수본·clip 무결성 검증과 동결
- `materialize_real_rgb_e1_frames.py`: 승인된 model-involved nofall frame 생성
- `materialize_phase4_recorded_e1_frames.py`: A01 단독 영상의 nofall/fall frame 생성
- `build_fall_e1_training_dataset.py`: CAUCA replay와 supplement 학습 목록 생성
- `train_fall_detector.py`: 동결 학습 설정과 dataset provenance 기록

실제 RGB 원본, cohort, cache, 검수 clip, frame supplement, 학습 run은 모두
`outputs/` 또는 외부 스토리지에 두고 Git에 포함하지 않는다.

### 14.6 Rule motion gate 실험과 미채택

실제 RGB 검수에서 GMDCSA24 false Event 14건 중 13건이 `bbox` 또는 `pose`
confirm으로 확정됐다. 최근 0.8초 Track 이력의 순 center 이동, 하강 step 비율,
방향 반전을 Cache에서 분석해, bbox 높이의 25% 이상 위로 이동한 Track의 rule
confirm을 막는 후보를 시험했다. 분석 window는 `MultiTrackHistory`와 같은 시간
비교를 사용해 runtime과 경계 sample이 일치하도록 고정했다.

후보 gate는 `model` confirm에는 적용하지 않고, 충분한 Track 관측이 없는 경우에는
기존 경로를 유지했다. 단일 Event의 사전 분석에서는 GMDCSA24 train의 false Event
3건과 validation의 1건을 걸러낼 수 있어 보였다. 그러나 상태머신 Cache 재생 결과는
다음과 같았다.

| 데이터 | E0 false Event / FAR | 후보 gate false Event / FAR | Recall / timely Recall 변화 |
| --- | --- | --- | --- |
| GMDCSA24 train-candidate | 9 / 0.9809 min | 9 / 0.9809 min | 56.9% / 53.4% 유지 |
| GMDCSA24 validation | 5 / 1.5507 min | 4 / 1.2405 min | 73.3% / 66.7% 유지 |
| CAUCAFall Development | 0 / 0.0 min | 0 / 0.0 min | 83.3% / 66.7% 유지 |
| CAUCAFall S7-8 diagnostic | 3 / 1.7518 min | 3 / 1.7518 min | 100% / 90% 유지 |

train의 세 후보는 첫 confirm만 취소된 뒤 0.7-1.0초 후 다시 `bbox` 또는 `model`
경로로 확정됐다. 재진입을 막기 위해 cooldown으로 강제 전이하면 이후 실제 낙상까지
숨길 수 있으며, 더 강한 순이동 임계값은 GMDCSA24 validation의 실제 fall Event를
함께 잃었다. validation false Event 감소도 20%라 Phase 4의 30% 최소 채택 기준에
미달한다.

따라서 이 scalar motion gate는 production config에 추가하지 않는다. Cache 기반
`analyze_fall_motion_coherence.py`는 E2 데이터 진단 도구로 유지한다. 결론은 bbox
방향이나 jitter가 전혀 쓸모없다는 뜻이 아니라, 이 값 하나로는 의도적인 눕기와
실제 낙상을 안전하게 분리할 수 없다는 것이다. 다음 단계는 동일 Track의 bbox와
17개 Pose keypoint 시퀀스를 함께 쓰는 경량 temporal verifier를 E2 후보로
분리해 검증하는 것이다.

### 14.7 GMDCSA24 카메라 구도 불일치와 진단 종료

위 실험 이후 원본 프레임을 직접 확인한 결과, GMDCSA24는 근접 정면(눈높이)
구도로 촬영됐다. 반면 실 배포 예정 카메라와 같은 구도로 확인된 CAUCAFall은
천장 구석·하향각·광각 CCTV 구도다. 현재 낙상 규칙·보조 모델 임계값은 모두
CAUCAFall 기반으로 튜닝돼 있으므로, GMDCSA24에서 유독 낮았던 Recall(56.9%/
73.3%)과 rule-path 의존(false Event 14건 중 13건)은 모델 일반화 실패가
아니라 이 카메라 구도 차이의 증상일 가능성이 크다.

따라서 GMDCSA24는 production 판단 데이터로 채택하지 않고 진단을 종료한다.
§14.4의 실제 RGB validation 채택 기준은 8월 7일 직접 촬영 데이터로 대체한다.
원본·가공 영상·Signal Cache·검수 결과는
재생성 가능하므로 로컬에서 삭제하고, 이 문서의 진단 결과만 이력으로
보존한다. 상세 판정은 `docs/data_sources.md`의 GMDCSA24 진단 종료 판정을
따른다.

### 14.8 촬영 전 실험 종료 상태

2026-08-07 실제 촬영 전까지 OF-Synthetic stress test, UP-Fall 실제 RGB cohort,
GMDCSA24 외부 진단과 scalar motion gate 비교를 완료했다. OF-Synthetic와
GMDCSA24는 학습 또는 production 판단 데이터로 미채택했고, scalar motion
gate도 최소 개선 기준에 미달해 production 동작에 포함하지 않는다.

따라서 촬영 전에는 새 낙상 모델·임계값·runtime 정책을 채택하지 않고 Phase 3
기준선의 Recall·timely Recall·FAR를 유지했다. 이후 직접 촬영 데이터의 검수와
평가는 외부 데이터 진단 결과와 분리해 다음 절부터 기록한다.

### 14.9 직접 촬영 데이터 intake와 검수 기반

2026-08-10에 8월 7일 촬영분 중 A 역할이 사용할 64개 영상을 계약 이름으로
확정했다. 모든 영상은 1920x1080 HEVC, 약 29.97 FPS이며 총 17,778 frame,
593.2초다. 전 frame 디코딩, 파일명·원본 대응, 중복 원본, SHA-256을 검사했다.

| 분할 | Actor | 영상 | fall / no_fall | no_fall 시간 |
| --- | --- | ---: | ---: | ---: |
| diagnostic | A01·A02 | 46 | 32 / 14 | 163.0초 |
| test | A03 | 18 | 14 / 4 | 33.2초 |

A03 test는 모델·tracker·config 동결 전까지 추론하지 않는다. 다중 인원 영상은
A01·A02에만 있어 Cause 결과는 actor-disjoint 일반화가 아닌 diagnostic으로
해석한다. 전체 no_fall 노출도 196.2초뿐이므로 FAR는 Event 원시 건수와 함께
기록하며, 이 촬영분만으로 운영 목표 0.2/min 달성을 확정하지 않는다.

다중 인원 A 평가 영상은 `contact_fall` 8개, `near_pass` 3개,
`occluded_cross` 1개다. 접촉 후 낙상은 계획한 최소 5개를 충족했지만
near-pass와 다중 인원 가림은 각각 5개에 미달한다. 따라서 Cause와 ID switch
결과는 사례 진단으로만 기록하고 일반 성능으로 보고하지 않는다.

재현 도구:

- `build_phase4_recordings_manifest.py`: metadata·split·checksum manifest 생성
- `generate_phase4_fall_annotations.py`: pending 낙상·Cause 검수 초안 생성
- `review_phase4_fall_annotations.py`: first/second reviewer 영상 검수
- `validate_phase4_recordings.py`: 파일·checksum·frame·actor·Cause 계약 검증
- `cache_fall_signals.py --recordings-manifest`: diagnostic 공식 Signal Cache 생성
- `evaluate_fall_from_cache.py --recordings-manifest`: 동결 annotation 기반 E0 평가
- `analyze_phase4_recorded_e0.py`: timely window의 candidate·bbox·Pose·모델 근거 진단

실제 manifest와 annotation은 `outputs/phase4_recorded_eval/annotations/`에 두며
Git에 포함하지 않는다. R01과 R02가 64개를 모두 검수했고 `needs_review` 없이
`reviewed`로 합의했으며, 파일·checksum을 포함한 공식 검증을 통과했다.

- recordings manifest SHA-256:
  `bd1f7b51dab9a5f0fd038ef93b0a5a125ce578138c388996d151989ef0e92837`
- fall/Cause annotation SHA-256:
  `8f0456f9fc5b65192f2df0e96bd434f53700f61918d7586dd294368350ccbe0b`

Diagnostic Signal Cache는 PoseTracker와 기존 `fall_detector_v1.pt`로 46개 영상,
13,452 frame을 오류 없이 생성했다. Phase 3 채택 runtime profile(Pose NORMAL
gate, auxiliary interval 3)과 gate 비활성·interval 1 replay의 Event 결과가
같아, 이번 Recall 저하는 runtime 최적화가 원인이 아니다.

### 14.10 직접 촬영 Diagnostic E0 결과

동결한 `phase4_fall_eval_v1` 규칙으로 diagnostic 46개를 평가했다. 아래 결과는
production 채택 결과가 아니라 E1 개선 후보를 비교하기 위한 E0 기준선이다.

| 지표 | 결과 |
| --- | ---: |
| Recall | 2/32 (6.25%) |
| timely Recall | 1/32 (3.125%) |
| no_fall false Event | 0/14 |
| FAR | 0.0/min |
| late detection | 1개 영상 |
| duplicate Event | 0개 영상 |

Cache 신호를 timely window 기준으로 분해한 결과는 다음과 같다.

- 32/32 fall 영상에서 하강 속도 또는 bbox 높이 수축 candidate 근거가 있었다.
- 기존 수평 bbox 임계값을 한 frame 이상 넘은 fall 영상은 3/32뿐이었다.
- 기존 fallen Pose 임계값을 넘은 fall 영상은 0/32였다.
- 보조 모델이 `fall`로 판단한 frame은 32개 fall 영상 전체에서 0건이었다.
- Track coverage 중앙값은 98.5%였고, 3개 side-fall만 80% 미만이었다.
- 미탐 분류는 확정 근거 부족 28개, tracking 제한 3개, timely 성공 1개다.

즉 candidate 진입이 아니라 확정 경로의 실제 카메라 구도 일반화가 주된
병목이다. 촬영 구도에서는 fall의 최대 bbox aspect ratio 중앙값이 1.09로
기존 임계값 1.3보다 낮고, `head_hip_diff_norm` 최댓값 중앙값도 -0.27로 기존
Pose 임계값 0.2와 방향·범위가 맞지 않았다. 보조 모델도 기존 학습 구도와의
domain shift로 timely window에서 `fall` 신호를 한 frame도 만들지 못했다.

Threshold-only 가능성을 확인하기 위해 같은 Cache에서 소규모 진단 sweep을
실행했다.

| 설정 | Recall | timely Recall | FAR |
| --- | ---: | ---: | ---: |
| 기존 1.3 / confirm 0.5초 | 6.25% | 3.125% | 0.0/min |
| aspect 1.2 / confirm 0.5초 | 12.5% | 9.375% | 0.0/min |
| aspect 1.1 / confirm 0.3초 | 46.875% | 31.25% | 0.0/min |
| aspect 1.0 / confirm 0.3초 | 68.75% | 53.125% | 1.47/min |
| Pose -0.1 | 9.375% | 3.125% | 1.10/min |

FAR 0.2/min 이하를 유지한 설정은 timely Recall 75% 목표에 도달하지 못했고,
Recall을 더 높인 설정은 FAR를 크게 악화시켰다. 따라서 임계값 완화는
production에 채택하지 않는다. 다음 E1 후보는 A01 단독 영상의 검수된 fall
positive와 nofall을 사용한 보조 모델 domain adaptation이다. A02는 학습하지
않은 actor 기준 비교에만 사용하며, 기존 Development·S7-8 회귀와 A02 지표를
모두 통과해야 한다. A03 `test` 18개는 모델·tracker·config 동결 전까지 cache와
evaluator 양쪽에서 계속 차단한다.

### 14.11 직접 촬영 E1 학습 후보 준비

E1은 기존 `fall_detector_v1.pt`에서 시작하는 단일 사전 정의 후보로 제한한다.
CAUCAFall Subject 1-5 positive replay와 균형 nofall을 유지하고, 직접 촬영 A01
단독 영상만 3 FPS로 선별했다. 다중 인원 영상은 자동 victim bbox가 다른 actor를
선택할 위험이 있어 학습에서 제외했다.

| 항목 | 결과 |
| --- | ---: |
| A01 사용 영상 | 17개 |
| 직접 촬영 고유 frame | 239개 |
| nofall / fall | 160 / 79 |
| Track 부재로 제외된 요청 frame | 29개 |
| CAUCA fall replay | 2,684개 |
| CAUCA 균형 nofall | 2,684개 |
| 직접 촬영 가중 반복 | 3회 |
| 최종 train entry | 6,085개 |
| 변경하지 않은 S6 validation | 2,181개 |

직접 촬영 고유 frame은 세 번 반복해 train entry의 약 11.8%를 차지하게 한다.
동일 frame 반복은 새로운 표본 수로 보고하지 않으며 manifest에 고유 frame 수와
가중 entry 수를 분리해 기록한다. A02·A03 경로가 학습 목록에 없음을 생성기가
검증한다.

학습 설정은 `configs/fall_training_e1_recorded.json`으로 고정한다. 낮은 learning
rate, 초기 layer freeze, 기존 모델 warm start를 사용하며 E1 결과를 보고 추가
튜닝하지 않는다. 비교 순서는 S6 학습 validation, A02 diagnostic, CAUCAFall
Development·S7-8 회귀다. 사전 채택 기준을 통과할 때만 A03 test를 한 번 평가한다.

관련 도구:

- `materialize_phase4_recorded_e1_frames.py`: A01 단독 영상의 class 0·1 frame 생성
- `build_fall_e1_training_dataset.py`: CAUCA replay와 직접 촬영 supplement 결합
- `evaluate_fall_from_cache.py`: 직접 촬영 결과의 primary actor별 지표 기록
- `refresh_fall_signal_cache_auxiliary.py`: 기존 Track을 유지하고 E1 신호만 갱신
