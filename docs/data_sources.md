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
│  └─ holdout/       # Subject 9~10 (PR4 최종 평가 전까지 미사용)
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
- 해상도 1080×960, 23fps
- 낙상 5종: 전방, 후방, 좌측, 우측, 앉은 상태에서의 낙상 → `fall` 라벨
- ADL 5종: 걷기, 뛰기(hopping), 물건 집기, 앉기, 무릎 꿇기 → `no-fall` 라벨

### Subject 분할

| 분할 | Subject |
|---|---|
| 개발·튜닝 | Subject 1~6 |
| 검증 | Subject 7~8 |
| 내부 평가 (holdout) | Subject 9~10 |

Subject 9~10(holdout)은 PR4 최종 평가 전까지 사용하지 않는다.

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

## 원인 후보 Mini Set (직접 촬영)

Phase 3 외부 접촉 원인 후보 추정 검증용 소규모 데이터셋.

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

## Phase 3 평가 기준

```text
CAUCAFall Holdout Recall ≥ 75%
False alarm ≤ 0.2회/분
평균 감지 지연 ≤ 2초
낙상 1회당 이벤트 1회

원인 후보 Track 정확도 ≥ 70%
혼자 낙상 false attribution ≤ 20%
bystander false attribution ≤ 20%

기능 적용 후 FPS 저하 ≤ 20%
API 장애 중 파이프라인 비정상 종료 없음
```

동일 입력·동일 하드웨어에서 적용 전후 각각 3회 측정한다. 초기 baseline과 기준 차이가 크면 ADR에 근거를 기록한 뒤 한 번만 조정한다.
