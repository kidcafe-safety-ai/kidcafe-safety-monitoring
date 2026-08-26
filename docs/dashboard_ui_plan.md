# Dashboard UI Plan

## 목표
React 기반 운영 대시보드 구현

## 화면 범위
- 실시간 모니터링 (MonitoringPage)
- 이벤트 기록 / 통계 (EventsPage)
- Zone 설정 (ZoneSettingsPage) — Phase 4 실제 API 저장·충돌 처리 완료
- 기간별 Report (ReportPage) — Phase 4 읽기 전용 실제 Event 연동 완료

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
| AlertHistoryPage | 실제 API 읽기 전용 연동 |
| ReportPage | 실제 기간·pagination Event 연동 |
| ZoneSettingsPage | 실제 Zone 조회·저장·version 충돌 연동 |
| SystemSettingsModal | Mock Prototype |
| 영상 영역 | Live View latest-frame polling 연동 |

SystemSettings의 Mock 데이터는 서버에 저장되지 않는다. API mode의 Report와
ZoneSettings는 Mock으로 자동 전환하지 않는다.

## Polling 책임 (Phase 4 완료 기준)

MonitoringPage에서 각 API를 독립 polling한다.

| API | 담당 데이터 | 호출 주기 |
|---|---|---|
| `GET /summary` | 오늘 이벤트 수 · 최근 10분 이벤트 수 KPI | 10초 |
| `GET /status/current` | 현재 감지 인원 · zone 상태 | 2초 |
| `GET /events/recent?minutes=10&limit=5` | 최근 10분 이벤트 목록 | 3초 |
| `GET /live/frame` | 최신 JPEG live frame | 1초 |

`recent_event_count`는 목록 길이가 아니라 `/summary`의 `recent_10min_event_count`를 사용한다.

Phase 4에서도 REST polling을 유지했다. 중복 요청, stale response, unmount cleanup,
10초 watchdog과 오류 로그 cooldown을 적용했으며 WebSocket은 채택하지 않았다.

## Zone Settings — Phase 4 연동 완료

Phase 3 종료 시점의 mock prototype을 Phase 4에서 실제 API 경로로 전환했다.

> `GET /zones`·`PUT /zones`·version 충돌 계약과 fail-closed 오류 처리는
> `docs/api_contract.md`를 따른다.

- API mode에서 정상 빈 Zone과 조회 실패를 구분한다.
- `sha256:` version token과 `409` 충돌 시 최신 설정 재조회 흐름을 사용한다.
- `422` validation detail과 `500` 저장 실패를 성공 상태로 보정하지 않는다.
- 저장 성공 후 `Vision AI 재시작 후 적용`을 안내한다.

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

---

## Phase 3 구현 상태

> 상태: Phase 3 완료 — Live View, 신규 Event 표시(FALL_SUSPECT/cause 포함),
> AlertHistory 읽기 전용 연동 완료. Report·ZoneSettings·SystemSettings 저장
> 연동은 Phase 4.
> 기준선: `v0.3.0-safety`

### Live View

- `PUT /live/frame` → FastAPI 메모리 보관 → `GET /live/frame` → React 500-1000ms polling
- MonitoringPage 영상 영역 placeholder를 실제 JPEG 표시로 교체 완료
- 204 No Content 수신 시 empty 상태 표시
- 연결 오류·파이프라인 중단 시 error fallback 표시
- object URL 정리 및 polling cleanup 적용
- 담당: A(정종민, frame 제공) → B(원우민, API) → C(정현수, React 표시)

### 신규 EventType·Severity 표시

| EventType | Severity | 표시 |
|---|---|---|
| ENTER_RESTRICTED | HIGH | 제한구역 진입 |
| DANGER_ZONE_DWELL | HIGH | 위험구역 체류 |
| FALL_SUSPECT | HIGH | 낙상 의심 |

- EventsPage·EventChart에 신규 타입 색상·뱃지 추가
- `외부 접촉 의심 · Track #N` 표시 (cause 있는 경우)
- `normalizeEventType()` 수정: 알 수 없는 타입을 `ENTER`로 변환하지 않음
- ZoneType `"slide"` → `"danger"` 교체

### AlertHistory 읽기 전용 연동

- 데이터 소스: 실제 `/events` API
- 발생 시각: `created_at` (UTC → Asia/Seoul 변환)
- `MOCK_TODAY` 하드코딩 제거
- 처리 상태: `미확인` 고정
- `확인중`·`처리완료`·조치 메모 저장 기능: 비활성화 (Phase 4 이후 후속)

### Phase 3 종료 당시 Mock 유지 화면

| 화면 | Phase 3 상태 |
|---|---|
| ReportPage | Mock 유지 |
| ZoneSettingsPage | Mock 유지 |
| SystemSettingsModal | Mock 유지 |

## Phase 4 Frontend 계약과 완료 결과

### Zone Settings

- ZoneSettingsPage는 version 기반 전체 목록 교체와 `409` 충돌 UX를 구현한다.
- 정상 빈 Zone과 조회 오류를 구분하고, 조회 오류 중에는 수정·저장을
  비활성화한다.
- validation 오류, 저장 실패, 저장 성공 상태를 각각 표시한다.
- 저장 성공 후 `Vision AI 재시작 후 적용`을 안내한다.

### Report

- ReportPage는 `created_from`·`created_to`와 전체 pagination을 사용하는
  읽기 전용 화면으로 전환한다.
- Report 조회는 전용 `getEventsPage(params)`를 사용하고 기존 `getEvents()`의
  반환 의미는 유지한다.
- 첫 요청의 `created_to`를 전체 페이지에서 고정하고 한 번에 최대 31일을
  조회한다.
- loading, empty, error와 기간 경계 상태를 구분한다.

### Recent Event

- 기존 Event 표시 metadata를 재사용해 한글명·severity·색상을 통일한다.
- `created_at`을 UTC로 해석한 뒤 Asia/Seoul 발생 시각으로 표시한다.
- Zone 이름, Track ID와 Cause 요약을 함께 표시한다.
- `cause=null`은 `원인 후보 없음`, 후보가 있으면
  `외부 접촉 의심 · Track #N`으로 표시한다.
- 신규 HIGH Event만 짧게 강조하고 `event_id` 기준으로 같은 Event를 반복
  강조하지 않는다.
- `prefers-reduced-motion`, 긴 Zone 이름, 미지 EventType과 모바일 레이아웃을
  지원한다.
- loading, empty, API 오류를 패널 내부에서 처리한다.
- Event 선택 대상은 AlertHistory로 고정한다.

- 읽음·확인·처리 상태는 Backend 계약이 없으므로 임의 생성하지 않는다.
- SystemSettingsModal과 AlertHistory 조치 상태 저장은 후속 범위다.

### 완료 상태 (2026-08-24)

- Zone Settings 실제 조회·저장·409·422·500 처리 완료
- Report 최대 31일·전체 pagination·중복 제거·partial result 차단 완료
- API mode 장애 시 Mock fallback 금지와 응답 계약 fail-closed 적용
- polling 중복·stale response·무한 pending·unmount cleanup 보강
- Seoul 날짜 경계, Event 표시, Report 집계, Zone validation 회귀 테스트 추가
- Frontend 전체 테스트 48개와 production build 통과

상세 일정과 인수 기준은 `docs/roadmap.md`, `docs/api_contract.md`를 따른다.
