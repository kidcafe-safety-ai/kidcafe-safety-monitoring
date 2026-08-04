# 데이터 소스 기록

Phase 3 낙상 감지 PoC와 Phase 4 외부·촬영 데이터 검증에 사용하는 데이터셋을
기록한다.

> 원본 데이터 파일은 Git에 업로드하지 않는다.
> URL·라이선스·체크섬은 이 문서에 기록하고, 실제 파일은 로컬 또는 팀 공유 스토리지에 보관한다.

## 저장 위치

`data/datasets/` 아래에 데이터셋별로 보관한다. 이 디렉터리는 `.gitignore`에서
제외되며(`data/datasets/*`), `.gitkeep`만 git에 추적된다.

```text
data/datasets/
├─ caucafall/v5/
│  ├─ development/   # Subject 1-6
│  ├─ validation/    # Subject 7-8
│  └─ holdout/       # Subject 9-10 (최종 평가 전까지 미사용)
├─ gmdcsa24/v2.1/
├─ omnifall/                 # Phase 4 비상업적 진단·학습 후보
├─ up_fall/                  # Phase 4 후보, gate 통과 후 사용
├─ ur_fall/                  # 선택
├─ phase4_recordings/        # 2026-08-07 촬영 원본, Git 제외
└─ fall_cause_mini_set/
```

---

## CAUCAFall

| 항목 | 내용 |
|---|---|
| 데이터셋명 | CAUCAFall V5 |
| 공식 URL | https://data.mendeley.com/datasets/7w7fccy7ky/5 |
| DOI | 10.17632/7w7fccy7ky.5 |
| 발행일 | 2025-03-18 |
| 접근 방법 | Mendeley Data 직접 다운로드 |
| 라이선스 | CC BY 4.0 |
| 용도 | 낙상 감지 개발·튜닝·내부 평가 |
| 검토 상태 | 공식 메타데이터·라이선스·다운로드·압축 무결성·체크섬 확인 완료 |

### 데이터 구성

- Subject(참가자) 10명, 참가자당 폴더 10개(활동별)
- 폴더마다 영상(`.avi`), 프레임 이미지(`.png`), 프레임별 분할 라벨(`.txt`) 포함
- 해상도 720×480, 20fps (`ffprobe`로 Subject 1/3/6 샘플 영상 직접 확인, `docs/fall_evaluation.md`의 fine-tuning 기록 참고)
- 낙상 5종: 전방, 후방, 좌측, 우측, 앉은 상태에서의 낙상 → `fall` 라벨
- ADL 5종: 걷기, 뛰기(hopping), 물건 집기, 앉기, 무릎 꿇기 → `no-fall` 라벨

### Subject 분할

| 분할 | Subject |
|---|---|
| 개발·튜닝 | Subject 1-6 |
| 진단·튜닝 (`validation/` 디렉터리) | Subject 7-8 |
| 최종 내부 평가 (holdout) | Subject 9-10 |

Subject 7-8은 초기 Validation 이후 오류 분석과 규칙 검증에 사용되어 현재는
진단·튜닝 데이터로 취급한다. Subject 9-10(holdout)은 설정 동결 후 최종 평가
전까지 사용하지 않는다.

### 체크섬

```text
파일명: Dataset CAUCAFall.zip
버전: V5
파일 크기: 8,326,349,365 bytes
SHA-256: 44b67468167fad2565edd51056bb1a2b62110ea165221ffd3ea8dbe03a181ee0
다운로드 일자: 2026-07-14
보관 위치: data/datasets/caucafall/v5/
```

---

## GMDCSA-24

| 항목 | 내용 |
|---|---|
| 데이터셋명 | GMDCSA-24 V2.1 |
| 공식 URL | https://zenodo.org/records/13354453 |
| DOI | 10.5281/zenodo.13354453 |
| 접근 방법 | Zenodo 직접 다운로드 |
| 라이선스 | CC BY 4.0 |
| 용도 | 외부 오탐 평가 |
| 검토 상태 | 공식 메타데이터·라이선스 확인 완료, 실제 다운로드·체크섬 확인 예정 |

### 체크섬

다운로드 후 기록:

```text
SHA-256: (다운로드 후 기입)
다운로드 일자: (기입)
```

---

## Phase 4 E1 외부 데이터 후보

외부 데이터는 2026-07-31까지 다운로드 가능 여부, 원 출처, 라이선스,
checksum, CAUCAFall 중복 여부를 확인한 뒤 사용한다. 확인 전에는 학습용으로
취급하지 않는다.

| 데이터 | 우선 용도 | 현재 상태 |
|---|---|---|
| OmniFall OF-Synthetic | sit·kneel·squat·crawl·lie-down hard-negative | 다운로드·체크섬 완료, 비상업적 진단 cohort 사용 중 |
| UP-Fall | 실제 RGB fall·sit·pick·lay 다양성 | subject·camera 분할과 라이선스 확인 대기 |
| GMDCSA-24 | 다른 환경의 고신뢰 false Event 선별 | 메타데이터 확인, 다운로드·checksum 대기 |

- gate를 통과한 데이터만 E1에 사용한다.
- 접근 또는 라이선스가 불명확하면 `not_available`로 기록한다.
- CAUCAFall 파생·중복 영상은 제외한다.
- 외부 데이터 미확보로 8월 7일 촬영이나 E0 기준선 평가를 지연하지 않는다.
- E1 미실행도 사유와 함께 정식 결과로 기록한다.

### OmniFall OF-Synthetic 사용 기록

| 항목 | 내용 |
|---|---|
| 공식 저장소 | https://huggingface.co/datasets/simplexsigil2/omnifall |
| 사용 범위 | OF-Synthetic random Train split의 hard-negative 후보 |
| 원본 archive | `data_files/omnifall-synthetic_av1.tar` (12,000개 AV1 영상) |
| 다운로드 상태 | 2026-08-04 완료, revision·SHA-256은 팀 스토리지의 source manifest에 기록 |
| Git 저장 | 원본·H.264 변환본·Signal Cache·검수 clip 모두 제외 |
| 중복 방지 | positive temporal label과 `fall`·`fallen` 대표 category 영상 제외 |
| 현재 용도 | E0 외부 challenge 진단과 검수된 hard-negative 후보 선별 |

Hugging Face metadata에는 `CC BY-NC 4.0`이 표시되지만 dataset card 본문은
annotation과 split을 `CC BY-NC-SA 4.0`으로 설명하고 영상 권리는 원 권리자에게
있다고 명시한다. 따라서 Phase 4에서는 비상업적 연구·진단 목적으로만 사용하고,
원본·변환 영상은 재배포하지 않는다. 외부 공개나 상업적 사용 전에는
OF-Synthetic 영상 archive에 적용되는 정확한 라이선스 범위를 원 배포자에게
추가 확인한다.

---

## UR Fall Detection Dataset

| 항목 | 내용 |
|---|---|
| 데이터셋명 | UR Fall Detection Dataset |
| 공식 URL | https://fenix.ur.edu.pl/%7Emkepski/ds/uf.html |
| 접근 방법 | 공식 사이트 직접 다운로드 |
| 라이선스 | CC BY-NC-SA 4.0 |
| 용도 | 선택적 시점 검증 |
| 검토 상태 | 공식 메타데이터·라이선스 확인 완료, 사용 여부·다운로드·체크섬 확인 예정 |

---

## 검토 후 미채택: MPFDD

Phase 3 원인 후보 구현 당시 공개 샘플 28개의 파일명과 설명을 검토했다.
다인 근접 장면의 hard-negative 후보 가능성은 확인했지만, 접촉 원인 Track
정답 라벨이 없고 저장소 라이선스도 명확하지 않아 학습·평가에는 사용하지
않았다. `false_cause_rate`를 포함한 정량 실행도 수행하지 않았으며,
7/22-7/28 통합 및 현재 후속 데이터 계획에서 제외한다.

| 항목 | 내용 |
|---|---|
| 공식 저장소 | https://github.com/Hnnuliulei123456/MPFDD |
| 확인 범위 | 공개 샘플 28개 파일명·설명 |
| 실제 사용 | 없음(학습·평가·임계값 선택 미사용) |
| 미채택 사유 | 접촉 원인 라벨 부재, 라이선스 불명확 |

---

## Phase 4 직접 촬영 데이터

2026-08-07에 성인 참여자·안전 매트·고정 카메라로 통제된 안전 시나리오를
촬영한다. 낙상, hard-negative, cause, Zone, Homography holdout을 같은
manifest와 review 정책으로 관리한다. 현재 구현은 합성 multi-track 테스트로
계약만 검증했으며 실제 촬영 데이터는 아직 없다.

| 시나리오 | 최소 샘플 수 |
|---|---|
| 혼자 낙상 | 5개 이상 |
| 다른 사람이 접근 후 낙상 | 5개 이상 |
| 다른 사람이 옆을 지나감 | 5개 이상 |
| 여러 사람이 근처에 있음 | 5개 이상 |

### 촬영 원칙

- 실제 충돌 강제 연출 금지
- 성인 참여자와 매트를 사용한 통제된 하강만 허용
- 합성 Track sequence 병행 가능
- 촬영 동의와 안전 담당자 확인 필수
- 아동 낙상 연출 금지
- 성인 데이터 성능을 아동 환경 성능으로 일반화하지 않음

### 계약

- 파일명·manifest·annotation: 이 문서의 Phase 4 촬영 데이터 계약
- actor 또는 session 단위 split
- 같은 take의 다중 camera 영상은 같은 split
- 동의 확인 원본은 비공개 저장소에서 별도 관리
- `consent_status=excluded` 데이터는 학습·평가·시연 금지
- 원본 영상·Signal Cache·모델은 Git 업로드 금지

### Schema version

공식 평가 산출물에는 입력 annotation에 맞는 다음 고정값을 기록한다.

| 데이터 | Schema version |
|---|---|
| CAUCAFall Annotation V2 | `caucafall_annotation_v2` |
| Phase 4 촬영 manifest | `phase4_recordings_manifest_v1` |
| Phase 4 낙상·Cause annotation | `phase4_fall_cause_v1` |
| Phase 4 Zone interval | `phase4_zone_intervals_v1` |
| Phase 4 calibration point | `phase4_calibration_points_v1` |
| Phase 4 Track·Actor review | `phase4_track_actor_review_v1` |

낙상 평가 결과의 `annotation_schema_version`은 CAUCAFall 평가에서는
`caucafall_annotation_v2`, 직접 촬영 평가에서는 `phase4_fall_cause_v1`이다.

### 파일명

```text
P4_S<2자리 숫자>_A<2자리 숫자>_<소문자 scenario>_<2자리 take>_cam<2자리 숫자>.mp4
```

예시: `P4_S01_A01_fall_backward_01_cam01.mp4`

- 실제 이름·학번·연락처를 사용하지 않는다.
- 하나의 clip에는 하나의 주 시나리오만 둔다.
- 다중 camera take는 camera ID만 다르게 하고 나머지 식별자는 유지한다.
- `scenario`는 lowercase snake_case를 사용한다.

권장 `scenario`:

```text
fall_backward
fall_side
sit_down
kneel
pick_up
lie_down
crawl
near_pass
contact_fall
zone_enter
zone_exit
zone_dwell
```

목록 밖 시나리오가 필요하면 같은 명칭을 파일명과 manifest에 사용하고 촬영
전에 팀에 공유한다.

### Manifest

파일: `data/annotations/phase4/recordings_manifest.csv`

```text
video_id,session_id,actor_ids,primary_actor_id,camera_id,scenario_type,label,
video_path,fps,frame_count,width,height,lighting,split_role,review_status,
consent_status,checksum_sha256
```

- `actor_ids`는 `A01|A02` 형식이다.
- `label`: `fall | no_fall`
- `split_role`: `train | internal_validation | diagnostic | test |
  external_evaluation`
- `review_status`: `pending | needs_review | reviewed`
- `consent_status`: `confirmed | excluded`
- `video_id`, `session_id`, actor ID, `camera_id`는 파일명 계약 형식을 따른다.
- `video_id`는 manifest 안에서 고유해야 한다.
- `scenario_type`은 lowercase snake_case다.
- `fps`, `frame_count`, `width`, `height`는 0보다 커야 한다.
- `primary_actor_id`는 `actor_ids`에 포함돼야 한다.
- `video_path`는 프로젝트 기준 상대 POSIX 경로이며 파일명은
  `<video_id>.mp4`와 일치해야 한다.
- `checksum_sha256`은 원본 파일의 64자리 lowercase SHA-256이다.
- `consent_status=excluded` 영상은 학습·평가·시연에서 제외한다.

### 낙상·Cause annotation

파일: `data/annotations/phase4/fall_cause_annotations.csv`

```text
video_id,label,fall_start_frame,impact_frame,lying_start_frame,recovery_frame,
victim_actor_id,contact_occurred,cause_candidate_exists,cause_actor_id,
contact_frame,review_status,reviewer_id,second_reviewer_id,notes
```

- frame 번호는 0부터 시작하고 첫 decoded frame이 frame 0이다.
- `video_id`는 파일 안에서 고유하며 manifest의 행과 일치해야 한다.
- annotation `label`은 같은 영상의 manifest `label`과 일치해야 한다.
- 입력한 모든 frame은 0 이상이고 manifest `frame_count`보다 작아야 한다.
- `fall_start_frame <= impact_frame <= lying_start_frame <= recovery_frame`
  순서를 사용하며 영상 밖 recovery는 비울 수 있다.
- `victim_actor_id`를 입력하면 manifest의 `actor_ids`에 포함돼야 한다.
- 단독 낙상·near-pass·무관한 주변 인원은 cause candidate 없음이 원칙이다.
- `contact_occurred=true`이면 `contact_frame`이 필요하고, `false`이면
  비워둔다.
- `cause_candidate_exists=true`이면 `cause_actor_id`가 필요하고, `false`이면
  비워둔다.
- `cause_actor_id`는 victim과 달라야 하며 manifest의 `actor_ids`에 포함돼야
  한다.
- Cause 정답은 A와 다른 팀원 1명의 검수를 모두 통과해야 `reviewed`다.
- `reviewer_id`와 `second_reviewer_id`는 서로 다른 reviewer여야 한다.
- 검수 불일치는 `needs_review`로 유지하고 공식 Cause 지표에서 제외한다.

### Zone·calibration annotation

파일:

```text
data/annotations/phase4/zone_intervals.csv
data/annotations/phase4/calibration_points.csv
```

필드:

```text
video_id,zone_id,interval_index,enter_frame,exit_frame,dwell_start_frame,
review_status,notes

camera_id,calibration_version,point_id,point_role,observation_index,
image_x_px,image_y_px,floor_x_m,floor_y_m,review_status,notes
```

- Zone interval의 `video_id`는 manifest와 일치해야 한다.
- `interval_index`는 같은 영상·Zone에서 1부터 시작하며 중복하지 않는다.
- `enter_frame`은 foot point가 Zone 내부로 들어온 첫 frame이다.
- `exit_frame`은 foot point가 Zone 외부로 나온 첫 frame이다.
- `enter_frame < exit_frame`이고 두 값은 영상 frame 범위 안에 있어야 한다.
- dwell 기준을 충족하지 않으면 `dwell_start_frame`은 비워둔다. 값이 있으면
  `enter_frame <= dwell_start_frame < exit_frame`이어야 한다.
- 가림 등으로 경계 frame이 불명확하면 `needs_review`로 둔다.
- `point_role`은 `fit | holdout`이다.
- `observation_index`는 같은 point에서 1부터 시작하며 중복하지 않는다.
- fit과 holdout에 같은 실제 위치를 중복 사용하지 않는다.
- holdout은 서로 다른 위치 최소 10개, 총 20회 이상 관측한다.
- 카메라가 움직이면 기존 calibration을 무효화하고 version을 변경한다.
- 공식 Homography 계산에는 `reviewed` 행만 사용한다.

### 결과 기록 형식

```text
시나리오: 혼자 낙상
샘플 수: 5
원인 후보 정확: 4
원인 후보 오류: 1
결과: 4/5 (80%)
```

---

## 사용 기준

- Subject 단위로 개발·검증·평가 분리
- 평가 데이터(holdout)는 튜닝 완료 후 한 번만 사용
- 원본 데이터 Git 업로드 금지
- 라이선스 미확인 데이터는 접근 전 확인

---

## Phase 3 평가 기준과 확인 상태

```text
Subject 7-8 timely Recall ≥ 75%
False alarm ≤ 0.2회/분
평균 감지 지연 ≤ 2초
낙상 1회당 이벤트 1회

기능 적용 후 FPS 저하 ≤ 20%
API 장애 중 파이프라인 비정상 종료 없음
```

Annotation V2와 Track handoff 안정화 이후 Development 결과는 Recall 83.3%,
timely Recall 66.7%, false alarm 0회/분, 중복 Event 0건이다. Subject 7-8
진단 결과는 Recall 100%, timely Recall 90%, false alarm 1.75회/분, 중복 Event
0건이다. 오탐 목표를 충족하지 못했고 Subject 7-8을 오류 분석에 사용했으므로,
기능은 기본 비활성 opt-in PoC로 유지하며 이 수치를 최종 성능으로 보고하지 않는다.
자세한 이력은 `docs/fall_evaluation.md`에 기록한다.

2026-07-22에 동일 능동 인원 영상과 하드웨어에서 각 조건을 warm-up 후 3회
측정했다. 최초 30프레임을 제외한 steady-state 중앙값은 낙상 OFF 9.461 FPS,
낙상 ON 5.098 FPS로 46.1% 감소해 목표(20% 이내)를 충족하지 못했다. API 장애의
추가 감소는 3.5%였고 모든 실행이 끝까지 완료됐다. 자세한 조건은
`docs/realtime_test.md`와 `docs/fall_evaluation.md`의 2026-07-22 통합 기록에
남긴다.

같은 날 후속 opt-in 최적화에서 M1/MPS 파일 경로에 Pose NORMAL gate와 보조
모델 interval `3`을 적용했다. 동일 파일 OFF/ON 각 3회 steady-state 중앙값은
최적화 ON 13.511 FPS, 낙상 OFF 14.5712 FPS로 하락률 7.3%를 기록해 로컬 경로
목표를 통과했다. Development 지표는 유지됐고 S7-8 진단 FAR는
2.34→1.75/min으로 감소했다. 이 값은 API·Live Frame을 제외한 단일 파일
측정이며 S7-8도 tuning 데이터이므로 최종 성능으로 해석하지 않는다.

Subject 9-10 Holdout은 설정 동결 후에도 이번 통합 범위에서는 실행하지 않았다.
Phase 4 최종 평가에서 한 번만 사용한다. `FALL_SUSPECT.cause`의 원인 후보 Track
정확도·false attribution도 아직 정량 검증하지 않았으며, Phase 4에서 위 Mini
Set 또는 원인 라벨이 명확한 외부 데이터로 평가한다.
