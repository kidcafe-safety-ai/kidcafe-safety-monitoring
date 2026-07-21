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

## MPFDD (Multi-Person Falls Dataset)

외부 접촉 원인 후보 추정(`FallCauseAttributor`)의 hard-negative 후보
검토용으로 로컬에 클론했다. 원인 후보 양성 정확도 검증에는 쓰지 않는다
(`docs/fall_evaluation.md`의 검증 데이터 정책, `docs/decisions.md` ADR-016 참고).

| 항목 | 내용 |
|---|---|
| 데이터셋명 | MPFDD (Multi-Person Falls Dataset) |
| 공식 저장소 | https://github.com/Hnnuliulei123456/MPFDD |
| 접근 방법 | 저장소 clone (`data/datasets/mpfdd`) |
| 라이선스 | 저장소에 별도 LICENSE 파일이 없어 확인되지 않음 — 사용 전 원저자에게 확인 필요 |
| 전체 규모(공식 README 기준) | 220개 영상(ADL 80 + fall 140), 실내/실외, 2~5인 시나리오 |
| 로컬 보유분 | 공개 샘플 28개 영상(전체 220개 중 일부, Scene 1~4) |
| 원인 라벨 | 없음 — "N인 낙상"은 낙상 시점에 여러 사람이 있었다는 뜻일 뿐, 접촉으로 낙상했다는 원인 라벨은 제공하지 않는다 |
| 용도 | 원인 후보 hard-negative(다인 근접 + 원인 없는 독립 낙상) 후보 데이터 검토 |
| 검토 상태 | 로컬 28개 파일명·README 내용 검토 완료(hard-negative 후보로 쓸 수 있음을 확인). `false_cause_rate` 등 실제 hard-negative 실행은 아직 하지 않음 |

---

## 원인 후보 Mini Set (직접 촬영)

Phase 4 외부 접촉 원인 후보 추정 정량 검증(precision/recall, false
attribution)용 소규모 데이터셋. 현재 구현은 합성 multi-track 테스트와 MPFDD
공개 샘플 검토까지만 수행했고, 이 Mini Set 자체는 아직 촬영·사용하지 않았다
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

동일 입력·동일 하드웨어에서 적용 전후 각각 3회 측정하는 FPS 기준은 아직 완료하지
않았다. 짧은 파일 1회 비교에서는 opt-in 경로가 기본 경로보다 약 36.9% 낮았으며,
장시간/IP 카메라 통합 측정에서 재확인한다.

Subject 9~10 Holdout 평가는 설정 동결 전까지 보류한다. `FALL_SUSPECT.cause`의
원인 후보 Track 정확도·false attribution은 아직 정량 검증하지 않았으며,
Phase 4에서 위 Mini Set 또는 외부 데이터로 평가한다.
