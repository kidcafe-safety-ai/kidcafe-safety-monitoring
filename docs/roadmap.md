# KidCafe Safety AI — 개발 로드맵

> 최종 수정: 2026-07-29
> MVP baseline: `v0.1.0-mvp`
> 본 문서는 MVP 1차 종료 이후 최종 제출까지의 상위 개발 로드맵이다.
> 한이음 일정은 [2026년 창의도전형 공고](https://www.hanium.or.kr/comm/noticeView.do?ntcAtclSn=63940) 기준으로 갱신했다. 세부 일정(주차별 작업·보고서 내부 마감 등)은 팀 오피스 기준이며 공식 공고와 별개로 운영한다.

---

## Roadmap Summary

| 기간 | 단계 | 핵심 목표 |
| --- | --- | --- |
| 5/31까지 | MVP 1차 종료 | 파일 영상 기반 MVP 기준선 고정 |
| 6/1-6/8 | Phase 1.5 | 서비스 구조 전환 준비 — 완료 |
| 6/8-6/21 | Phase 2 | 실시간 입력 연결 — 완료 |
| 6/22-6/30 | Phase 2.5 | 실시간 운영 대시보드 v1 안정화 — 완료 |
| 7월 | Phase 3 — **완료(7/27)** | 안전 감지 고도화 |
| 7/29-8/29 | Phase 4 | 실제 데이터 검증·선택 개선·1차 공모전 준비 |
| 9월 | Phase 5 | 성과 정리 및 2차 평가 준비 |
| 10월 이후 | Final | 최종 제출·시연·발표 |
| 11월 | Post Final | 최종 평가 및 시상 대응 |

---

## 5/31까지 — MVP 1차 종료

**목표**: 파일 영상 기반 MVP를 공식 기준선으로 고정한다.

### 핵심 작업

- [x] main 머지
- [x] `v0.1.0-mvp` 태그 생성
- [x] README / ADR / interfaces / roadmap 정리
- [x] Phase 1.5 역할 확정 (Phase 1.5에서 완료)
- [x] Event Schema v1 확인
- [x] API 계약 초안 (Phase 1.5에서 완료)
- [x] React 화면 범위 확정 (Phase 1.5에서 완료)
- [x] 모델 비교 후보 확정
- [x] 실험 영상 후보 확정
- [x] 브랜치 / 파일 소유권 규칙 확정 (Phase 1.5에서 확정)
- [ ] 데이터 확보 계획 초안
- [ ] 개인정보 / 촬영 동의 / 비식별 처리 방식 검토
- [ ] 최종 성능지표 초안
- [ ] 논문 / 경진대회 목표 후보 확정

---

## 6/1-6/8 — Phase 1.5: 서비스 구조 전환 준비 — 완료

**목표**: MVP 1차를 실시간 서비스 구조로 확장하기 위한 기반을 만든다.

### 완료 항목

- [x] Event Schema v1 확정 (MVP 기존 구조 유지)
- [x] FastAPI + SQLite 최소 API 구현
- [x] React mock Dashboard 2페이지 (모니터링 / 이벤트 기록)
- [x] YOLO 모델 1차 비교 완료 → YOLO26n 선정
- [x] InputSource 인터페이스 초안 (`interfaces.md` Section 8)
- [x] API Contract v1 문서화
- [x] 역할별 담당 파일 범위 확정

### 산출물

- `src/api/` — FastAPI + SQLite
- `frontend/` — React mock Dashboard
- `docs/model_benchmark.md` — YOLO 모델 비교 결과
- `docs/api_contract.md` — API 계약 v1
- `scripts/` — 벤치마크 도구

---

## 6/8-6/21 — Phase 2: 실시간 입력 연결 — 완료

**목표**: 저장 영상 기반 구조를 웹캠 / RTSP / IP 카메라 기반 실시간 구조로 전환한다.

### 완료 항목

**A**
- [x] WebcamSource 구현
- [x] RTSPSource 구현 (credential sanitize 포함)
- [x] YOLO26n 기준 실시간 추론 테스트
- [x] 이벤트를 FastAPI `POST /events`로 전송
- [x] `PUT /status/current`로 현재 감지 상태 전송 (2초 주기)
- [x] latency / FPS 측정 및 `docs/realtime_test.md` 기록

**B**
- [x] `PUT /status/current` / `GET /status/current` API 구현
- [x] SQLite upsert (`INSERT ... ON CONFLICT DO UPDATE`)
- [x] 실시간 이벤트 저장 검증

**C**
- [x] `eventsApi.ts` mock → FastAPI 실제 호출 전환 (`VITE_API_MODE`)
- [x] `/events/recent` polling (3초), `/summary` polling (10초), `/status/current` polling (2초)
- [x] loading / error / empty 상태 처리

### 우선순위 원칙

```text
1. 웹캠 기반 end-to-end 먼저 완성
2. 실시간 영상 스트리밍보다 실시간 이벤트 저장/조회 우선
3. WebSocket은 Phase 2 / Phase 2.5 / Phase 3 제외 → Phase 4 이후 검토
4. Current Status는 Event 누적이 아니라 /status/current 별도 처리
```

### 산출물

- [x] 웹캠 실시간 입력 파이프라인 (`src/input/`, `src/integrations/`)
- [x] FastAPI 이벤트 송수신 + current status API (`src/api/routers/status.py`)
- [x] React API 연동 (`frontend/src/api/eventsApi.ts`, `usePolling`)
- [x] `docs/realtime_test.md` 실험 로그
- [x] `v0.2.0-realtime` 태그 생성

---

## 6/22-6/30 — Phase 2.5: 실시간 운영 대시보드 안정화 — 완료

**목표**: Phase 2.0에서 구현한 실시간 연결 구조를 기반으로, 중간평가 및 시연 가능한 실시간 운영 대시보드 v1을 완성한다.

### Phase 정의

```text
Phase 2.0 = 각 모듈을 연결한다
Phase 2.5 = 연결된 흐름을 시연 가능한 수준으로 안정화한다
Phase 3   = 안전 감지 기능을 고도화한다
```

### 핵심 원칙

```text
- 웹캠 기반 end-to-end 흐름을 최우선으로 안정화
- React는 REST polling 기반 유지
- WebSocket, ReID, 낙상, 충돌은 Phase 3 이후
- Event Schema v1 / CurrentStatus 구조 유지
- 이벤트 흔들림은 기록하고 실제 보정은 Phase 3에서 처리
```

### 역할별 작업 범위

**A — Vision AI / 실시간 입력 안정화**

```text
[x] 내장 웹캠 3-5분 E2E 테스트 (300프레임 / 2700프레임)
[x] API 서버 미기동 / 재기동 상황 테스트
[x] FPS / latency / frame drop 측정
[x] ENTER / EXIT 이벤트 흔들림 기록
[x] docs/realtime_test.md 실험 결과 업데이트
[x] macOS Docker Compose E2E 검증 (내장 웹캠 → Docker FastAPI)
```

**B — FastAPI / SQLite 안정화**

```text
[x] POST /events 저장 안정성 검증
[x] PUT /status/current 저장 안정성 검증
[x] GET /status/current 조회 안정성 검증
[x] API validation / error response 정리
[x] CORS / React 개발 서버 연동 확인
[x] Docker Compose FastAPI 컨테이너 구성 및 검증
[x] SQLite bind mount (./outputs:/app/outputs) 확인
```

**C — React Dashboard 안정화 + USB 웹캠 테스트**

```text
[x] 실제 API 기반 화면 안정화
[x] loading / error / empty 상태 처리 개선
[x] KPI 문구 정확화
[x] 이벤트 기록 / 통계 화면 완성도 개선
[x] USB C920 웹캠 연결 확인 (camera index 0 / 1)
[x] USB 웹캠 반복 E2E 검증 (Windows, 단일 3-5분 실행 대신 반복 시나리오로 완료 인정)
    - 300프레임 API/SQLite E2E
    - 180프레임 메인 pipeline
    - 60프레임 API 장애 테스트
[x] React build 통과 확인
[x] Docker Compose React 컨테이너 구성 및 API mode 검증
[x] 오늘 이벤트 / 최근 10분 이벤트 KPI 집계 기준 정합성 수정
```

### RTSP / IP 카메라 기준

```text
- RTSPSource 인터페이스 구현 완료 (credential sanitize 포함)
- Phase 2.5에서 실장비 미확보로 실측 테스트 미수행
- 장비 확보 후 별도 테스트 브랜치에서 연동 검증 예정
- 실제 RTSP URL / 계정 / 비밀번호는 문서나 PR에 포함하지 않음
```

### Phase 2.5 완료 기준

```text
1. 내장 웹캠 기반 end-to-end 흐름이 3-5분 이상 안정적으로 동작한다.
2. USB 웹캠 환경에서도 동일 흐름을 테스트한다.
3. 이벤트가 FastAPI와 SQLite를 거쳐 React에 표시된다.
4. CurrentStatus가 React KPI와 zone 상태에 반영된다.
5. API 서버 장애 상황에서 화면과 pipeline이 크게 깨지지 않는다.
6. 실행 방법과 테스트 결과가 docs/realtime_test.md에 기록된다.
7. 중간평가에서 시연 가능한 수준의 대시보드 v1이 준비된다.
```

### Phase 2.5 제외 범위

```text
- WebSocket 실시간 push
- ReID / 낙상 감지 / 독립 충돌 감지 (`COLLISION_SUSPECT`는 Phase 4 이후 재검토)
- Zone Settings FastAPI 연동
- 다중 카메라 고도화
```

### Docker 도입 범위

Phase 2.5에서는 시연 재현성과 팀원 실행 환경 통일을 위해 Docker Compose를 제한적으로 도입한다.

도입 범위:

```text
- FastAPI
- React
- SQLite volume
- .env.example
- docker-compose.yml
```

제외 범위:

```text
- Vision AI 웹캠 파이프라인
- YOLO 추론 환경
- GPU / MPS 설정
- USB 카메라 passthrough
- RTSP 운영 안정화
```

Docker 도입 시 역할:

```text
A
- Vision AI 파이프라인은 Docker에 포함하지 않고 기존처럼 로컬 실행 유지
- --api-url http://localhost:8000 으로 Docker FastAPI에 이벤트 / CurrentStatus 전송 확인

B
- FastAPI 컨테이너 구성
- 8000 포트 노출
- SQLite outputs volume 저장 확인
- /health, /events, /events/recent, /summary, /status/current API smoke test 확인

C
- React 컨테이너 또는 실행 설정 정리
- VITE_API_BASE_URL=http://localhost:8000
- VITE_API_MODE=api
- React Dashboard에서 Docker FastAPI 호출 및 화면 표시 확인
```

Docker는 배포 목적이 아니라, 개발 / 시연 실행 환경을 통일하기 위한 목적으로 도입한다.

### 산출물

- [x] 내장 웹캠 / USB 웹캠 기반 E2E 안정화 결과
- [x] React 운영 대시보드 v1
- [x] `docs/realtime_test.md` Phase 2.5 테스트 기록
- [x] Docker Compose 구현 및 Windows(USB C920) / macOS(내장 웹캠) 검증 완료
- [x] 중간평가 보고서 (마감 2026-07-14 18:00, Phase 3 7/7-7/14 일정으로 이관 — Phase 2.5 종료 blocker 아님, 이후 제출 및 B/C 승인 완료)

### Phase 3 인계 기술 부채

```text
- API 비동기 전송 또는 전송 queue: API 장애 시 동기 timeout으로 FPS 0.99 저하
- debounce / hysteresis: zone 경계에서 ENTER/EXIT 빠른 반복 발생
- React Live View: latest-frame polling 계약 확정, 구현 예정
- FPS 재측정 및 최적화: Windows CPU 환경 avg 6.23 FPS, 개선 여지 있음
```

---

## 7월 — Phase 3: 안전 감지 고도화

**목표**: 단순 구역 이벤트를 실제 키즈카페 안전 시나리오에 맞는 감지 정책으로 고도화한다.

> Phase 3 계약 상세(EventType·ZoneType·API·DB migration)는 `docs/interfaces.md`, `docs/api_contract.md`, `docs/decisions.md`가 최종 기준이다.

### 일정

```text
7/7-7/10   Live View — Live Frame latest-only worker 최소 구현 (E2E 우선)
7/11-7/14  중간평가 보고서
7/15-7/21  핵심 기능 — 공간정책·FALL_SUSPECT·이벤트 확장 (AsyncEventDispatcher의 Event FIFO queue·Status latest-only 확장은 완료)
7/22-7/27  통합 (M1/MPS 낙상 runtime 최적화 포함, 계획(7/28)보다 하루 앞당김)
7/27       Phase 3 종료 — 낙상 오탐 개선(hard-negative 재학습, temporal
           classifier, 외부 데이터)과 Subject 9-10 최종 holdout은 Phase 4로 이관
```

### 역할

```text
A(정종민): 낙상·원인 후보·비차단 전송·annotated frame·FPS/latency
B(원우민): 공간정책·이벤트 흔들림·Live API·EventCause/DB migration·Zone Settings 계약
C(정현수): Live UI·신규 이벤트/cause·AlertHistory·화면 성능
```

> 예외: 공간정책·debounce 작업은 README 파일 소유권상 A 소유인 `src/events/`, `src/geofencing/`에 B가 조율해 수정한다. 충돌 방지를 위해 B 공간정책 PR → A 낙상 연결부 PR 순서로 진행한다.

> B 공간정책 상태 (2026-07-16): `EventManager`에 zone 전이 확인(진입 0.3초, 이탈 0.5초, Track 소실 유예 0.5초)과 `ENTER_RESTRICTED`·`DANGER_ZONE_DWELL` 치환 로직을 구현했다. 단위 테스트로 경계 진동 억제와 중복 이벤트 금지를 확인했다.
>
> B 공간정책 실측 결과 (2026-07-18): 실제 영상 전후 비교로 전체 이벤트 46.4% 감소(28→15건), 0.52초 이내 빠른 반전 12→0건을 확인했다(`docs/realtime_test.md` 참고). zone 진입 ground truth annotation이 없어 정량 임계값 재튜닝은 수행하지 못했으며, 실제 카메라 데이터 기반 재튜닝은 Phase 4로 이관한다.

> A 통합 상태 (2026-07-22): 동결한 낙상 PoC의 JSONL → FastAPI → SQLite →
> Dashboard / Live Frame 전파와 API 장애 중 비차단 실패 보존을 확인했다.
> Signal Cache 회귀 지표는 유지됐고, 능동 인원 영상에서 낙상 ON의 FPS 감소가
> 46.1%로 목표(20% 이내)를 넘었다. 기능은 opt-in·기본 비활성으로 유지하며
> 실제 원인 후보 정확도와 최종 holdout은 Phase 4로 이관한다.

> A runtime 최적화 상태 (2026-07-22): 별도 opt-in Pose NORMAL gate와 보조
> 모델 interval `3` 프로파일은 Development·S7-8 회귀 기준을 유지했다.
> M1/MPS 단일 파일 OFF/ON 각 3회 중앙값 기준 FPS 하락률 7.3%로 목표를
> 통과했고, S7-8 진단 FAR는 2.34→1.75/min으로 감소했다. API 포함 반복 측정,
> 다른 장치, 운영 FAR 개선은 Phase 4 후속으로 남긴다.

> Phase 3 종료 범위 확정 (2026-07-27): Phase 3는 현재 병합된 범위(Annotation
> V2·평가 프로토콜, Signal Cache·Tracker Sweep, Candidate/Cooldown Handoff,
> 원인 후보 추정, Pose gate + interval 3 runtime 최적화, 통합 E2E·성능 측정)로
> 종료한다. 7/22-7/27 잔여 일정에는 Phase 3 추가 성과로 M1/MPS 낙상 runtime
> 최적화를 수행했다. 데이터 추가, hard-negative 재학습, temporal classifier
> 비교 등 정확도 개선 실험은 Phase 3 종료 게이트에 포함하지 않으며 Phase 4
> 모델 고도화 범위(A 역할 첫 번째 작업 묶음)로 이관한다. Subject 9-10 holdout도
> Phase 4 최종 평가로 이관한다.

### 우선순위

```text
P0: Live View, 공간 안전정책, debounce/hysteresis, FALL_SUSPECT PoC,
    비차단 API 전송, 신규 이벤트 E2E

P1: 외부 접촉 원인 후보 추정, 신규 이벤트 Dashboard·AlertHistory 반영,
    성능·회귀 측정, flake8·CI

P2: Zone Settings 계약, 인증/인가 미니 ADR,
    SystemSettings·Report 연동 범위, Phase 4 이관 기준
```

### 성공 기준 / 종료 게이트

```text
- Live View E2E (frame 제공 → API → React 표시) 확인 — 완료
- FALL_SUSPECT opt-in PoC 구현 및 Development/Subject 7-8 진단 결과 기록
  (`cause` 원인 후보 추정 완료, 정량 정확도는 Phase 4) — 완료
- zone_type 기반 ENTER_RESTRICTED / DANGER_ZONE_DWELL 이벤트 정상 발생 — 완료
- API 장애 중 추론 루프 유지 — 완료 (실패 Event는 실행별 JSONL에 보존)
- false positive·감지 지연·FPS 결과 기록 — 완료 (S7-8 FAR 1.75/min, 운영 목표
  0.2/min 미달은 Phase 4 이관, FPS 하락률 7.3%로 목표 충족)
- flake8·pytest·React build·GitHub Actions 통과 — 완료
- Zone Settings 계약·인증/인가 미니 ADR 확정 — 완료 (저장 API 구현은 Phase 4,
  `docs/api_contract.md`의 Zone Settings 저장 계약, ADR-018 참고)
- 중간평가 보고서 기한 내 제출 — 완료
- A/B/C 전원 계약 일치 승인 — 완료
```

### CI 품질 게이트

> 상태: 구현 완료 (`chore/ci-baseline`) — Phase 3부터 PR 단위로 flake8·pytest·React build를 GitHub Actions에서 자동 검증한다.
> main에서 CI가 최초 green 된 뒤 required check 활성화를 검토한다.

도입 전 측정:

```text
flake8 src tests                       → 148건
flake8 src tests --max-line-length=99  → 38건
```

적용 후:

```text
flake8 src tests → 0건
pytest -q        → 220 passed, 1 skipped
React build      → 통과
```

적용 순서:

```text
flake8 99자 기준선 설정
→ 기존 38건 수정
→ pytest 전체 통과
→ Backend·Frontend GitHub Actions 추가
→ main 최초 성공
→ required check 활성화
```

```text
flake8 src tests
pytest -q
npm ci
npm run build
```

권장 `.flake8` 설정:

```ini
[flake8]
max-line-length = 99
extend-exclude =
    .venv,
    frontend,
    node_modules,
    outputs
per-file-ignores =
    tests/test_charts.py:E402
```

`F401`, `F541`, `F841`은 무시하지 않고 수정한다. `tests/test_charts.py`의 E402만 예외로 허용한다.

### 개발 진행 순서

```text
Phase 3 Open·계약 문서 PR
→ CI 기준선 PR
→ Live View A→B→C 순차 통합
→ 7/11-7/14 보고서 제출
→ EventType·ZoneType·EventCause 공용 코드 PR
→ A/B/C 역할별 병렬 개발
→ integration E2E
→ main
```

### 운영 확정

```text
- Stretch: `APPROACH_EXIT`
  - Phase 3 활성 계약에는 아직 포함하지 않는다.
  - 구현 착수 시 계약을 먼저 갱신한다.
- 중간평가 보고서:
  - 총괄: 정종민(A)
  - 역할별 섹션: A(정종민) / B(원우민) / C(정현수)
  - 담당자는 회의록 링크로 대체 가능
```

### 핵심 작업

- 공간 안전정책 고도화
- `zone_type` 분리 (`play | exit | restricted | danger`)
- 안전구역 이탈 / 출입구 접근 / 제한구역 진입 규칙 정의
- debounce / hysteresis 적용
- FALL_SUSPECT opt-in PoC 완료 및 잔존 오탐 개선 계획 정리
- FALL_SUSPECT.cause 외부 접촉 원인 후보 추정 완료 (정량 정확도 평가는 Phase 4)
- 공개 데이터(CAUCAFall) 기반 실험 및 라벨링 기준 정리 완료 — 실제 키즈카페 재현 촬영은 Phase 4로 이관
- 낙상 · 위험구역 이벤트 정의 확정

### 비고

- Phase 3은 계획(7/28)보다 하루 빠른 7/27에 종료했다.
- Phase 4에는 실제 촬영 평가, 선택적 낙상 개선, Homography, Zone·Report 연동과
  공모전 제출 준비가 겹치므로 Phase 3에서 공간 안전정책과 FALL_SUSPECT
  opt-in PoC, 외부 접촉 원인 후보 추정까지 구현을 마쳤다.

### 산출물

- 공간 안전정책 v1
- FALL_SUSPECT opt-in PoC 및 Development/Subject 7-8 진단 기록
- FALL_SUSPECT.cause 외부 접촉 원인 후보 추정 완료 (정량 정확도 평가는 Phase 4)
- Live View latest-frame polling E2E
- 실험 데이터 기준

---

## 7월 29일-8월 29일 — Phase 4: 실제 데이터 검증 및 공모전 준비

**목표**: Phase 3의 낙상·원인 후보·공간 안전정책을 실제 촬영 데이터로
검증하고, 조건을 충족한 개선만 production에 반영한 뒤 공모전 제출물을 만든다.

### 주요 일정

- 7/29-7/30: 계약·`phase4_fall_eval_v1` 동결
- 7/31-8/6: E1 hard-negative·Homography·Zone·Report 병렬 개발
- 8/7: 실제 테스트 영상 공동 촬영
- 8/8-8/12: 라벨링·기준선·cause·tracking·Homography 분석
- 8/13-8/16: 조건을 충족한 개선만 선택 적용
- 8/17-8/20: 모델·API·UI 동결과 최종 E2E
- 8/21-8/28: 제출물 제작·검수, 8/28 내부 제출
- 8/29: 공식 일정 확인과 제출 상태 대응

### 핵심 작업

- 외부·촬영 데이터 기반 낙상 E1 개선 실험 — 완료
- 실제 촬영 timely Recall·FAR 평가 — 완료
- cause·ID switch 정량 분석 — 진행 중
- Homography floor-plane Zone 기본 비활성 PoC
- Zone Settings 실제 저장·version 충돌 처리
- ReportPage 기간별 실제 Event 연동
- Recent Event UX와 API mode 회귀
- CAUCAFall 참고 holdout은 필요 시 회귀 확인용으로만 평가
- 실제 영상 A/B/C E2E
- 개발보고서·제작설계서·시연 영상 준비

### A 진행 상태 (2026-08-11)

- 8월 7일 실제 키즈카페 목표 IP 카메라 구도의 성인 통제 재연 영상 64개를
  계약 형식으로 정리하고 R01·R02 검수를 완료했다.
- A01 촬영 frame을 기존 보조 detector에 추가 학습한 E1을 채택했다.
- 학습하지 않은 A03 actor-disjoint test에서 Recall 93.3%, timely Recall 93.3%,
  FAR 0.0/min, 평균 onset latency 0.441초, 중복 Event 0건을 기록했다.
- E1 낙상 모델과 inference 설정은 목표 키즈카페 카메라의 selected profile로
  동결했다. 장시간 RTSP·Cause 검증 전까지 실행은 명시적 opt-in으로 유지한다.
- 실제 영상의 Vision AI·API·SQLite·Live Frame E2E를 통과했다.
- 다음 A 작업은 다중 인원 Cause·ID switch 분석과 조건부 Tracker 비교다.

경량 temporal classifier는 E1 이후에도 같은 오탐이 실제 촬영에서 재현될 때만
검토한다. BoT-SORT는 ID switch가 실제 missed·duplicate·cause 오류를 반복해서
유발할 때만 비교하며, StrongSORT·ReID는 그 이후 후속 범위다. Cross-camera
ReID와 YOLO 모델 비교는 Phase 4 필수 범위가 아니다.

### 일정 기준

2026년 공식 공고는 프로젝트 수행 기간을 4월 1일-10월 30일로 안내하고,
공모전 상세 일정은 추후 별도 공지한다고 명시한다. 따라서 8월 28일과 29일은
각각 팀 내부 제출일과 잠정 관리일이며 공식 마감으로 표현하지 않는다.

### 산출물

- `Phase 4 Contract v1`과 평가 fixture
- 낙상·cause·tracking·Homography 결과표
- 실제 촬영 manifest·annotation·재현 명령
- Zone Settings·Report 실제 연동
- 공모전 개발보고서·제작설계서·시연 영상

구현 계약은 `docs/api_contract.md`, `docs/interfaces.md`,
`docs/fall_evaluation.md`, `docs/data_sources.md`에 책임별로 기록한다.

---

## 9월 — Phase 5: 성과 정리 및 2차 평가 준비

**목표**: 논문, 발표, 2차 평가를 위한 결과물 완성도를 높인다.

### 핵심 작업

- 논문 제출처 확정
- 논문 초안 작성
- 아이디어 정리
- 성능 실험표 정리
- 발표자료 초안
- 시연 시나리오 정리
- 개인정보 / 비식별 처리 내용 정리
- 논문 형식에 맞춘 실험 결과 재정리
- 2차 평가용 최종본 준비

### 한이음 일정 참고

- 2차 평가 신청기간: 9/11-10/14
- 제출물: 개발보고서, 제작설계서 최종본, GitHub
- 평가 방식: 실시간 현장 시연 및 PT 발표
- 2차 평가에서는 기능 수보다 실시간 시연 안정성이 중요하다.

### 산출물

- 2차 평가 제출물
- 발표자료 초안
- 논문 초안
- 시연 시나리오

---

## 10월 이후 — Final: 제출·시연

**목표**: 최종 제출과 발표, 외부 제출을 안정적으로 마무리한다.

### 핵심 작업

- 최종 시연 영상
- 한이음 결과물 제출
- 최종 발표
- 논문 / 경진대회 제출
- 특허 제출 여부 최종 결정
- 프로젝트 회고
- 개인별 포트폴리오 정리

### 산출물

- 최종 결과물
- 최종 발표자료
- 최종 시연 영상
- 논문 / 경진대회 제출본
- 포트폴리오 정리 자료

---

## 11월 — Post Final: 최종 평가 및 시상 대응

**목표**: 3차 평가 및 시상 가능성에 대응한다.

### 한이음 일정 참고

- 3차 평가 및 시상: 11/18
- 최종 1팀 선정 기준

### 비고

- 3차 평가는 2차 평가 통과 이후 대응한다.
- 현 시점에서는 1차, 2차 평가 통과를 우선 목표로 한다.

---

## 주요 리스크 및 운영 원칙

### 데이터 확보 리스크

실제 키즈카페 아동 영상은 개인정보 이슈로 확보가 어려울 수 있다. 공개 영상, 팀원 재현 촬영, 빈 시간대 촬영, 비식별 샘플 확보 등 대체 데이터 전략을 병행한다.

### 실시간 입력 안정화 리스크

RTSP / IP 카메라 연결은 네트워크, 코덱, 지연시간, 끊김 문제가 발생할 수 있다. 웹캠 입력을 먼저 안정화한 뒤 RTSP / IP 카메라로 확장한다.

### Tracker / ReID 범위 조절

ByteTrack과 기존 handoff를 기본으로 유지한다. 실제 촬영에서 ID switch가 Event
오류를 유발한 경우에만 BoT-SORT를 비교한다. StrongSORT·ReID는 BoT-SORT
이후에도 오류가 남을 때 후속 검토하며, cross-camera ReID는 Phase 4 범위에서
제외한다.

### 시연 안정성 우선

최종 평가는 기능 개수보다 안정적인 시연이 중요하다. 발표 전에는 새로운 기능 추가보다 입력 안정성, 이벤트 정확성, 대시보드 오류 방지를 우선한다.

### 문서화 병행

실험 결과, 실패 사례, 모델 비교, 데이터 출처는 개발 중 바로 문서화한다. 최종 보고서, 논문, 포트폴리오에 재사용하기 위해 날짜와 작성자를 남긴다.

---

## 핵심 전략

1. 5월 말까지 MVP 1차를 고정한다.
2. 6월에는 실시간 서비스 구조를 만든다.
3. 7월에는 안전 감지 기능의 차별점을 만든다.
4. 8월에는 공모전 1차 제출 가능한 완성도를 확보한다.
5. 9월에는 논문, 발표, 2차 평가 자료를 정리한다.
6. 10월 이후에는 최종 시연과 외부 제출에 집중한다.

---

## 참고

- MVP 범위 상세: [README.md — MVP 1단계 상태](../README.md)
- 인터페이스 계약: [docs/interfaces.md](interfaces.md)
- 의사결정 기록: [docs/decisions.md](decisions.md)
