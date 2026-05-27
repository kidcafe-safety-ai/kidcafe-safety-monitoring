# KidCafe Safety AI — 개발 로드맵

> 최종 수정: 2026-05-27  
> MVP baseline: `v0.1.0-mvp`  
> Phase 2 착수 예정: 2026-06-01

---

## Phase 1: MVP baseline (완료)

**목표**: 파일 영상 기반 end-to-end 검증

| 항목 | 상태 |
|------|------|
| YOLO + ByteTrack 탐지/추적 | Done |
| Zone JSON 기반 Geofencing | Done |
| ENTER / DWELL / EXIT 이벤트 생성 | Done |
| `events.jsonl`, `events.csv`, `summary.json` 출력 | Done |
| `result.mp4` 결과 영상 | Done |
| Streamlit 검증 대시보드 | Done |
| pytest 기반 테스트 | Done |

**baseline 태그**: `v0.1.0-mvp`

---

## Phase 2: 실시간 서버 + React 대시보드

**목표**: 실시간 입력 + 운영형 UI

세부 일정 및 태스크는 착수 시 별도 정리.

| 항목 | 상태 |
|------|------|
| FastAPI 서버 구축 | Phase 2 |
| WebSocket 실시간 이벤트 스트림 | Phase 2 |
| IP 카메라 / RTSP 실시간 입력 | Phase 2 |
| React 운영 대시보드 전환 | Phase 2 |
| DB 연동 (이벤트 영구 저장) | Phase 2 |
| 필터 / 알림 (카카오/문자/이메일) | Phase 2 |
| 설정 영구 저장 (`config.json`) | Phase 2 |

---

## Phase 3: 공간 안전정책 고도화

| 항목 |
|------|
| Zone 규칙 고도화 (밀집도, 충돌 경고) |
| 알림 임계값 정책 설계 |
| 날짜별 데이터 관리 구조 |
| 관리자 확인 처리 흐름 |

---

## Phase 4: 낙상 / 충돌 감지

| 항목 |
|------|
| Pose Estimation 도입 (MediaPipe 또는 YOLOv8-pose) |
| 낙상 감지 모듈 |
| 충돌/접촉 감지 모듈 |
| 이벤트 타입 확장 (`FALL`, `COLLISION`) |

---

## Phase 5: ReID / 모델 비교 / 논문 실험

| 항목 |
|------|
| OSNet 기반 ReID 도입 |
| StrongSORT 비교 실험 |
| YOLOv8s / YOLOv8m 교체 및 성능 비교 |
| 실제 키즈카페 CCTV 데이터 기반 검증 |
| 논문 실험 파이프라인 구성 |

---

## 참고

- MVP 범위 상세: [README.md — MVP 1단계 상태](../README.md)
- 인터페이스 계약: [docs/interfaces.md](interfaces.md)
- 의사결정 기록: [docs/decisions.md](decisions.md)
