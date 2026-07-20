# API Contract v1

> **작성일**: 2026-06-04  
> **작성자**: 우민 (B / Backend FastAPI 담당)  
> **최종 수정**: 2026-07-18 (Phase 3 FALL_SUSPECT opt-in PoC 구현 반영)
> **상태**: Phase 2.5 구현 완료 / Phase 3 Live Frame API 구현 / Phase 3 Event·Zone·EventCause 계약 구현 완료 / 공간 안전정책 구현 / FALL_SUSPECT opt-in PoC 구현 완료 (`cause` 원인 후보 추정은 PR3)
> **관련 문서**: [`dashboard_api.md`](dashboard_api.md), [`dashboard_analysis.md`](dashboard_analysis.md), [`interfaces.md`](interfaces.md), [`decisions.md`](decisions.md), [`roadmap.md`](roadmap.md)

이 문서는 Phase 1.5~2.5의 구현된 API, Phase 3 Live Frame API·Event/Zone 공용 계약, 그리고 Phase 3의 확정된 후속 계약(안전 감지 로직 등)을 구분해 정리한다.

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

`GET /live/frame`은 binary endpoint이므로 위 공통 JSON wrapper의 예외다. `200`은 `image/jpeg` body를 그대로 반환하고, `204`는 body 없이 반환한다.

---

## Event Schema v1

`POST /events` 요청은 기존 `src/common/types.py`의 `Event` dataclass와 호환되는 필드를 기준으로 한다.
API 계층에서는 별도 Pydantic schema로 매핑하며, 기존 Event dataclass는 수정하지 않는다.

### Required Fields

| Field | Type | Description |
| --- | --- | --- |
| `event_id` | `string` | 이벤트 UUID 또는 고유 ID |
| `timestamp` | `string` | 영상 내 상대 시각, `HH:MM:SS.mmm` |
| `event_type` | `EventType` | 이벤트 종류. 아래 Phase 3 활성 값 중 하나 |
| `track_id` | `integer` | 사람 추적 ID |
| `zone_id` | `string` | zone 식별자 |
| `bbox` | `number[4]` | `[x1, y1, x2, y2]` pixel 좌표 |
| `foot_point` | `number[2]` | `[cx, y2]` pixel 좌표 |
| `frame_number` | `integer` | 이벤트 발생 프레임 번호 |
| `video_source` | `string` | 입력 영상 경로 또는 소스 ID |

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

이벤트 목록을 조회한다. 기본 정렬은 `id DESC` 최신순이다.

### Query Parameters

| Parameter | Type | Default | Constraint |
| --- | --- | --- | --- |
| `limit` | `integer` | `50` | `1 <= limit <= 500` |
| `offset` | `integer` | `0` | `offset >= 0` |
| `event_type` | `string | null` | `null` | Phase 3 활성 `EventType` 6종 중 하나 |
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

WebSocket은 Phase 2.5와 Phase 3에서도 제외하며 Phase 4 이후 검토한다.

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

> 상태: Live Frame API 구현 완료 / Event Schema v2·ZoneType·SQLite migration 구현 완료 / 공간 안전정책 구현 완료 / FALL_SUSPECT opt-in PoC 구현 완료 (`cause` 원인 후보 추정은 PR3)
> 기준선: v0.2.5-dashboard
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
- 업로드 주기: 1~2 FPS
- 해상도: 640×480, JPEG quality 70~80

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
- `event_confidence`: optional, 0.0~1.0 또는 null
- `cause`: optional, 전체 객체 또는 null (부분 객체 불허)
- PR2의 `FALL_SUSPECT` 생성 경로는 `cause=null`을 기록한다. non-null 원인 후보
  생성은 PR3의 외부 접촉 attribution 범위다.

**EventCause 검증 범위** (상세 규칙은 `docs/interfaces.md`의 EventCause 검증 규칙 참조)

```text
cause.type: "NEARBY_TRACK"
cause.track_id: 0 이상의 정수
cause.score: 0.0~1.0
cause.evidence.min_distance_norm / closing_speed_norm / time_to_fall_sec: 0 이상의 실수
```

- 위 범위를 벗어나거나 `cause`가 일부 필드만 포함한 부분 객체인 경우 `422 Unprocessable Entity`
- `event_confidence`가 `0.0~1.0` 범위를 벗어나면 `422 Unprocessable Entity`

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

## GET /zones Phase 3 계약

> 상태: 구현 완료 — `data/zones/*.json`에 `zone_type` 반영, `GET /zones`가 그대로 직렬화해 반환

기존 `GET /zones`는 Zone 목록을 반환한다. Phase 3에서 `zone_type` 필드가 추가됐다.

```json
{
  "status": "success",
  "data": [
    {
      "zone_id": "playground_bottom_right",
      "zone_name": "test video zone",
      "zone_type": "danger",
      "type": "polygon",
      "points": [[0.65, 0.65], [1.0, 0.65], [1.0, 1.0], [0.65, 1.0]],
      "rules": { "enter_alert": true, "dwell_threshold_sec": 5 }
    }
  ],
  "message": null
}
```

- 내부 JSON `name` → API 응답 `zone_name`으로 변환
- `zone_type`: `play | exit | restricted | danger` (Phase 3 필수)
- `PUT /zones`: Phase 4

**`name` / `zone_name` 호환성 원칙**

- `zone_name`을 표준 필드로 사용한다.
- 기존 `name`은 Phase 3에서 deprecated alias로 계속 유지한다 (API 응답에서 제거하지 않음).
- `name` 제거 여부는 Phase 4에서 재검토한다.

---

## Zone Settings 저장 계약 (Phase 3: 필드·저장 구조만 확정)

Phase 3에서는 Zone Settings의 필드와 저장 구조만 확정한다. `PUT /zones`를 통한 실제 저장 구현은 Phase 4다.

**API 필드**

```text
zone_id
zone_name
zone_type
points
dwell_threshold_sec
enter_alert
version
updated_at
```

**내부 JSON 필드**

```text
zone_id
name
zone_type
type
points
rules.enter_alert
rules.dwell_threshold_sec
version
updated_at
```

**변환 원칙**

- API `zone_name` ↔ 내부 JSON `name`
- API `dwell_threshold_sec` / `enter_alert` ↔ 내부 JSON `rules.dwell_threshold_sec` / `rules.enter_alert`
- `version`, `updated_at`은 저장 시마다 갱신 (동시 수정 감지용)
- `GET /zones` endpoint와 `zone_type` 응답 확장 모두 구현 완료
- `PUT /zones`(Zone Settings 저장)는 Phase 4 구현

---

## AlertHistory 읽기 전용 연동 (Phase 3)

- 발생 시각: 영상 상대 시각 `timestamp` 대신 API `created_at` 사용
- `created_at`: UTC 해석 → 화면에서 Asia/Seoul 변환
- `MOCK_TODAY` 하드코딩 제거, 실제 현재 날짜 사용
- `alert_id`: `event_id` 사용
- `target`: `Track #N` 형식
- `title`·`message`·`severity`: `event_type` 기반 Frontend 매핑
- 처리 상태: Phase 3에서 `미확인` 고정
- `확인중`·`처리완료`·조치 메모 저장: Phase 4
- 실제 이벤트와 Mock 처리 상태 혼용 금지
