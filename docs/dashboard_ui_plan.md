# Dashboard UI Plan

## 목표
React 기반 운영 대시보드 구현

## 화면 범위
- 실시간 모니터링 (MonitoringPage)
- 이벤트 기록 / 통계 (EventsPage)
- Zone 설정 (ZoneSettingsPage) — Phase 2.5 Mock Prototype

## Event Schema v1
필수 필드는 MVP 이벤트 로그와 FastAPI 응답 구조를 맞추기 위한 기준이다.

- `event_id`, `timestamp`, `event_type`, `track_id`, `zone_id`
- `bbox`, `foot_point`, `frame_number`, `video_source`

Dashboard 확장 필드는 화면 표시를 위한 선택 필드다.

- `event_label`
- `severity`
- `zone_type`

## timestamp 기준
`HH:MM:SS.mmm` 형식을 사용한다.

예시: `00:00:10.600`

이벤트 `timestamp`는 영상 상대 시각을 유지한다. 오늘 및 최근 이벤트 집계는 SQLite 저장 시각인 `created_at`을 사용한다. 실제 이벤트 발생 시각이 별도로 필요하면 Phase 3 이후 `occurred_at` 추가를 검토한다.

## API 전환 구조 — Phase 2.5 완료

Phase 1.5에서 계획한 mock → FastAPI 전환이 Phase 2에서 완료됐고, Phase 2.5에서 Docker API mode 검증까지 완료됐다.

- `eventsApi.ts` 내부에서 `VITE_API_MODE` 기준으로 mock/API 분기
- `MonitoringPage` / `EventsPage`는 `eventsApi.ts`만 참조하며, 페이지 코드 변경 없이 전환 완료
- `MonitoringPage`는 `DashboardSummary`(`/summary`), `CurrentStatus`(`/status/current`), 최근 이벤트(`/events/recent`)를 각각 독립 polling한다.

## 화면별 현재 상태

| 화면 | 현재 상태 |
|---|---|
| MonitoringPage | 실제 API 연동 |
| EventsPage | 실제 API 연동 |
| AlertHistoryPage | Mock Prototype |
| ReportPage | Mock Prototype |
| ZoneSettingsPage | Mock Prototype |
| SystemSettingsModal | Mock Prototype |
| 영상 영역 | Live View placeholder |

Mock Prototype 화면의 데이터는 서버에 저장되지 않는다.

## Polling 책임 (Phase 2.5 기준)

MonitoringPage에서 각 API를 독립 polling한다.

| API | 담당 데이터 | 호출 주기 |
|---|---|---|
| `GET /summary` | 오늘 이벤트 수 · 최근 10분 이벤트 수 KPI | 10초 |
| `GET /status/current` | 현재 감지 인원 · zone 상태 | 2초 |
| `GET /events/recent?minutes=10&limit=5` | 최근 10분 이벤트 목록 | 3초 |

`recent_event_count`는 목록 길이가 아니라 `/summary`의 `recent_10min_event_count`를 사용한다.

WebSocket은 실시간 push 필요성이 명확해진 이후 재검토한다.

## Zone Settings — mock prototype

ZoneSettingsPage는 mock prototype이다.

> Zone Settings FastAPI 연동은 후속 Phase에서 안전정책 확정 후 검토한다.

- `zoneSettingsMockApi.ts` — mock prototype only. FastAPI 미연동.
- UI에 "Mock Prototype" badge 표시
- zone_type 표현은 Phase 3 안전정책 확정 후 실제 API와 함께 정의한다.

## Docker API mode 검증 완료

- `VITE_API_MODE=api`, `VITE_API_BASE_URL=http://localhost:8000`으로 Docker Compose 실행 확인
- React Dashboard가 Docker FastAPI에서 `/status/current`, `/events/recent`, `/summary`를 정상 호출함을 확인

## Phase 2.5 완료 기준

- [x] React 앱 실행
- [x] VITE_API_MODE 기반 API 연동 전환
- [x] CurrentStatus 타입 NORMAL | HIGH 반영
- [x] loading / error / empty 상태 처리
- [x] ZoneStatusPanel fallback NORMAL
- [x] npm run build 통과
- [x] Docker API mode 실행 및 React Dashboard 연동 확인
