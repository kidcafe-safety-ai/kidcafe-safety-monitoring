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
- 검수 완료 상태: Development 60/60, Validation 20/20 (`review_status=reviewed`).

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
| Tune 1 | 시간차 근거 분리 (§3) | 16.7% (5/30) | 0.0 | 1.92 | 0 | `outputs/fall_eval/development_tune_01_temporal_evidence.json` |
| Tune 2 | + Pose torso_angle (§5.3, 폐기) | 20.0% (6/30) | 0.0 | 0.88 | 0 | `outputs/fall_eval/development_tune_02_pose_confirmation.json` |
| Tune 2b | + Pose head_hip_diff_norm (§5.3) | 30.0% (9/30) | 0.0 | 1.14 | 1 (`S4_fall_forward`) | `outputs/fall_eval/development_tune_02b_pose_head_hip.json` |
| **Tune 3 (최종, PR2 기준선)** | + cooldown pose 반영 + early tolerance 0.2s + `S6_fall_backwards` 제외 | **34.5% (10/29)** | 0.0 | 1.02 | 1 (`S4_fall_forward`, 원인 §5.6) | `outputs/fall_eval/development_tune_04_final.json` |

Tune 3부터는 `S6_fall_backwards`가 `needs_review`로 제외돼 fall 모수가 29개다
(§5.5). 모든 실행에서 `evaluation_valid=true`(오류 영상 0개), Tune 3의
`early_false_alarms=0`(early tolerance 0.2s 적용 후).

**PR2 결론**: False alarm(0.0/min ≤ 0.2)·평균 지연(1.02s ≤ 2.0s)은 목표를
만족하지만, **Recall 34.5%는 목표(≥75%)에 크게 못 미친다**. §5.1·§5.3에서
확인한 카메라 깊이 방향 낙상의 구조적 한계 때문에 규칙 기반 bbox+pose
방식만으로는 목표 달성이 어렵다고 판단해, Recall 목표 달성은 후속 PR(PR2.5,
§8)의 YOLO fine-tuning으로 넘긴다. PR2는 **규칙 기반 PoC 기준선**으로
머지한다.

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
aspect_ratio(§5.1)와 동일한 카메라 각도 문제가 골격 각도에도 그대로
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
  aspect_ratio가 낮게 유지되는 낙상(§5.1)에서 회복 조건이 자주 만족돼
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
  깊이 방향 낙상(§5.1)에서 pose는 여전히 쓰러진 자세로 보는 동안 bbox가
  한 번도 수평으로 판정되지 않아 cooldown이 조기 만료되고, 같은 낙상이
  다시 candidate로 잡혀 중복 Event가 발생했다 (`S4_fall_forward`, frame
  41과 149 두 번 확정). recovery와 동일한 pose 우선 규칙을 적용해 고쳤다.

머리-엉덩이 신호 도입 후 Development Recall은 30%(9/30)까지 올랐으나
(`development_tune_02b_pose_head_hip.json`), 위 cooldown 버그로 인한 중복
확정 1건이 섞여 있었다. 최종 결과는 §5.5 참고.

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

### 5.6 알려진 한계: cooldown 중 track 소실 시 상태 초기화 (미해결)

`_advance_cooldown()`이 bbox뿐 아니라 pose `is_fallen_pose`도 확인하도록
고쳤음에도(§5.3 cooldown pose 반영) `S4_fall_forward`는 여전히 중복
Event(frame 41, 149)가 발생한다. track_id를 프레임 단위로 직접 추적한
결과, pose/bbox 판정 문제가 아니라 **frame 101~131(30프레임=1.5초) 동안
사람이 전혀 검출되지 않는 구간**이 원인이었다(누운 자세에서의 occlusion
추정). 이 공백이 `track_grace_sec`(0.5초)보다 훨씬 길어서
`_forget_lost_tracks()`가 이 track의 `_TrackState`(COOLDOWN 포함)를
완전히 삭제하고, frame 132에 같은 track_id로 재검출됐을 때
`_advance_state`가 `setdefault`로 상태를 NORMAL부터 새로 만들어 cooldown
기억이 사라진다. 즉 pose-blindness가 아니라 "cooldown 중 track이 grace
period 이상 소실되면 cooldown 자체가 리셋된다"는 별도 원인이다.

가능한 수정(`_forget_lost_tracks()`에서 `COOLDOWN` 상태 track은 삭제
예외 처리)을 확인했으나, Pose 경로는 PR2.5(§8) fine-tuning 확정 전까지의
비교 기준·fallback 역할로 한정하기로 해 이번 PR2에서는 추가로 수정하지
않고 **알려진 한계로 남긴다**. `falls_with_multiple_events=1`(Tune 3, §4)이
이 사례다.

## 6. Validation (Subject 7~8)

annotation은 검수 완료(20/20)됐으나, 평가는 **아직 실행하지 않았다** — 설정을
최종 동결(pose 보완 포함)한 뒤 한 번만 실행하고, 그 결과를 보고 임계값을 다시
조정하지 않는다 (개발/검증 분리 원칙).

## 7. Subject 9~10 사용 확인

이번 PR2 전 과정(생성·검수·평가)에서 Subject 9~10(holdout)에는 접근하지
않았다 — `generate_caucafall_annotations.py`/`evaluate_fall.py` 모두 holdout
경로를 코드 수준에서 차단한다 (`guard_holdout`/`_contains_holdout_segment`).

## 8. PR2 범위 확정과 후속 로드맵

PR2(규칙 기반 bbox+pose)만으로는 Recall 목표(≥75%)를 달성하지 못했다.
§5.1·§5.3에서 확인했듯 카메라를 향해/멀어지는 방향(깊이 방향) 낙상은
aspect_ratio·skeleton 각도 등 어떤 단순 2D 투영 신호로도 구조적으로 분리가
어렵다 — CAUCAFall 공식 문서(Figure8, 271.4°)로도 교차 확인된 한계다.
반면 CAUCAFall은 프레임 단위 fall/nofall 라벨을 자체 제공하도록 설계되어
있어(공식 참고 구현도 전신 keypoint 기반), YOLO 분류기를 직접 fine-tuning해
confirm 신호로 쓰는 방식이 데이터셋 의도에 더 가깝다.

이에 따라 작업을 다음과 같이 분리한다:

- **PR2 (본 PR, `feature/fall-detector`)**: bbox+pose 규칙 기반
  FALL_SUSPECT 코어. **Recall 목표 달성본이 아니라 규칙 기반 PoC
  기준선**으로 머지한다 — 위 구조적 한계와 미달 수치를 PR 본문에 명시한다.
- **PR2.5 (`feature/fall-classifier`, 별도 PR)**: CAUCAFall 프레임 라벨로
  YOLO26n fall/nofall을 fine-tuning하고, candidate 진입(동적 근거)은 현재
  규칙을 그대로 두되 confirm을 fine-tuned 모델의 fall score로 대체한다.
  bbox/pose 규칙은 보조 신호로 남긴다. 학습 데이터 분할은 기존 Subject
  기준 정책을 그대로 따른다 (Development로 학습/내부 검증, Validation은
  최종 평가 전 미접근, Holdout은 PR4까지 미접근).
- **PR3**: `FALL_SUSPECT.cause` 외부 접촉 후보 추정 (ADR-016).

Validation(Subject 7~8) 평가는 PR2.5까지 포함한 최종 구조가 동결된 뒤
한 번만 실행한다 — PR2 단계에서는 실행하지 않는다.
