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
│  └─ holdout/       # Subject 9-10 (필요 시 참고 회귀에만 사용)
├─ gmdcsa24/                 # v2.1 공식 archive, 실제 RGB
├─ omnifall/                 # OF-Synthetic 진단 기록 전용
├─ up_fall/                  # 실제 RGB 선별 pilot archive
├─ ur_fall/                  # 검토 후 미사용
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
| 용도 | 낙상 감지 초기 구현·학습·참고 회귀 |
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
| CAUCAFall 내부 참고 holdout | Subject 9-10 |

Subject 7-8은 초기 Validation 이후 오류 분석과 규칙 검증에 사용되어 현재는
진단·튜닝 데이터로 취급한다. Subject 9-10(holdout)은 필요 시 설정 동결 후
참고 회귀에만 사용한다. 이 분할은 CAUCAFall 내부 회귀 확인용이며 실제
키즈카페 목표 환경의 성능이나 모델 채택을 결정하지 않는다.

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
| 용도 | 실제 RGB 외부 Recall·FAR 평가, train-candidate 오탐 mining |
| 검토 상태 | 공식 v2.1 다운로드·archive 무결성·체크섬 확인 완료, metadata 불일치는 cohort manifest에 보존 |

### 체크섬

```text
파일명: GMDCSA24-v2.1.zip
파일 크기: 1,107,545,615 bytes
MD5: 3d36f2c5c1a666b99639e4e9fd843efb
SHA-256: d455f90f67060b9c8032701d0a91ff38536eaa5ec85582a7a12e68351af591d7
다운로드 일자: 2026-08-04
```

### 구성·분할

- 실제 RGB H.264 MP4 160개: ADL 81개, Fall 79개
- Subject 1-3: `train_candidate` 123개
- Subject 4: 독립 `validation` 37개
- official CSV의 명시적 `Falling (...) [start to end]` 시작 시각만 onset으로
  사용한다.
- Fall 5개는 원본 구간 문자열이 깨져 있어 자동 보정하지 않고
  `needs_review`로 제외한다. 이 중 Subject 4 validation은 2개다.
- ADL의 세부 temporal class 문자열과 `Length (seconds)`에 원본 오타가 있다.
  materializer는 원문을 고치지 않고 실제 probe duration과의 차이를
  `metadata_issues`로 기록한다. 전체 ADL의 `no_fall` 라벨은 유지하되, fall
  onset이 duration 불일치의 영향을 받으면 `needs_review`로 평가에서 제외한다.

### GMDCSA24 진단 종료 판정

`docs/fall_evaluation.md` §14.6의 E0·motion gate 실험에서 GMDCSA24는
train-candidate FAR 0.9809/min, validation FAR 1.5507/min, fall Recall
train 56.9%·validation 73.3%로 §14.4의 실제 RGB validation 채택 기준에
미달했다.

원인 진단을 위해 원본 프레임을 직접 확인한 결과, GMDCSA24는 근접 정면
(눈높이) 구도로 촬영됐다. 실 배포 예정 카메라와 같은 구도로 확인된
CAUCAFall(천장 구석·하향각·광각 CCTV)과 비교하면 구도 차이가 가장 크고,
낙상 규칙·보조 모델 임계값은 모두 CAUCAFall 기반으로 튜닝돼 있어 이
구도 차이가 GMDCSA24에서 유독 낮은 Recall과 rule-path 의존(§14.6)의
원인일 가능성이 크다.

따라서 GMDCSA24는 production 판단 데이터로 채택하지 않는다. §14.4의
실제 RGB validation 채택 기준은 8월 7일 직접 촬영 데이터로 대체한다.
원본은 체크섬을 기록해 재다운로드
가능하고 가공물은 스크립트로 재생성 가능하므로, 로컬 원본·가공 영상·
Signal Cache·검수 결과는 삭제하고 이 진단 결과만 이력으로 보존한다.

---

## UP-Fall

| 항목 | 내용 |
|---|---|
| 데이터셋명 | UP-Fall Detection Dataset |
| 공식 URL | https://sites.google.com/up.edu.mx/har-up/ |
| 용도 | 실제 RGB 낙상 Recall과 sitting·picking-up·laying FAR 외부 진단 |
| 선택 범위 | Subject 1-10, Activity 1-5·8·9·11, Trial 1, Camera 1 |
| 원본 형식 | timestamp PNG ZIP 79개, 640×480, 공식 nominal 18 FPS |
| 다운로드 크기 | 16,487,618,041 bytes |
| 다운로드 일자 | 2026-08-04 |
| 검토 상태 | 공식 링크·파일 크기·ZIP CRC·개별 SHA-256 확인 완료 |

### 분할·가공

- Subject 1-8: `train_candidate` 63개(fall 39, no-fall 24)
- Subject 9-10: 독립 `validation` 16개(fall 10, no-fall 6)
- Camera 2는 시점 비교용 1개만 별도 확인했으며 cohort에는 넣지 않는다.
- PNG ZIP은 전체 압축 해제하지 않고 timestamp 순서로 읽어 nominal 18 FPS
  H.264/yuv420p MP4로 변환한다.
- selection manifest SHA-256:
  `2b18cc492c26769700478e0715ffa97bfcba5a49d1a5d9cbb869745227f66c9e`
- 개별 archive checksum 목록 SHA-256:
  `4a1daf3bee1e41753df87fa550f12bca55819a8e2c74216a7e6b095097ca514c`

### E0 외부 진단 결과

| 분할 | Recall | timely Recall | FAR | 중복 Event |
|---|---:|---:|---:|---:|
| Subject 1-8 train-candidate | 23.1% | 7.7% | 0.1191/min | 0 |
| Subject 9-10 validation | 40.0% | 30.0% | 0.0/min | 0 |

no-fall FAR는 낮았지만 낙상 Recall이 크게 하락했다. 이는 CAUCAFall 기반 E0가
UP-Fall의 카메라 시점과 낙상 표현에 일반화되지 않았음을 보여주는 외부 진단
결과이며, 성능 개선이나 새 모델 채택 결과가 아니다. UP-Fall validation은 학습에
사용하지 않고, train-candidate의 hard-negative도 사람이 검수한 뒤 보조 모델이
관여한 구간만 E1 후보로 사용할 수 있다.

공식 페이지에서 공개 다운로드는 확인했지만 명시적인 재배포 라이선스 문구는
확인하지 못했다. 따라서 프로젝트의 비상업적 로컬 연구·평가에만 사용하고 원본,
변환본, frame supplement를 Git이나 외부 저장소에 재배포하지 않는다. 라이선스가
명확해지기 전에는 모델 공개 시 해당 데이터 포함 여부도 별도로 검토한다.

---

## Phase 4 외부 데이터 결정

외부 데이터는 다운로드 가능 여부, 원 출처, 라이선스, checksum, CAUCAFall
중복 여부를 확인한 뒤 사용한다. UP-Fall·GMDCSA24 검증은 2026-08-04에
완료했으며, 확인 전 데이터는 학습용으로 취급하지 않는다.

| 데이터 | 우선 용도 | 현재 상태 |
|---|---|---|
| OmniFall OF-Synthetic | 합성 도메인 stress test | 진단 종료, 학습 미채택 |
| UP-Fall | 실제 RGB 낙상·ADL 외부 진단 | 79개 평가 완료, 모델·설정 미채택 |
| GMDCSA-24 | 실제 RGB ADL·Fall 외부 진단 | 진단 종료, 카메라 구도 불일치로 미채택 |

- gate를 통과한 데이터만 E1에 사용한다.
- 접근 또는 라이선스가 불명확하면 `not_available`로 기록한다.
- CAUCAFall 파생·중복 영상은 제외한다.
- 외부 데이터 미확보로 8월 7일 촬영이나 E0 기준선 평가를 지연하지 않는다.
- E1 미실행도 사유와 함께 정식 결과로 기록한다.

### OmniFall OF-Synthetic 사용 기록

| 항목 | 내용 |
|---|---|
| 공식 저장소 | https://huggingface.co/datasets/simplexsigil2/omnifall |
| 진단 범위 | OF-Synthetic random Train split의 E0 mining cohort 569개와 독립 validation 187개 |
| 원본 archive | `data_files/omnifall-synthetic_av1.tar` (12,000개 AV1 영상) |
| 다운로드 상태 | 2026-08-04 완료, revision·SHA-256은 팀 스토리지의 source manifest에 기록 |
| Git 저장 | 원본·H.264 변환본·Signal Cache·검수 clip 모두 제외 |
| 중복 방지 | positive temporal label과 `fall`·`fallen` 대표 category 영상 제외 |
| 현재 용도 | E0 합성 도메인 stress test 기록 보존, 학습에는 미사용 |

Hugging Face metadata에는 `CC BY-NC 4.0`이 표시되지만 dataset card 본문은
annotation과 split을 `CC BY-NC-SA 4.0`으로 설명하고 영상 권리는 원 권리자에게
있다고 명시한다. 따라서 Phase 4에서는 비상업적 연구·진단 목적으로만 사용하고,
원본·변환 영상은 재배포하지 않는다. 외부 공개나 상업적 사용 전에는
OF-Synthetic 영상 archive에 적용되는 정확한 라이선스 범위를 원 배포자에게
추가 확인한다.

### OF-Synthetic 진단 종료 판정

Train mining cohort 569개에서 E0 false Event 125건(2.6037/min)이 발생했다.
수동 검수 결과 111건은 합성 영상 안에서는 일관된 hard-negative였고, 13건은
시각적 합성 artifact, 1건은 판단 보류였다. 별도 synthetic validation 187개에서도
41건(2.5985/min)이 재현됐으며 confirm 경로는 model 15건, bbox 26건이었다.

이는 눕기 중심의 취약점과 보조 모델만 고쳐서는 FAR 목표에 도달할 수 없다는
stress-test 근거로는 유효하다. 하지만 모든 영상이 생성형 합성 데이터이고 실제
카메라의 사람·조명·가림·배경 분포를 대표하지 않으므로 E1 학습 데이터로는
채택하지 않는다. 카메라 구도도 근접 정면 위주로 확인되어, 실 배포 예정인
천장 구석·하향각 CCTV 구도와 다르다. 생성한 archive, H.264 cohort, Signal
Cache와 검수 결과는 감사 가능한 진단 기록으로만 보존하고, 개선 실험은
UP-Fall과 8월 7일 직접 촬영 실제 RGB로 전환한다.

---

## UR Fall Detection Dataset

| 항목 | 내용 |
|---|---|
| 데이터셋명 | UR Fall Detection Dataset |
| 공식 URL | https://fenix.ur.edu.pl/%7Emkepski/ds/uf.html |
| 접근 방법 | 공식 사이트 직접 다운로드 |
| 라이선스 | CC BY-NC-SA 4.0 |
| 용도 | 선택적 시점 검증 |
| 검토 상태 | 공식 메타데이터·라이선스 확인 후 Phase 4 미사용으로 검토 종료 |

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

2026-08-07에 성인 참여자·안전 매트·고정 IP 카메라로 통제된 안전 시나리오
촬영을 완료했다. 낙상, hard-negative, cause, Zone, Homography holdout을 같은
manifest와 review 정책으로 관리한다. 원본 파일 무결성 확인, manifest 작성,
frame annotation과 actor 또는 session 단위 분할은 촬영 후 평가 브랜치에서
진행하며, 완료 전에는 성능 개선 결과로 해석하지 않는다.

| 시나리오 | 최소 샘플 수 |
|---|---|
| 혼자 낙상 | 5개 이상 |
| 다른 사람이 접근 후 낙상 | 5개 이상 |
| 다른 사람이 옆을 지나감 | 5개 이상 |
| 여러 사람이 근처에 있음 | 5개 이상 |

A 역할 낙상·Cause 평가 subset의 실제 확보 수는 `contact_fall` 8개,
`near_pass` 3개, `occluded_cross` 1개다. 접촉 후 낙상 외 다중 인원 시나리오는
위 최소 수에 미달하므로 Cause·ID switch 결과를 일반 성능으로 해석하지 않고
사례 진단으로만 사용한다.

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

Subject 9-10 Holdout은 Phase 4에서도 실행하지 않았다. CAUCAFall은 초기 구현용
공개 데이터와 참고 회귀로만 보존하며 목표 환경 최종 성능 근거로 사용하지 않는다.
Phase 4 최종 평가는 실제 키즈카페 목표 카메라의 actor-disjoint A03을 사용했다.

`FALL_SUSPECT.cause`는 실제 촬영 데이터로 정량 검증했다. Cause 후보 8편의
top-1은 3/8(37.5%)로 목표에 미달했고, 단독 낙상 24편의 `cause=null`
specificity는 24/24(100.0%)였다. Tracker 3-way 비교 후에도 채택 기준을 충족한
후보가 없어 Production ByteTrack을 유지했다. 상세 결과는
`docs/phase4_cause_tracking/`과 `docs/phase4_tracker_comparison/`에 기록한다.
