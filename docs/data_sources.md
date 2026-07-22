# 데이터 소스 기록

Phase 3 낙상 감지 PoC 및 외부 접촉 원인 후보 추정에 사용하는 데이터셋을 기록한다.

> 원본 데이터 파일은 Git에 업로드하지 않는다.
> URL·라이선스·체크섬은 이 문서에 기록하고, 실제 파일은 로컬 또는 팀 공유 스토리지에 보관한다.

## 저장 위치

`data/datasets/` 아래에 데이터셋별로 보관한다. 이 디렉터리는 `.gitignore`에서
제외되며(`data/datasets/*`), `.gitkeep`만 git에 추적된다.

```text
data/datasets/
├─ caucafall/v5/
│  ├─ development/   # Subject 1~6
│  ├─ validation/    # Subject 7~8
│  └─ holdout/       # Subject 9~10 (최종 평가 전까지 미사용)
├─ gmdcsa24/v2.1/
├─ ur_fall/                  # 선택
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
| 개발·튜닝 | Subject 1~6 |
| 진단·튜닝 (`validation/` 디렉터리) | Subject 7~8 |
| 최종 내부 평가 (holdout) | Subject 9~10 |

Subject 7~8은 초기 Validation 이후 오류 분석과 규칙 검증에 사용되어 현재는
진단·튜닝 데이터로 취급한다. Subject 9~10(holdout)은 설정 동결 후 최종 평가
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

## UR Fall Detection Dataset

| 항목 | 내용 |
|---|---|
| 데이터셋명 | UR Fall Detection Dataset |
| 공식 URL | https://fenix.ur.edu.pl/~mkepski/ds/uf.html |
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
7/22~7/28 통합 및 현재 후속 데이터 계획에서 제외한다.

| 항목 | 내용 |
|---|---|
| 공식 저장소 | https://github.com/Hnnuliulei123456/MPFDD |
| 확인 범위 | 공개 샘플 28개 파일명·설명 |
| 실제 사용 | 없음(학습·평가·임계값 선택 미사용) |
| 미채택 사유 | 접촉 원인 라벨 부재, 라이선스 불명확 |

---

## 원인 후보 Mini Set (직접 촬영)

Phase 4 외부 접촉 원인 후보 추정 정량 검증(precision/recall, false
attribution)용 소규모 데이터셋. 현재 구현은 합성 multi-track 테스트로 계약을
검증했으며, 이 Mini Set 자체는 아직 촬영·사용하지 않았다
(`docs/decisions.md` ADR-016, `docs/fall_evaluation.md`의 검증 데이터 정책 참고).

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
Subject 7~8 timely Recall ≥ 75%
False alarm ≤ 0.2회/분
평균 감지 지연 ≤ 2초
낙상 1회당 이벤트 1회

기능 적용 후 FPS 저하 ≤ 20%
API 장애 중 파이프라인 비정상 종료 없음
```

Annotation V2와 Track handoff 안정화 이후 Development 결과는 Recall 83.3%,
timely Recall 66.7%, false alarm 0회/분, 중복 Event 0건이다. Subject 7~8
진단 결과는 Recall 100%, timely Recall 90%, false alarm 2.34회/분, 중복 Event
0건이다. 오탐 목표를 충족하지 못했고 Subject 7~8을 오류 분석에 사용했으므로,
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
목표를 통과했다. Development 지표는 유지됐고 S7~8 진단 FAR는
2.34→1.75/min으로 감소했다. 이 값은 API·Live Frame을 제외한 단일 파일
측정이며 S7~8도 tuning 데이터이므로 최종 성능으로 해석하지 않는다.

Subject 9~10 Holdout은 설정 동결 후에도 이번 통합 범위에서는 실행하지 않았다.
Phase 4 최종 평가에서 한 번만 사용한다. `FALL_SUSPECT.cause`의 원인 후보 Track
정확도·false attribution도 아직 정량 검증하지 않았으며, Phase 4에서 위 Mini
Set 또는 원인 라벨이 명확한 외부 데이터로 평가한다.
