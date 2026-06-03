# API Contract v1

KidCafe Safety AI Phase 1.5 Backend API 계약 문서.

Phase 1.5의 목적은 기존 파일 기반 Vision AI 파이프라인을 변경하지 않고,
MVP 1단계에서 생성하던 Event 구조를 FastAPI + SQLite 기반 API 서버로 제공하는 것이다.

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

FastAPI 기본 validation error는 기본 `422` 응답 형식을 그대로 사용한다.

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
| `confidence` | `number | null` | detector/tracker confidence |
| `created_at` | `string` | SQLite 저장 시각 |

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

## API List

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/health` | API health check |
| `POST` | `/events` | 이벤트 저장 |
| `GET` | `/events` | 이벤트 목록 조회 |
| `GET` | `/events/recent` | 최신 이벤트 조회 |
| `GET` | `/summary` | 이벤트 KPI summary 조회 |
| `GET` | `/zones` | `data/zones/sample.json` zone 목록 조회 |

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

## GET /zones

`data/zones/sample.json`을 읽어 반환한다. 파일이 없거나 형식이 맞지 않으면 빈 리스트를 반환할 수 있다.

### Response

```json
{
  "status": "success",
  "data": [
    {
      "zone_id": "playground_bottom_right",
      "name": "test video zone",
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

---

## CORS

React 개발 서버 연동을 위해 최소 다음 origin을 허용한다.

- `http://localhost:3000`
- `http://localhost:5173`
- `http://127.0.0.1:3000`
- `http://127.0.0.1:5173`

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

위 항목은 후속 단계에서 별도 설계 후 구현한다.
