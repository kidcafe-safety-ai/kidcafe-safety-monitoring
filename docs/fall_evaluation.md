# Phase 3 FALL_SUSPECT 평가 기록

`feature/fall-detector` (PR2) 낙상 감지 코어의 실측 평가 기록. 데이터·설정·결과를
버전과 함께 남겨, 나중에 같은 조건을 재현하거나 회귀를 확인할 수 있게 한다.

## 1. 데이터셋

- 데이터셋: CAUCAFall V5 (DOI 10.17632/7w7fccy7ky.5, CC BY 4.0)
- 상세 라이선스·체크섬: [docs/data_sources.md](data_sources.md)
- 분할 (docs/data_sources.md, configs/caucafall_v5_split.json과 동일):
  - Development (Subject 1~6): 60개 영상 — fall 30, no_fall 30
  - Validation (Subject 7~8): 20개 영상 — fall 10, no_fall 10
  - Holdout (Subject 9~10): 미사용 (PR4 최종 평가 전까지 접근 금지)

## 2. Annotation 생성·검수

- 생성: `scripts/generate_caucafall_annotations.py`가 CAUCAFall이 이미 제공하는
  프레임별 YOLO 라벨(`class 0=nofall, 1=fall`)에서 class가 0→1로 바뀌는 지점을
  `fall_start_frame` 후보로 자동 추출한다. txt 파일명 숫자는 `subject_id*100000
  + 순번` 형식이라 그대로 frame 번호로 쓸 수 없어 정렬 순서(0-base)를 사용했고,
  txt 개수가 실제 AVI 디코딩 프레임 수보다 많은(관측상 대부분 +1, 최대 +23인
  예외 1건 `S6_fall_backwards` 포함) 경우 초과분은 뒤에서 제외하고 경고로
  남겼다 (`{split}_generation_report.csv`).
- 검수: `scripts/review_caucafall_annotations.py`로 AVI를 순차 디코딩해 사람이
  직접 확인했다. fall 40개(Development 30 + Validation 10) 전부 프레임 단위로
  검수했고, no_fall 40개는 실제 프레임 범위의 class가 전부 0인지 자동 검증
  (`--auto-verify-no-fall`) 후 표본을 사람이 확인했다.
- 감지 지연 기준: `impact_frame`/`lying_start_frame`은 이번 PR2에서 비워두고
  `fall_start_frame` 기준으로 지연을 측정하는 간소화 정책을 채택했다 (40개 영상
  전부에 `impact_frame`을 입력하는 상세 평가는 하지 않음).
- 검수 상태: Development 59개 `reviewed` + 1개 `needs_review`
  (`S6_fall_backwards`, 평가 제외), Validation 20개 `reviewed`.

## 3. 상태머신 설계 변경 (Tune 1)

최초 구현은 "하강 속도 / 높이 수축률 / 수평 자세" 3개 근거 중 2개 이상이 **같은
프레임에** 동시에 있어야 candidate에 진입했다. Subject 1 Fall backwards로
확인한 결과, 실제 낙상은 하강/수축이 먼저 나타나고(frame 68~71) 수평 자세는
한참 뒤(frame 75+)에야 나타나 두 근거가 겹치지 않았고, 그 결과 개발 60개 중
26개가 `event_count=0`으로 아예 candidate에 진입하지 못했다.

**변경**: candidate 진입 조건을 "하강 속도 OR 높이 수축률"(단일 동적 근거)로
완화하고, 수평 자세는 confirm 단계(진입 후 `fall_confirm_sec` 이상 지속)에서만
사용하도록 시간적으로 분리했다. `_is_recovered()`도 이에 맞춰 유지한다
(`src/safety/fall_detector.py` 모듈 docstring 참고).

## 4. Development 평가 결과

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
0건)를 모두 만족했다. 이 수치는 Subject 1~6 개발 데이터에서 설정을 고른
결과이므로, 운영 성능의 증명은 아니며 Subject 7~8 Validation 결과와 분리해
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
| Fall backwards | ~1.60 | O |
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
결과, `nose_y - hip_y`가 서 있을 때는 음수(-52~-67)였다가 쓰러진 뒤에는
양수(+57)로 부호가 뒤집힌다 — bbox aspect_ratio로는 잡지 못한 자세 변화를
keypoint 관계로는 명확하게 포착한다.

**1차 시도(폐기): 어깨-엉덩이 벡터 각도(torso_angle)**. 수직 기준 각도가
`pose_horizontal_angle_threshold_deg` 이상 지속되면 confirm하는 방식으로
구현·평가했으나(Recall 20%, `development_tune_02_pose_confirmation.json`),
`S1_fall_forward`를 프레임 단위로 직접 추적한 결과 각도가 60° 이상으로
올라가는 프레임이 사실상 1개(frame 142, 37.5~71.8° 순간 스파이크)뿐이었다.
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
자세 변화 중 자주 떨어지므로(관측: 0.9 → 0.16~0.48) 코 → 눈 평균 → 귀 평균
순 fallback을 쓴다. Subject 1 Development 실측 결과 낙상 지속 구간
최소값(~0.24)과 일상 동작 최댓값(~0.16)이 겹치지 않아 벡터 각도보다 훨씬
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

## 6. Validation (Subject 7~8)

Tune 13 설정과 `fall_detector_v1.pt`를 동결한 뒤 Subject 7~8 20개 영상에서
한 번 실행했다. 이 결과를 확인한 뒤에는 임계값·모델을 다시 조정하지 않았다.

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
이번 PR에서는 개발/검증 분리 원칙을 지켜 Validation 결과를 보고 재튜닝하지
않았고, `--fall-detection-enabled`의 기본값을 `false`로 유지한다. 실제
키즈카페/IP 카메라 hard-negative 데이터와 함께 오탐을 줄이는 후속 실험이
필요하다.

## 7. Subject 9~10 사용 확인

Subject 9~10 holdout은 로컬 원본 데이터에 존재하더라도 이번 PR2의 학습,
체크포인트 선택, 임계값 튜닝, Development/Validation 평가에 사용하지 않았다.
`generate_caucafall_annotations.py`와 `evaluate_fall.py`는 holdout split을 코드
수준에서 차단한다(`guard_holdout`, `_contains_holdout_segment`). Holdout 평가는
PR4 최종 평가 전까지 보류한다.

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
| 1~5 | fine-tuning 학습 |
| 6 | 내부 검증(val), 모델 선택·early stopping |
| 7~8 | 모델·설정 동결 후 Event-level Validation 1회 |
| 9~10 | PR4 Holdout, 접근 금지 |

`best.pt`는 Subject 1~6 전체로 재학습하지 않고, Subject 6 internal validation
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
모두 기록한다. 실제 생성 결과(Subject 1~5 train / Subject 6 val):

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

### 8.5 Development 동결 설정과 해석

Development 최종 평가는 아래 설정을 사용한다.

```text
fall_model_conf = 0.5
fall_model_iou_threshold = 0.3
model_vote_window_sec = 0.5
model_candidate_entry_sec = 0.1
model_confirm_sec = 0.2
cooldown_inherit_iou_threshold = 0.3
```

이 값은 Subject 1~6 Development에서 고정한 값이며, Subject 7~8 Validation 이후
변경하지 않았다. Development 성능은 목표를 만족했지만 Validation false alarm이
목표를 크게 넘었으므로, 현재 모델은 실시간 PoC의 선택적 기능이지 운영 환경에서
기본으로 켜는 기능은 아니다.

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
통합/PR4 범위로 남긴다.

같은 영상·720x480·MPS·FastAPI·Live Frame 조건에서 `--fall-detection-enabled`만
제외한 기본 경로(`yolo26n.pt` + ByteTracker)도 한 번 실행했다. 워밍업 이후
progress 출력(frame 31/61/91/121)의 단순 평균은 기본 경로 12.5 FPS, 낙상 opt-in
경로(`yolo26n-pose.pt` + PoseTracker + 보조 detector) 7.9 FPS로 기록됐다.
짧은 파일의 4개 표본 기준 약 4.6 FPS(36.9%) 차이이며, 모델·tracker가 함께
바뀌는 실제 opt-in 기능 전체의 비교다. 이 값은 장시간 성능 벤치마크나 IP 카메라
성능을 대표하지 않으며, 장시간/IP 카메라 FPS·latency 평가는 후속 통합에서 측정한다.

## 9. PR3: `FALL_SUSPECT.cause` 외부 접촉 원인 후보 추정

### 9.1 설계 요지

`src/safety/fall_cause_attributor.py`(`FallCauseAttributor`)가
`FALL_CONFIRMED` 순간에만 호출된다. 매 프레임 별도 추론이나 모델 호출을
하지 않으며, `FallDetector`가 낙상 판정에 쓰는 `MultiTrackHistory`와는
완전히 독립된 자체 이력(Track별 foot_point·bbox 높이·시각)을 갖는다 —
attribution에 필요한 lookback을 위해 낙상 판정용 이력 window를 늘리면
PR2에서 이미 튜닝·동결한 속도/변화율 계산과 Development/Validation 수치가
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

PR3 구현 자체에는 외부 데이터셋이 필요 없었다 — 정식 자동 테스트는
`tests/test_fall_cause_attributor.py`(후보 탐색·점수 계산·tie-break·
독립 이력 유지 범위를 합성 시나리오로 검증)와 `tests/test_fall_detector.py`
·`tests/test_fall_pipeline_module.py`(candidate 진입 시각 캡처, 실제 낙상
confirm 시 cause 연결까지 mock 없이 end-to-end로 검증)로 커버했다.

CAUCAFall은 주로 단일 인원 낙상 데이터라 원인 후보 정확도를 증명하는
데이터가 아니다. 로컬 `data/datasets/mpfdd`(공개 샘플 28개 영상, 전체
MPFDD 220개 중 일부)도 여러 사람이 같은 장면에 있는 낙상 영상은 있지만
접촉으로 낙상했다는 원인 라벨은 제공하지 않는다 — 그래서 PR3에서는
`cause` 양성 정확도를 이 데이터로 주장하지 않는다. PR3에서 실제로 한 것은
28개 공개 샘플의 파일명·설명을 검토해 hard-negative(원인 없는 다인 근접)
후보 데이터로 쓸 수 있다는 것만 확인한 수준이다 — `false_cause_rate` 측정
등 실제 hard-negative 실행은 아직 하지 않았다. 실제 접촉 원인 후보
정확도(precision/recall, false attribution) 평가와 hard-negative 실행은
Phase 4에서 접촉 유발 영상 또는 권한·라벨이 명확한 외부 데이터로 진행한다.

### 9.4 알려진 한계

- 2D 화면상 근접은 실제 접촉을 보장하지 않는다 — `cause`는 "외부 접촉
  의심 후보"이지 충돌·인과관계를 확정하는 기능이 아니다.
- ReID가 없어 Track ID가 낙상 직전 바뀌면(재획득) 후보 연속성이 끊길 수
  있다 — 그 Track의 이력 시작 시각이 `fall_start_sec` 이후라면 §9.1의
  "낙상 시작 뒤에 처음 등장한 Track 제외" 규칙에 걸려 후보에서 빠진다.
- 다중 인원이 근접한 상황에서 false cause(원인이 없는데 후보가 잡히는
  경우) 가능성이 있다 — 정량 평가는 Phase 4로 남겨뒀다.
- `distance_threshold`·`closing_speed_threshold`·`score_threshold` 등은
  튜닝된 값이 아니라 초기 PoC 기본값이다.
