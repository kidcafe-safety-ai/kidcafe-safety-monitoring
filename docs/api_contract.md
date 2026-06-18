# API Contract v1

> **작성일**: 2026-06-04  
> **작성자**: 우민 (B / Backend FastAPI 담당)  
> **상태**: Phase 1.5 구현 완료 + Phase 2 Current Status API 구현 반영
> **관련 문서**: [`dashboard_api.md`](dashboard_api.md), [`dashboard_analysis.md`](dashboard_analysis.md), [`interfaces.md`](interfaces.md), [`decisions.md`](decisions.md), [`roadmap.md`](roadmap.md)

이 문서는 Phase 1.5에서 구현된 Backend API와 Phase 2에서 추가할 Current Status API 계약을 정리한다.

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

FastAPI/Pydantic validation error는 기본 `422` 응답 형식을 그대로 사용한다.
이번 문서 기준으로 `RequestValidationError` 공통 handler는 아직 추가하지 않는다.

---

## Event Schema v1

`POST /events` 요청은 기존 `src/common/types.py`의 `Event` dataclass와 호환되는 필드를 기준으로 한다.
API 계층에서는 별도 Pydantic schema로 매핑하며, 기존 Event dataclass는 수정하지 않는다.

### Required Fields

| Field | Type | Description |
| --- | --- | --- |
| `event_id` | `string` | 이벤트 UUID 또는 고유 ID |
| `timestamp` | `string` | 영상 내 상대 시각, `HH:MM:SS.mmm` |
| `event_type` | `"ENTER" | "DWELL" | "EXIT"` | 이벤트 종류 |
| `track_id` | `integer` | 사람 추적 ID |
| `zone_id` | `string` | zone 식별자 |
| `bbox` | `number[4]` | `[x1, y1, x2, y2]` pixel 좌표 |
| `foot_point` | `number[2]` | `[cx, y2]` pixel 좌표 |
| `frame_number` | `integer` | 이벤트 발생 프레임 번호 |
| `video_source` | `string` | 입력 영상 경로 또는 소스 ID |

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

`risk_level`은 Phase 2에서 `NORMAL | HIGH`만 허용한다.
`LOW | MEDIUM | HIGH`처럼 세분화된 위험도는 Phase 2.5 또는 Phase 3에서 검토한다.

`PUT /status/current` 요청 body에 `updated_at`이 있으면 그대로 저장한다.
`updated_at`이 없으면 Backend 수신 시각을 timezone-aware ISO 문자열로 생성해 저장한다.
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

### Phase 2

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

이벤트 목록을 조회한다. 기본 정렬은 `id DESC` 최신순이다.

### Query Parameters

| Parameter | Type | Default | Constraint |
| --- | --- | --- | --- |
| `limit` | `integer` | `50` | `1 <= limit <= 500` |
| `offset` | `integer` | `0` | `offset >= 0` |
| `event_type` | `string | null` | `null` | `ENTER`, `DWELL`, `EXIT`만 허용 |
| `zone_id` | `string | null` | `null` | zone ID 필터 |

`total`은 필터 적용 후, `limit`/`offset` pagination 적용 전 전체 개수다.

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

---

## GET /events/recent

최신 이벤트를 `id DESC` 기준으로 조회한다.

### Query Parameters

| Parameter | Type | Default | Constraint |
| --- | --- | --- | --- |
| `limit` | `integer` | `10` | `1 <= limit <= 100` |

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

### Response

```json
{
  "status": "success",
  "data": {
    "total_events": 3,
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

## GET /zones

`data/zones/sample.json`을 읽어 반환한다. 파일이 없거나 형식이 맞지 않으면 빈 리스트를 반환할 수 있다.
API 응답에서는 `zone_name`을 보장한다.
전환기 호환성을 위해 기존 `name` 필드는 제거하지 않는다.

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

WebSocket은 Phase 2에서 제외하고 Phase 2.5 이후 검토한다.

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
