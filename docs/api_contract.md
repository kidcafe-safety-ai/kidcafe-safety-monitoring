# API Contract v1

> **작성일**: 2026-06-04  
> **작성자**: 우민 (B / Backend FastAPI 담당)  
> **최종 수정**: 2026-10-12 (Final Phase 입력 검증·CurrentStatus 최신 판단·DB 재생성 반영)
> **상태**: Phase 4 기간 조회·Zone 저장·Frontend 연동 구현 완료,
> Backend·DB·RTSP 설정 동결
> **관련 문서**: [`interfaces.md`](interfaces.md),
> [`fall_evaluation.md`](fall_evaluation.md), [`decisions.md`](decisions.md),
> [`roadmap.md`](roadmap.md)

이 문서는 Phase 1.5-2.5의 기본 API, Phase 3 Live Frame·Event/Zone 공용 계약과
Phase 4 기간 조회·Zone 저장 구현 및 동결 결과를 구분해 정리한다.

---

## Common Response

성공 응답은 공통적으로 다음 구조를 따른다.

```json
{
  "status": "success",
  "data": {},
  "message": null
}
```

중복 `event_id` 같은 명시적 API 오류는 다음 구조를 따른다.

```json
{
  "status": "error",
  "data": null,
  "message": "event_id already exists"
}
```

FastAPI/Pydantic validation error는 기본 `422` 응답 형식(`{"detail": [...]}`)을
그대로 사용한다. Final Phase에서 `RequestValidationError` handler를 추가했지만
형식은 바꾸지 않는다. 요청 값에 `NaN`·`Infinity`가 있으면 기본 handler가
`detail[].input`을 JSON으로 직렬화하지 못해 500이 나가므로, 그 값만 문자열
(`"nan"`, `"inf"`)로 바꿔 `422`를 보장한다.

`GET /live/frame`은 binary endpoint이므로 위 공통 JSON wrapper의 예외다. `200`은 `image/jpeg` body를 그대로 반환하고, `204`는 body 없이 반환한다.

---

## Event Schema v1

`POST /events` 요청은 기존 `src/common/types.py`의 `Event` dataclass와 호환되는 필드를 기준으로 한다.
API 계층에서는 별도 Pydantic schema로 매핑하며, 기존 Event dataclass는 수정하지 않는다.

### Required Fields

| Field | Type | Description |
| --- | --- | --- |
| `event_id` | `string` | 이벤트 UUID 또는 고유 ID, 빈 문자열 불가 |
| `timestamp` | `string` | 영상 내 상대 시각, `HH:MM:SS.mmm` |
| `event_type` | `EventType` | 이벤트 종류. 아래 Phase 3 활성 값 중 하나 |
| `track_id` | `integer` | 사람 추적 ID |
| `zone_id` | `string` | zone 식별자, 빈 문자열 불가 (낙상은 `__global__`) |
| `bbox` | `number[4]` | `[x1, y1, x2, y2]` pixel 좌표, 유한한 값 |
| `foot_point` | `number[2]` | `[cx, y2]` pixel 좌표, 유한한 값 |
| `frame_number` | `integer` | 이벤트 발생 프레임 번호, `>= 0` |
| `video_source` | `string` | 입력 영상 경로 또는 소스 ID, 빈 문자열 불가 |

모든 number 입력(`bbox`, `foot_point`, `confidence`, `event_confidence`,
`cause.score`, `cause.evidence.*`)은 `NaN`·`Infinity`를 받지 않고 `422`를
반환한다 (Final Phase). Python `json`은 이 값을 읽어들이기 때문에 저장되면
조회 응답 직렬화가 실패해 `GET /events`·`/events/recent` 전체가 500이 된다.
Vision AI의 `AsyncEventDispatcher`는 `422`를 실패로 보고
`outputs/api_failed_events.jsonl`에 남긴다.

Phase 3 활성 `EventType`은 `ENTER`, `DWELL`, `EXIT`, `ENTER_RESTRICTED`,
`DANGER_ZONE_DWELL`, `FALL_SUSPECT`다. 기존 세 타입은 그대로 유지한다.

### Optional API/DB Fields

| Field | Type | Description |
| --- | --- | --- |
| `id` | `integer` | SQLite autoincrement PK |
| `zone_name` | `string | null` | zone 표시 이름 |
| `video_time_sec` | `number | null` | `timestamp`에서 계산한 초 단위 영상 시각 |
| `confidence` | `number | null` | detector/tracker confidence, `0.0 <= confidence <= 1.0` |
| `created_at` | `string` | SQLite 저장 시각, `CURRENT_TIMESTAMP` 형식 |

### Timestamp Validation

`timestamp`는 정규식 `^\d{2}:[0-5]\d:[0-5]\d\.\d{3}$` 기준으로 검증한다.

허용 예:

```text
00:00:10.600
```

거부 예:

```text
10.6
00:00:10
00:99:00.000
```

저장 시 `video_time_sec`를 계산한다.

```text
00:00:10.600 -> 10.6
```

잘못된 timestamp를 `video_time_sec = 0.0`으로 조용히 저장하지 않는다.

---

## Current Status Schema

`/status/current`는 Event 누적 로그가 아니라 현재 프레임 기준 최신 상태를 표현한다.
Event는 `events` 테이블에 누적 저장하고, Current Status는 `source`별 최신 상태만 유지한다.

### Fields

| Field | Type | Description |
| --- | --- | --- |
| `source` | `string` | 입력 소스 ID 또는 카메라 ID |
| `frame_number` | `integer` | 현재 상태 기준 프레임 번호, `>= 0` |
| `active_track_count` | `integer` | 현재 감지 중인 track 수, `>= 0` |
| `zone_occupancy` | `array` | zone별 현재 점유 상태 |
| `zone_occupancy[].zone_id` | `string` | zone ID |
| `zone_occupancy[].zone_name` | `string | null` | zone 표시 이름 |
| `zone_occupancy[].current_count` | `integer` | 해당 zone의 현재 track 수, `>= 0` |
| `zone_occupancy[].risk_level` | `"NORMAL" | "HIGH"` | Phase 2 현재 위험도 |
| `updated_at` | `string | null` | current status 갱신 시각 |

Phase 3에서도 `CurrentStatus.risk_level`은 `NORMAL | HIGH`를 유지한다.
`LOW | MEDIUM | HIGH`는 `risk_level`의 확장이 아니라 Frontend `SafetyEvent.severity` 파생 표시값이다 (`docs/interfaces.md` Severity 정책 참조).

`PUT /status/current` 요청 body에 `updated_at`이 있으면 그대로 저장한다.
단, timezone을 포함한 ISO 8601이어야 한다(`2026-10-12T10:00:00+09:00`,
`2026-10-12T01:00:00Z`). 날짜가 아니거나 timezone이 없으면 `422`다 (Final Phase).
`updated_at`이 없으면 Backend 수신 시각을 timezone-aware ISO 문자열로 생성해 저장한다.
`GET /status/current`는 source별 row 중 `updated_at`이 가장 늦은 row를 반환한다.
source마다 offset이 달라도 맞게 고르도록 문자열이 아니라 SQLite
`julianday(updated_at)`로 비교한다 (Final Phase). 이전에 저장된, 파싱할 수 없는
`updated_at` row는 가장 뒤로 밀린다. 영상 전환·playlist처럼 source가 바뀌면 이전
source row는 남아 있지만 새 source가 최신이므로 응답에 영향을 주지 않는다.
실행 종료 시 Vision AI가 `active_track_count=0`, 각 Zone `current_count=0`으로
보내면 그 값이 최신 상태가 된다.
저장된 current status가 하나도 없는 경우에만 `GET /status/current`에서 `updated_at: null`을 반환한다.
이 기준은 `current_status.updated_at`에만 적용하며, 기존 `events.created_at`은 SQLite `CURRENT_TIMESTAMP`를 유지한다.

---

## API List

### Phase 1.5 (구현 완료)

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/health` | API health check |
| `POST` | `/events` | 이벤트 저장 |
| `GET` | `/events` | 이벤트 목록 조회 |
| `GET` | `/events/recent` | 최신 이벤트 조회 |
| `GET` | `/summary` | 이벤트 KPI summary 조회 |
| `GET` | `/zones` | zone 목록 조회 |

### Phase 2 (구현 완료)

| Method | Path | Description |
| --- | --- | --- |
| `PUT` | `/status/current` | Vision AI 현재 감지 상태 저장/갱신 |
| `GET` | `/status/current` | 현재 감지 상태 조회 |

`/status/current`는 Event 누적 로그가 아니라 현재 상태만 저장한다.

---

## GET /health

### Response

```json
{
  "status": "success",
  "data": {
    "service": "kidcafe-api",
    "healthy": true
  },
  "message": null
}
```

---

## POST /events

이벤트를 SQLite `events` 테이블에 저장한다.

### Request

```json
{
  "event_id": "event-001",
  "timestamp": "00:00:10.600",
  "event_type": "ENTER",
  "track_id": 7,
  "zone_id": "playground_bottom_right",
  "zone_name": "test video zone",
  "bbox": [10.0, 20.0, 110.0, 220.0],
  "foot_point": [60.0, 220.0],
  "frame_number": 318,
  "confidence": 0.91,
  "video_source": "data/videos/test.mp4"
}
```

### Success Response

성공 시 `201 Created`를 반환한다.

```json
{
  "status": "success",
  "data": {
    "id": 1,
    "event_id": "event-001",
    "timestamp": "00:00:10.600",
    "event_type": "ENTER",
    "track_id": 7,
    "zone_id": "playground_bottom_right",
    "zone_name": "test video zone",
    "bbox": [10.0, 20.0, 110.0, 220.0],
    "foot_point": [60.0, 220.0],
    "frame_number": 318,
    "video_time_sec": 10.6,
    "confidence": 0.91,
    "video_source": "data/videos/test.mp4",
    "created_at": "2026-06-03 12:00:00"
  },
  "message": null
}
```

### Duplicate event_id

이미 존재하는 `event_id`가 들어오면 `409 Conflict`를 반환한다.
`INSERT OR IGNORE`로 조용히 무시하지 않는다.

```json
{
  "status": "error",
  "data": null,
  "message": "event_id already exists"
}
```

---

## GET /events

이벤트 목록을 조회한다. Phase 4에서는 기간 필터를 하위 호환 방식으로
추가하며, 기본 정렬은 `created_at DESC`, 내부 SQLite `id DESC`다.

### Query Parameters

| Parameter | Type | Default | Constraint |
| --- | --- | --- | --- |
| `limit` | `integer` | `50` | `1 <= limit <= 500` |
| `offset` | `integer` | `0` | `offset >= 0` |
| `event_type` | `string | null` | `null` | Phase 3 활성 `EventType` 6종 중 하나 |
| `zone_id` | `string | null` | `null` | zone ID 필터 |
| `created_from` | RFC 3339 datetime 또는 `null` | `null` | 저장 시각 시작, 포함 |
| `created_to` | RFC 3339 datetime 또는 `null` | `null` | 저장 시각 종료, 미포함 |

`total`은 필터 적용 후, `limit`/`offset` pagination 적용 전 전체 개수다.
기간 입력은 timezone을 포함해야 하며 UTC로 변환해 SQLite `created_at`과
비교한다. `created_from < created_to`여야 하고, 잘못된 datetime·timezone
누락·역전된 범위는 기존 FastAPI/Pydantic `422 detail` 형식으로 반환한다.
영상 상대 시각 `timestamp`는 기간 조회에 사용하지 않는다.

### Response

```json
{
  "status": "success",
  "data": {
    "items": [
      {
        "id": 3,
        "event_id": "event-003",
        "timestamp": "00:00:12.000",
        "event_type": "EXIT",
        "track_id": 7,
        "zone_id": "playground_bottom_right",
        "zone_name": null,
        "bbox": [12.0, 21.0, 111.0, 221.0],
        "foot_point": [61.5, 221.0],
        "frame_number": 360,
        "video_time_sec": 12.0,
        "confidence": null,
        "video_source": "data/videos/test.mp4",
        "created_at": "2026-06-03 12:00:00"
      }
    ],
    "total": 1,
    "limit": 50,
    "offset": 0,
    "count": 1
  },
  "message": null
}
```

### Phase 4 Report 사용

- C는 pagination envelope를 보존하는 `getEventsPage(params)`를 추가한다.
- 기존 `getEvents()`의 반환 의미는 변경하지 않는다.
- `total`, `limit`, `offset`으로 선택 기간 전체 페이지를 조회한다.
- 현재 시각을 포함하는 기간은 첫 요청의 `created_to`를 고정하고 모든
  페이지에서 같은 값을 사용한다.
- Phase 4 UI는 한 번에 최대 31일을 조회한다.
- EventType·Zone별 집계는 Frontend에서 수행한다.
- 기존 `/summary`는 현재 KPI용이며 과거 기간 Report 집계에 사용하지 않는다.

---

## GET /events/recent

최신 이벤트를 조회한다. `minutes`가 없으면 기존과 같이 시간 제한 없이
`id DESC` 기준으로 조회한다. `minutes`가 있으면 Backend 현재 UTC 시각을
기준으로 최근 N분 동안 저장된 이벤트만 조회한다.

시간 필터는 영상 내부 상대 시각인 `event.timestamp`가 아니라 UTC
`YYYY-MM-DD HH:MM:SS` 형식의 `events.created_at`에 적용한다. 범위는
`created_at >= cutoff_utc AND created_at <= now_utc`이며, 미래 시각의 이벤트는
제외한다. 필터 결과는 `created_at DESC, id DESC`로 정렬한 후 `limit`을 적용한다.

### Query Parameters

| Parameter | Type | Default | Constraint |
| --- | --- | --- | --- |
| `limit` | `integer` | `10` | `1 <= limit <= 100` |
| `minutes` | `integer` | 없음 | 선택 사항, `1 <= minutes <= 1440` |

예: `GET /events/recent?minutes=10&limit=5`

### Response

```json
{
  "status": "success",
  "data": [
    {
      "id": 3,
      "event_id": "event-003",
      "timestamp": "00:00:12.000",
      "event_type": "EXIT",
      "track_id": 7,
      "zone_id": "playground_bottom_right",
      "zone_name": null,
      "bbox": [12.0, 21.0, 111.0, 221.0],
      "foot_point": [61.5, 221.0],
      "frame_number": 360,
      "video_time_sec": 12.0,
      "confidence": null,
      "video_source": "data/videos/test.mp4",
      "created_at": "2026-06-03 12:00:00"
    }
  ],
  "message": null
}
```

---

## GET /summary

이벤트 KPI summary를 반환한다.

Phase 1.5에서는 DB에 dwell duration을 저장하지 않으므로 `avg_dwell_seconds`는 `0.0`으로 반환한다.
ENTER/EXIT 매칭 기반 평균 체류시간 계산은 이번 작업 범위에 포함하지 않는다.

- `total_events`는 기간 제한이 없는 전체 누적 이벤트 수다. 기존 의미를 유지한다.
- `today_event_count`는 `Asia/Seoul` 기준 오늘 저장된 이벤트 수다.
- `recent_10min_event_count`는 Backend 현재 시각 기준 최근 10분 동안 저장된 전체 이벤트 수다.
- 오늘 집계는 영상 내부 상대 시각인 `event.timestamp`가 아니라 `events.created_at`을 사용한다.
- 최근 10분 집계도 `events.created_at`을 사용하며, 정확히 10분 전은 포함하고 미래 시각은 제외한다.
- `created_at`은 SQLite `CURRENT_TIMESTAMP`가 저장한 UTC `YYYY-MM-DD HH:MM:SS` 형식이며, 조회 경계도 같은 형식으로 비교한다.
- 조회 범위는 서울 기준 오늘 시작 시각 이상, 내일 시작 시각 미만이다.
- Frontend는 `today_event_count`가 없거나 집계에 실패했을 때 `total_events` 또는 임의의 `0`으로 대체하지 않는다.
- Frontend는 `recent_10min_event_count`가 없거나 집계에 실패했을 때 최대 5건인 최근 목록 길이 또는 임의의 `0`으로 대체하지 않는다.

### Response

```json
{
  "status": "success",
  "data": {
    "total_events": 3,
    "today_event_count": 2,
    "recent_10min_event_count": 1,
    "enter_count": 1,
    "dwell_count": 1,
    "exit_count": 1,
    "total_tracks": 2,
    "video_count": 2,
    "avg_dwell_seconds": 0.0
  },
  "message": null
}
```

---

## PUT /status/current

Vision AI 파이프라인이 현재 프레임 기준 감지 상태를 저장/갱신한다.
이 API는 이벤트 로그를 누적 저장하지 않고, `source`별 current status 최신값만 덮어쓴다.

### Request

```json
{
  "source": "camera_01",
  "frame_number": 1230,
  "active_track_count": 4,
  "zone_occupancy": [
    {
      "zone_id": "playground_bottom_right",
      "zone_name": "test video zone",
      "current_count": 2,
      "risk_level": "HIGH"
    }
  ],
  "updated_at": "2026-06-08T10:15:30+09:00"
}
```

`updated_at`은 요청 body에 있으면 그대로 저장한다.
요청 body에 없으면 Backend가 수신 시각 기준 timezone-aware ISO 문자열을 생성해 저장한다.

### Response

```json
{
  "status": "success",
  "data": {
    "source": "camera_01",
    "updated": true
  },
  "message": null
}
```

---

## GET /status/current

가장 최근에 저장된 current status를 조회한다.
저장된 current status가 하나도 없으면 error가 아니라 기본값을 반환한다.

### Response

```json
{
  "status": "success",
  "data": {
    "source": "camera_01",
    "frame_number": 1230,
    "active_track_count": 4,
    "zone_occupancy": [
      {
        "zone_id": "playground_bottom_right",
        "zone_name": "test video zone",
        "current_count": 2,
        "risk_level": "HIGH"
      }
    ],
    "updated_at": "2026-06-08T10:15:30+09:00"
  },
  "message": null
}
```

### Empty State Response

```json
{
  "status": "success",
  "data": {
    "source": "unknown",
    "frame_number": 0,
    "active_track_count": 0,
    "zone_occupancy": [],
    "updated_at": null
  },
  "message": null
}
```

---

## GET /zones (Phase 3 역사적 기준선)

`data/zones/sample.json`을 읽어 반환한다. 파일이 없거나 형식이 맞지 않으면 빈 리스트를 반환할 수 있다.
API 응답에서는 `zone_name`을 보장한다.
전환기 호환성을 위해 기존 `name` 필드는 제거하지 않는다.

이 동작은 Phase 3 기준선이며 현재 경로가 아니다. Phase 4에서 아래
`GET /zones Phase 4 계약`의 version envelope와 오류 정책으로 전환했다.

### Response

```json
{
  "status": "success",
  "data": [
    {
      "zone_id": "playground_bottom_right",
      "name": "test video zone",
      "zone_name": "test video zone",
      "type": "polygon",
      "points": [
        [0.65, 0.65],
        [1, 0.65],
        [1, 1],
        [0.65, 1]
      ],
      "rules": {
        "enter_alert": true,
        "dwell_threshold_sec": 5
      }
    }
  ],
  "message": null
}
```

---

## SQLite

기본 DB 경로는 프로젝트 루트 기준 `outputs/kidcafe_events.db`다.
환경변수 `KIDCAFE_DB_PATH`가 있으면 해당 경로를 사용한다.
DB 경로는 모듈 import 시점이 아니라 connection 생성 또는 `init_db` 실행 시점에 읽는다.
connection을 열 때 DB 파일이 없으면 아래 schema를 다시 만든다 (Final Phase). API
실행 중 DB 파일을 지우거나 `outputs/`를 비워도 재시작 없이 빈 DB로 계속 동작한다.
백업·복원·초기화 절차는 [`backend_final.md`](backend_final.md)를 따른다.

`events` 테이블:

```sql
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    event_type TEXT NOT NULL,
    track_id INTEGER NOT NULL,
    zone_id TEXT NOT NULL,
    zone_name TEXT,
    frame_number INTEGER NOT NULL,
    video_time_sec REAL,
    timestamp TEXT NOT NULL,
    bbox_json TEXT NOT NULL,
    foot_point_json TEXT NOT NULL,
    confidence REAL,
    video_source TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
```

`current_status` 테이블:

```sql
CREATE TABLE IF NOT EXISTS current_status (
    source TEXT PRIMARY KEY,
    frame_number INTEGER NOT NULL,
    active_track_count INTEGER NOT NULL,
    zone_occupancy_json TEXT NOT NULL,
    updated_at TEXT
);
```

`current_status`는 Event처럼 누적 저장하지 않는다.
같은 `source`로 `PUT /status/current` 요청이 들어오면 기존 row를 덮어쓴다.
`zone_occupancy`는 SQLite에는 JSON 문자열로 저장하고 API 응답에서는 배열로 반환한다.

---

## CORS

React 개발 서버 연동을 위해 최소 다음 origin을 허용한다.

- `http://localhost:3000`
- `http://localhost:5173`
- `http://127.0.0.1:3000`
- `http://127.0.0.1:5173`

---

## Phase 2 React Polling 기준

C 역할은 WebSocket 대신 polling으로 실시간성을 확보한다.

| API | 호출 주기 |
| --- | --- |
| `GET /status/current` | 2초 |
| `GET /events/recent` | 3초 |
| `GET /summary` | 10초 |
| `GET /events` | 페이지 진입 또는 필터 변경 시 |

Phase 4에서도 REST polling을 유지하고 WebSocket은 미채택했다.

---

## Phase 1.5 Out of Scope

다음 항목은 Phase 1.5 B 역할에 포함하지 않는다.

- 기존 Vision AI 파이프라인 변경
- WebSocket
- 인증/권한
- 알림
- PostgreSQL 전환
- SQLAlchemy, Alembic 기반 migration 계층
- React 구현
- ReID
- cross-camera
- 낙상 감지
- 충돌 감지

## Phase 2 Out of Scope

- WebSocket 완성
- 인증/권한
- 알림 push
- PostgreSQL 전환
- 복잡한 관리자 기능

---

## Phase 3 계약

> 상태: Live Frame API 구현 완료 / Event Schema v2·ZoneType·SQLite migration 구현 완료 / 공간 안전정책 및 FALL_SUSPECT opt-in PoC·원인 후보 추정 구현 완료
> 기준선: v0.3.0-safety
> 적용 시점: 아래 각 계약은 해당 구현 PR 머지 이후 적용됨

---

## PUT /live/frame

Vision AI 파이프라인이 최신 JPEG 프레임을 업로드한다.

```http
PUT /live/frame?source=webcam%3A0&frame_number=100&captured_at=2026-07-07T12:00:00Z
Content-Type: image/jpeg

<JPEG binary>
```

**Query Parameters**

| 파라미터 | 타입 | 설명 |
|---|---|---|
| `source` | string | 영상 소스 식별자 |
| `frame_number` | int | 원본 파이프라인 frame 번호 |
| `captured_at` | string | ISO 8601 UTC |

**제약**

- Body: JPEG binary
- Content-Type: `image/jpeg`
- 최대 크기: 1 MiB
- 업로드 주기: 1-2 FPS
- 해상도: 640×480, JPEG quality 70-80

**응답**

```json
{
  "status": "success",
  "data": { "source": "webcam:0", "frame_number": 100, "stored": true },
  "message": null
}
```

오류:
- `415 Unsupported Media Type`: JPEG가 아닌 경우
- `413 Payload Too Large`: 1 MiB 초과
- `422 Unprocessable Entity`: metadata 오류

**저장 원칙**

- 최신 JPEG 1장만 Process Memory에 보관
- DB·파일 영속 저장 없음
- frame 교체·조회는 lock으로 보호
- stale 판정은 서버 수신 monotonic time 기준

---

## GET /live/frame

최신 JPEG 프레임을 조회한다.

```http
GET /live/frame
```

**응답**

| 조건 | 응답 |
|---|---|
| 최신 frame 있음 | `200 image/jpeg` |
| frame 없음 | `204 No Content` |
| 서버 수신 기준 3초 이상 미갱신 | `204 No Content` |

헤더:
- `Cache-Control: no-store`
- `X-Source`, `X-Frame-Number`, `X-Captured-At`

React: 204 수신 시 placeholder 표시, 파이프라인 중단 시 fallback 유지

---

## Event Schema v2 (Phase 3 확장)

> 상태: 구현 완료 (`src/common/types.py`, `src/api/schemas.py`, `src/api/repositories.py`)

기존 Event 필드를 유지하고 optional 필드를 추가한다.

**Phase 3 활성 EventType**

```text
ENTER
DWELL
EXIT
ENTER_RESTRICTED
DANGER_ZONE_DWELL
FALL_SUSPECT
```

```json
{
  "event_id": "...",
  "timestamp": "HH:MM:SS.mmm",
  "event_type": "FALL_SUSPECT",
  "track_id": 3,
  "zone_id": "__global__",
  "bbox": [100.0, 50.0, 200.0, 300.0],
  "foot_point": [150.0, 300.0],
  "frame_number": 100,
  "video_source": "webcam:0",
  "confidence": 0.91,
  "event_confidence": 0.82,
  "cause": {
    "type": "NEARBY_TRACK",
    "track_id": 7,
    "score": 0.68,
    "evidence": {
      "min_distance_norm": 0.31,
      "closing_speed_norm": 0.74,
      "time_to_fall_sec": 0.42
    }
  }
}
```

- `confidence`: optional (기존 DB 행은 null 허용)
- `event_confidence`: optional, 0.0-1.0 또는 null
- `cause`: optional, 전체 객체 또는 null (부분 객체 불허)
- 외부 접촉 근거가 충분하면 `FALL_SUSPECT.cause`에 `NEARBY_TRACK` 후보를
  기록하고, 근거가 부족하거나 attribution이 비활성화되면 `cause=null`을 기록한다.

**EventCause 검증 범위** (상세 규칙은 `docs/interfaces.md`의 EventCause 검증 규칙 참조)

```text
cause.type: "NEARBY_TRACK"
cause.track_id: 0 이상의 정수
cause.score: 0.0-1.0
cause.evidence.min_distance_norm / closing_speed_norm / time_to_fall_sec: 0 이상의 실수
```

- 위 범위를 벗어나거나 `cause`가 일부 필드만 포함한 부분 객체인 경우 `422 Unprocessable Entity`
- `event_confidence`가 `0.0-1.0` 범위를 벗어나면 `422 Unprocessable Entity`

---

## SQLite Migration (Phase 3)

> 상태: 구현 완료 (`src/api/database.py`의 `_migrate_events_table`)

기존 DB에 nullable 컬럼을 추가한다.

```sql
event_confidence REAL NULL
cause_json TEXT NULL
```

idempotent migration 방식:

```sql
-- PRAGMA table_info(events)로 컬럼 존재 여부 확인 후
ALTER TABLE events ADD COLUMN event_confidence REAL;
ALTER TABLE events ADD COLUMN cause_json TEXT;
```

원칙:
- 여러 번 실행해도 안전
- 기존 행은 두 필드 모두 NULL
- 기존 DB 파일 자동 삭제·초기화 없음
- migration 실패 시 서버 시작 오류 명확하게 출력

---

## Summary 신규 이벤트 집계

> 상태: 구현 완료 (`src/api/repositories.py`의 `get_summary`)

Phase 3 신규 EventType의 Summary 집계 기준:

| 카운터 | 포함 EventType |
|---|---|
| `today_event_count` | 모든 이벤트 |
| `recent_10min_event_count` | 모든 이벤트 |
| `enter_count` | `ENTER`, `ENTER_RESTRICTED` |
| `dwell_count` | `DWELL`, `DANGER_ZONE_DWELL` |
| `exit_count` | `EXIT` |
| `FALL_SUSPECT` | 전체 집계에 포함, 전용 KPI는 Phase 4 검토 |

---

## GET /zones Phase 4 계약

> 상태: Phase 4 구현·회귀 검증 완료

Phase 4에서는 기존 list-only `data`를 version이 포함된 설정 envelope로
변경한다.

```json
{
  "status": "success",
  "data": {
    "version": "sha256:<64자리 lowercase hex>",
    "updated_at": "2026-08-07T10:30:00Z",
    "zones": [
      {
        "zone_id": "playground_bottom_right",
        "zone_name": "test video zone",
        "zone_type": "danger",
        "type": "polygon",
        "points": [[0.65, 0.65], [1.0, 0.65], [1.0, 1.0], [0.65, 1.0]],
        "rules": { "enter_alert": true, "dwell_threshold_sec": 5 }
      }
    ]
  },
  "message": null
}
```

- 내부 JSON `name` → API 응답 `zone_name`으로 변환
- `zone_type`: `play | exit | restricted | danger`
- version은 현재 runtime 파일 bytes의 SHA-256 opaque token
- version 형식은 `sha256:<64자리 lowercase hex>`
- `updated_at`은 runtime 파일 최종 변경 시각의 UTC RFC 3339 값
- 유효한 빈 파일만 `zones=[]` 성공
- 파일 누락·읽기 실패·JSON 또는 schema 오류는 generic envelope `500`
- 오류를 빈 Zone이나 Mock 데이터로 대체하지 않음

```json
{
  "status": "error",
  "data": null,
  "message": "zone configuration is unavailable"
}
```

**`name` / `zone_name` 호환성 원칙**

- `zone_name`을 표준 필드로 사용한다.
- runtime 내부 JSON은 기존 `name`을 유지한다.
- API request·response는 `zone_name`을 사용한다.

---

## PUT /zones Phase 4 저장 계약

> 상태: Phase 4 구현·회귀 검증 완료

```json
{
  "expected_version": "sha256:<64자리 lowercase hex>",
  "zones": [
    {
      "zone_id": "danger_door",
      "zone_name": "출입문 위험구역",
      "type": "polygon",
      "zone_type": "danger",
      "points": [[0.1, 0.2], [0.3, 0.2], [0.3, 0.5]],
      "rules": {
        "enter_alert": true,
        "dwell_threshold_sec": 5
      }
    }
  ]
}
```

- `PUT /zones`는 전체 Zone 목록을 교체한다.
- request는 `expected_version`과 전체 `zones`를 포함한다.
- 일부 Zone만 보내면 누락한 Zone은 삭제 대상으로 해석한다.
- `zone_id`와 `zone_name`은 비어 있지 않아야 하고 `zone_id`는 고유해야 한다.
- `type`은 `polygon`, `zone_type`은 `play | exit | restricted | danger`다.
- image Zone point는 0.0-1.0 범위이며 최소 3개다.
- polygon은 첫 점을 끝에 반복하지 않는 open ring으로 저장한다.
- NaN·Infinity·중복 점·면적 0·self-intersection polygon을 거부한다.
- `enter_alert`는 boolean, `dwell_threshold_sec`은 0-3600 정수다.
- version 확인, 검증, 임시 파일 작성, `os.replace()`를 하나의 lock 임계
  구역에서 수행한다.
- version 불일치는 `409`, schema·polygon 오류는 기본 `422`, 저장 실패는
  generic envelope `500`이다.
- Phase 4 운영 기준은 단일 Backend process다.
- seed `data/zones/sample.json`은 읽기 전용이다.
- mutable runtime은 `outputs/zones_runtime.json`, Docker에서는
  `/app/outputs/zones_runtime.json`을 사용한다.
- runtime 경로는 `KIDCAFE_ZONES_PATH`로 변경할 수 있다.
- 최초 실행 전에 setup 단계가 seed를 runtime으로 복사하며 API는 누락 파일을
  자동 생성하지 않는다.
- Vision AI의 `--zones` 기본값은 기존 단독 실행과의 하위 호환을 위해
  `data/zones/sample.json`을 유지한다.
- Phase 4 통합 실행에서는 Vision AI에
  `--zones outputs/zones_runtime.json`을 명시하고 저장 후 재시작해 반영한다.
- Docker Backend의 `KIDCAFE_ZONES_PATH=/app/outputs/zones_runtime.json`과
  host Vision AI의 `outputs/zones_runtime.json`은 같은 volume 파일이어야 한다.

성공 응답은 `GET /zones`와 같은 `version`, `updated_at`, `zones` envelope다.
`409`가 발생하면 Frontend는 자동 덮어쓰지 않고 최신 설정을 재조회한 뒤
사용자에게 다시 확인받는다. API 저장 성공 후 화면에는
`Vision AI 재시작 후 적용`을 표시한다.

평가 artifact와 fixture 필드는 `docs/interfaces.md`, 촬영 데이터 필드는
`docs/data_sources.md`를 따른다.

---

## AlertHistory 읽기 전용 연동 (Phase 3)

- 발생 시각: 영상 상대 시각 `timestamp` 대신 API `created_at` 사용
- `created_at`: UTC 해석 → 화면에서 Asia/Seoul 변환
- `MOCK_TODAY` 하드코딩 제거, 실제 현재 날짜 사용
- `alert_id`: `event_id` 사용
- `target`: `Track #N` 형식
- `title`·`message`·`severity`: `event_type` 기반 Frontend 매핑
- 처리 상태: Phase 3에서 `미확인` 고정
- `확인중`·`처리완료`·조치 메모 저장: Phase 4 이후 후속 범위
- 실제 이벤트와 Mock 처리 상태 혼용 금지
