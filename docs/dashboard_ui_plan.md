# Phase 1.5 Dashboard UI Plan

## 목표
React mock 기반 운영 대시보드 구현

## 화면 범위
- 실시간 모니터링
- 이벤트 기록 / 통계

## Event Schema v1
필수 필드는 MVP 이벤트 로그와 향후 FastAPI 응답 구조를 맞추기 위한 기준이다.

- `event_id`, `timestamp`, `event_type`, `track_id`, `zone_id`
- `bbox`, `foot_point`, `frame_number`, `video_source`

Dashboard mock UI 확장 필드는 화면 표시를 위한 선택 필드다.

- `event_label`
- `severity`
- `zone_type`

## timestamp 기준
Phase 1.5에서는 Backend API와 동일하게 `HH:MM:SS.mmm` 형식을 사용한다.

예시:

`00:00:10.600`

이는 MVP 파일 영상 기준 시간이며, 실제 운영 시각이 필요한 경우 Phase 2 이후 `created_at` 또는 `occurred_at` 같은 별도 필드로 확장한다.

## API 전환 구조
`MonitoringPage` / `EventsPage`는 mock을 직접 import하지 않고 `eventsApi.ts`를 통해 데이터 호출

향후 FastAPI 연결 시 page/component 코드는 유지하고 `frontend/src/api/eventsApi.ts` 내부 구현만 교체한다.

Phase 2에서는 React가 mock 데이터에서 FastAPI API 데이터로 전환될 예정이다.
React page/component는 Backend 응답 구조를 직접 다루지 않고 `eventsApi.ts`를 통해 화면용 타입을 사용한다.
`DashboardSummary`는 `/summary`, `/status/current`, `/events/recent`를 조합해서 구성한다.
`/status/current`가 아직 없을 수 있으므로 API 실패 fallback을 제공한다.
Phase 2 초기 실시간 갱신은 WebSocket이 아니라 polling 기반으로 준비한다.

## 완료 기준
- React 앱 실행
- mock 기반 2개 화면 구현
- Event 타입 정의
- eventsApi.ts 계층 분리
- Bar Chart 1개 이상 구현
