# KidCafe Safety AI — 개발 로드맵

> 최종 수정: 2026-06-24
> MVP baseline: `v0.1.0-mvp`
> 본 문서는 MVP 1차 종료 이후 최종 제출까지의 상위 개발 로드맵이다.
> 한이음 일정은 2025년 창의도전형 공고 기준으로 작성했으며, 2026년 공고 확인 후 갱신한다.

---

## Roadmap Summary

| 기간 | 단계 | 핵심 목표 |
| --- | --- | --- |
| ~5/31 | MVP 1차 종료 | 파일 영상 기반 MVP 기준선 고정 |
| 6/1~6/8 | Phase 1.5 | 서비스 구조 전환 준비 — 완료 |
| 6/8~6/21 | Phase 2 | 실시간 입력 연결 — 완료 |
| 6/22~6/30 | Phase 2.5 | 실시간 운영 대시보드 v1 안정화 |
| 7월 | Phase 3 | 안전 감지 고도화 |
| 8월 | Phase 4 | 모델·추적 고도화 및 1차 공모전 준비 |
| 9월 | Phase 5 | 성과 정리 및 2차 평가 준비 |
| 10월~ | Final | 최종 제출·시연·발표 |
| 11월 | Post Final | 최종 평가 및 시상 대응 |

---

## ~5/31 — MVP 1차 종료

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

## 6/1~6/8 — Phase 1.5: 서비스 구조 전환 준비 — 완료

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

## 6/8~6/21 — Phase 2: 실시간 입력 연결 — 완료

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
3. WebSocket은 Phase 2 / Phase 2.5 제외 → Phase 3 이후 검토
4. Current Status는 Event 누적이 아니라 /status/current 별도 처리
```

### 산출물

- [x] 웹캠 실시간 입력 파이프라인 (`src/input/`, `src/integrations/`)
- [x] FastAPI 이벤트 송수신 + current status API (`src/api/routers/status.py`)
- [x] React API 연동 (`frontend/src/api/eventsApi.ts`, `usePolling`)
- [x] `docs/realtime_test.md` 실험 로그
- [x] `v0.2.0-realtime` 태그 생성

---

## 6/22~6/30 — Phase 2.5: 실시간 운영 대시보드 안정화

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
- 내장 웹캠 3~5분 E2E 테스트
- API 서버 미기동 / 재기동 상황 테스트
- FPS / latency / frame drop 측정
- ENTER / EXIT 이벤트 흔들림 기록
- docs/realtime_test.md 실험 결과 업데이트
```

**B — FastAPI / SQLite 안정화**

```text
- POST /events 저장 안정성 검증
- PUT /status/current 저장 안정성 검증
- GET /status/current 조회 안정성 검증
- API validation / error response 정리
- CORS / React 개발 서버 연동 확인
- 필요 시 /events 조회 최적화 검토
```

**C — React Dashboard 안정화 + USB 웹캠 테스트**

```text
- 실제 API 기반 화면 안정화
- loading / error / empty 상태 처리 개선
- KPI 문구 정확화
- 이벤트 기록 / 통계 화면 완성도 개선
- USB 웹캠 연결 확인 (camera index 0 / 1 / 2 테스트)
- USB 웹캠 3~5분 E2E 실행 및 결과 PM 공유
- React build 통과 확인
```

### RTSP / IP 카메라 기준

```text
- 장비 미확보 상태이므로 Phase 2.5에서는 실측 테스트 보류
- 장비 확보 시 연결 성공 또는 실패 원인 문서화
- 실제 RTSP URL / 계정 / 비밀번호는 문서나 PR에 포함하지 않음
- RTSPSource 구현 구조는 유지
```

### Phase 2.5 완료 기준

```text
1. 내장 웹캠 기반 end-to-end 흐름이 3~5분 이상 안정적으로 동작한다.
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
- ReID / 낙상 / 충돌 감지
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

- 내장 웹캠 / USB 웹캠 기반 E2E 안정화 결과
- React 운영 대시보드 v1
- `docs/realtime_test.md` Phase 2.5 테스트 기록
- 개발 / 시연 재현성 확보용 Docker Compose 초안
- 중간평가용 시연 결과물

---

## 7월 — Phase 3: 안전 감지 고도화

**목표**: 단순 구역 이벤트를 실제 키즈카페 안전 시나리오에 맞는 감지 정책으로 고도화한다.

### 핵심 작업

- 공간 안전정책 고도화
- `zone_type` 분리
- 안전구역 이탈 / 출입구 접근 / 제한구역 진입 규칙 정의
- debounce / hysteresis 적용
- 충돌 의심 PoC
- 낙상 의심 PoC
- 실제 / 유사 키즈카페 영상 확보
- 라벨링 기준 정리
- 낙상 / 충돌 / 위험구역 이벤트 정의 확정

### 비고

- 7월 일정은 계획보다 빠르게 진행되어야 한다.
- 8월에는 ReID, cross-camera(후순위), 모델 비교, 공모전 1차 제출 준비가 겹치므로 7월 중순까지 공간 안전정책과 충돌/낙상 PoC 1차 구현을 목표로 한다.

### 산출물

- 공간 안전정책 v1
- 충돌 의심 PoC
- 낙상 의심 PoC
- 실험 데이터 기준

---

## 8월 — Phase 4: 모델·추적 고도화 및 1차 공모전 준비

**목표**: 모델, 추적, ReID, fine-tuning 가능성을 검토하고 1차 공모전 제출 가능한 결과물을 만든다.

### 핵심 작업

- ReID 적용 여부 최종 판단
- 단일 카메라 ReID 우선 개발
- StrongSORT / BoT-SORT 비교
- cross-camera 확장 가능성 검토
- YOLO 모델 비교
- fine-tuning 가능 여부 판단
- 키즈카페 / 아동 유사 데이터 라벨링
- 모델별 성능표 정리
- ID switch / FPS / event accuracy 실험 정리
- 시연 동영상 준비
- 개발보고서 / 제작설계서 초안 준비
- 논문대회 일정 및 양식 확인

### 한이음 일정 참고

- 1차 공모전 신청기간: 8/1 ~ 8/29 16시
- 제출물: 개발보고서, 제작설계서, 시연 동영상
- 1차 평가는 단순 접수가 아니라 시상 후보 여부를 결정하는 핵심 단계다.

### 산출물

- 1차 공모전 제출물
- 시연 동영상
- 모델 / 추적 성능 비교표
- 실험 결과 문서

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

- 2차 평가 신청기간: 9/11 ~ 10/14
- 제출물: 개발보고서, 제작설계서 최종본, GitHub
- 평가 방식: 실시간 현장 시연 및 PT 발표
- 2차 평가에서는 기능 수보다 실시간 시연 안정성이 중요하다.

### 산출물

- 2차 평가 제출물
- 발표자료 초안
- 논문 초안
- 시연 시나리오

---

## 10월~ — Final: 제출·시연

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

### ReID / Cross-Camera 범위 조절

ReID와 cross-camera는 구현 난이도가 높으므로 8월 중순까지 PoC 결과를 보고 범위를 조절한다. 최소 목표는 단일 카메라 ReID 또는 ID switch 감소 실험으로 둔다.

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
