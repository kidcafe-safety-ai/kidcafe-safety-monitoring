# Dashboard UI Plan

## 목표
React 기반 운영 대시보드 구현

## 화면 범위
- 실시간 모니터링 (MonitoringPage)
- 이벤트 기록 / 통계 (EventsPage)
- Zone 설정 (ZoneSettingsPage) — Phase 2 mock prototype

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

MVP 파일 영상 기준 상대 시각이며, 실제 운영 시각이 필요한 경우 Phase 3 이후 `created_at` 또는 `occurred_at` 확장을 검토한다.

## API 전환 구조 — Phase 2 완료

Phase 1.5에서 계획한 mock → FastAPI 전환이 Phase 2에서 완료됐다.

- `eventsApi.ts` 내부에서 `VITE_API_MODE` 기준으로 mock/API 분기
- `MonitoringPage` / `EventsPage`는 `eventsApi.ts`만 참조하며, 페이지 코드 변경 없이 전환 완료
- `DashboardSummary`는 `/summary`, `/status/current`, `/events/recent`를 조합해서 구성

## Phase 2 Polling 기준

| API | 호출 주기 |
|---|---|
| `GET /status/current` | 2초 |
| `GET /events/recent` | 3초 |
| `GET /summary` | 10초 |

WebSocket은 Phase 2.5 이후 검토한다.

## Zone Settings — mock prototype

ZoneSettingsPage는 Phase 2 기준 mock prototype이다.

> Zone Settings FastAPI 연동은 Phase 3 예정. Phase 2에서는 UI 구조만 제공한다.

- `zoneSettingsMockApi.ts` — Phase 2 mock prototype only. FastAPI 미연동.
- UI에 "Mock Prototype" badge 표시
- zone_type 표현은 Phase 3 안전정책 확정 후 실제 API와 함께 정의한다.

## Phase 2 완료 기준

- [x] React 앱 실행
- [x] VITE_API_MODE 기반 API 연동 전환
- [x] CurrentStatus 타입 NORMAL | HIGH 반영
- [x] loading / error / empty 상태 처리
- [x] ZoneStatusPanel fallback NORMAL
- [x] npm run build 통과
