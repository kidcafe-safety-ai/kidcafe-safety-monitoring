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

두 결과 모두 `evaluation_valid=true`(오류 영상 0개), `early_false_alarms=0`.

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

### 5.3 Pose 기반 보완 (다음 단계)

`yolo26n-pose.pt`(COCO 17 keypoint)로 `Subject 1 Fall forward`를 재확인한
결과, `nose_y - hip_y`가 서 있을 때는 음수(-52~-67)였다가 쓰러진 뒤에는
양수(+57)로 부호가 뒤집힌다 — bbox aspect_ratio로는 잡지 못한 자세 변화를
keypoint 관계로는 명확하게 포착한다. 같은 `feature/fall-detector` 브랜치에서
pose 기반 confirm 경로를 이어서 구현한다 (커밋 분리: bbox 코어 → pose 보완).

## 6. Validation (Subject 7~8)

annotation은 검수 완료(20/20)됐으나, 평가는 **아직 실행하지 않았다** — 설정을
최종 동결(pose 보완 포함)한 뒤 한 번만 실행하고, 그 결과를 보고 임계값을 다시
조정하지 않는다 (개발/검증 분리 원칙).

## 7. Subject 9~10 사용 확인

이번 PR2 전 과정(생성·검수·평가)에서 Subject 9~10(holdout)에는 접근하지
않았다 — `generate_caucafall_annotations.py`/`evaluate_fall.py` 모두 holdout
경로를 코드 수준에서 차단한다 (`guard_holdout`/`_contains_holdout_segment`).
