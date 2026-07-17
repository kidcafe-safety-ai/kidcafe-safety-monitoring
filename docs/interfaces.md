# System Interfaces Specification

모듈 간 데이터 형식 표준. **이 문서가 변경되면 팀 공유 필수.**

---

## 1. TrackingResult (YOLO + ByteTrack 출력)

### 정의

한 프레임 기준의 YOLO 탐지 + ByteTrack 추적 결과를 담는 데이터 구조.

현재 MVP에서는 별도 Detection 모듈을 분리하지 않고, `src/tracking/bytetrack_wrapper.py`에서 YOLO 탐지와 ByteTrack 추적을 함께 처리한다.

### 구조

```python
@dataclass
class Track:
    track_id: int                # 사람 고유 ID
    bbox: List[float]            # [x1, y1, x2, y2] pixel 좌표
    foot_point: List[float]      # [cx, y2] pixel 좌표
    confidence: float            # 0.0~1.0

@dataclass
class TrackingResult:
    frame_number: int
    timestamp: str               # "HH:MM:SS.mmm" 영상 내 상대 시각
    video_source: str
    tracks: List[Track]
```

### timestamp 형식

- 형식: `HH:MM:SS.mmm`
- 의미: 영상 내 상대 시각 (시스템 시간 아님)
- 계산: `frame_number / fps`
- fps는 입력 영상의 `cv2.CAP_PROP_FPS` 값 사용

---

## 2. Event (Geofencing & Events 모듈 출력)

### 정의

위험구역 이벤트 한 건.

### EventType 상세

**Phase 2.5 기준 (현재 구현)**

| 타입 | 의미 | 발생 조건 |
|------|------|---------|
| ENTER | 진입 | 사람이 zone에 새로 들어옴 |
| DWELL | 체류 | zone에 `dwell_threshold_sec` 이상 머무름 (zone당 1회) |
| EXIT | 이탈 | 사람이 zone에서 나감 |

**Phase 3 신규 (공간 안전정책 구현 완료 / 낙상 감지는 후속 PR)**

`src/common/types.py`의 `EventType`/`VALID_EVENT_TYPES`와 `EventManager`의
`ENTER_RESTRICTED`, `DANGER_ZONE_DWELL` 발생 로직까지 반영했다.
`FALL_SUSPECT` 감지 로직은 A 역할 후속 PR 범위다.

| 타입 | 의미 | 발생 조건 |
|------|------|---------|
| ENTER_RESTRICTED | 제한구역 진입 | `zone_type=restricted` 구역에 진입 (`ENTER` 대체) |
| DANGER_ZONE_DWELL | 위험구역 체류 | `zone_type=danger` 구역에 기준 시간 이상 체류 (`DWELL` 대체) |
| FALL_SUSPECT | 낙상 의심 | bbox 비율·속도·자세 기반 낙상 판정, optional `cause` 포함 |

- 동일 상태 변화에서 일반·안전 이벤트 중복 생성 금지
- `restricted`·`danger` 구역 이탈은 기존 `EXIT` 사용
- 구역 밖 낙상: `zone_id="__global__"`
- 독립 `COLLISION_SUSPECT`는 Phase 4 이후 재검토

### 이벤트 발생 기준

- 기준점은 bbox 중심이 아니라 **foot_point**를 사용한다.
- `foot_point = [bbox 중심 x, bbox 하단 y]`
- 사람이 구역에 들어갔는지는 foot_point가 zone polygon 내부에 있는지로 판단한다.
- polygon 경계 위의 점도 zone 내부로 인정한다. (`shapely.covers()` 사용)

### Zone 전이 안정화 기준

`EventManager`는 raw polygon 판정을 바로 이벤트로 확정하지 않고, FPS와
`frame_number`를 이용한 연속 관측 시간으로 안정 상태를 결정한다.

| 전이 | 기본 확인 시간 | 동작 |
|---|---:|---|
| zone 밖 → 안 | 0.3초 | 연속 진입이 유지된 경우에만 ENTER 계열 이벤트 발생 |
| zone 안 → 밖 | 0.5초 | 연속 이탈이 유지된 경우에만 EXIT 발생 |
| Track 소실 | 0.5초 | 유예시간 후 confirmed zone에 대해 EXIT 발생 |

- 진입·이탈 확인 시간을 다르게 둔 비대칭 temporal hysteresis를 사용한다.
- 진입 후보 상태에서 Track 관측이 끊기면 연속성이 깨진 것으로 보고 후보를 초기화한다.
- `CurrentStatus.zone_occupancy`와 DWELL 시간은 raw 판정이 아닌 confirmed zone 상태를 기준으로 한다.
- `restricted` 진입은 `ENTER_RESTRICTED`만, `danger` 체류는 `DANGER_ZONE_DWELL`만 생성한다.
- polygon buffer를 이용한 공간 hysteresis와 ReID 기반 track 재연결은 이번 구현 범위가 아니다.
- 기본값은 `EventManager` 생성자에서 조정할 수 있으며, 실영상 전후 비교 후 재튜닝한다.

### timestamp 형식

- 형식: `HH:MM:SS.mmm`
- 의미: 영상 내 상대 시각 (시스템 시간 아님)
- 계산: `frame_number / fps`

### 구조

`src/common/types.py` 현재 구현 기준 (Phase 3 타입 반영 완료).

```python
EventType = Literal[
    "ENTER", "DWELL", "EXIT",
    "ENTER_RESTRICTED", "DANGER_ZONE_DWELL", "FALL_SUSPECT",
]

@dataclass
class Event:
    event_id: str                # UUID
    timestamp: str               # "HH:MM:SS.mmm" 영상 내 상대 시각
    event_type: EventType
    track_id: int
    zone_id: str
    bbox: List[float]            # [x1, y1, x2, y2] pixel 좌표
    foot_point: List[float]      # [cx, y2] pixel 좌표
    frame_number: int
    video_source: str
    # Phase 3 추가 (optional, 하위 호환)
    confidence: Optional[float] = None
    event_confidence: Optional[float] = None
    cause: Optional[EventCause] = None
```

---

## 3. Zone (Geofencing 모듈 입력)

### 정의

위험구역 또는 관심구역을 표현하는 JSON 입력 형식.

### JSON 형식

```json
[
  {
    "zone_id": "danger_door",
    "name": "출입문 (위험)",
    "type": "polygon",
    "points": [
      [0.1, 0.2],
      [0.3, 0.2],
      [0.3, 0.5],
      [0.1, 0.5]
    ],
    "rules": {
      "enter_alert": true,
      "dwell_threshold_sec": 5
    }
  }
]
```

### 좌표 기준

- `points`는 **정규화 좌표**를 사용한다.
- 범위: `0.0 ~ 1.0`
- `[0.0, 0.0]` = 영상 왼쪽 위
- `[1.0, 1.0]` = 영상 오른쪽 아래

### 검증 규칙

- `zone_id`, `name`, `type`, `points` 필수
- `type`은 현재 MVP에서 `polygon` 사용
- polygon은 최소 3개 이상의 점 필요
- 모든 좌표는 `0.0 ~ 1.0` 범위여야 함
- 잘못된 형식이면 `ValueError` 발생

---

## 4. EventManager 인터페이스

### 정의

Track의 raw zone 판정과 confirmed zone 상태를 분리하고, 확인된 상태 변화에 따라
일반 이벤트 또는 안전 이벤트를 생성하는 상태머신.

### 생성자

```python
EventManager(
    zones: List[Zone],
    fps: float,
    enter_confirm_sec: float = 0.3,
    exit_confirm_sec: float = 0.5,
    track_lost_grace_sec: float = 0.5,
)
```

### 파라미터

| 이름 | 타입 | 설명 |
|------|------|------|
| `zones` | `List[Zone]` | zone별 `dwell_threshold_sec` 접근용 |
| `fps` | `float` | 전이 확인, DWELL 및 timestamp 시간 계산용 |
| `enter_confirm_sec` | `float` | zone 진입 확정에 필요한 연속 관측 시간. 기본값 0.3초 |
| `exit_confirm_sec` | `float` | zone 이탈 확정에 필요한 연속 관측 시간. 기본값 0.5초 |
| `track_lost_grace_sec` | `float` | Track 소실 후 EXIT 확정까지의 유예시간. 기본값 0.5초 |

### 이벤트 상태 흐름

```
raw zone 밖
  ↓ enter_confirm_sec 이상 연속 진입
confirmed zone 안
  ├─ restricted → ENTER_RESTRICTED
  └─ 그 외     → ENTER
  ↓ dwell_threshold_sec 이상 체류
  ├─ danger → DANGER_ZONE_DWELL
  └─ 그 외 → DWELL
  ↓ exit_confirm_sec 이상 연속 이탈
EXIT

Track 소실
  ↓ track_lost_grace_sec 이상 미관측
confirmed zone별 EXIT
```

---

## 5. Output 파일 인터페이스

### `outputs/events.jsonl`

이벤트 로그 파일. 한 줄에 하나의 Event JSON 객체를 저장한다.

예시:

```jsonl
{"event_id":"...","timestamp":"00:00:08.500","event_type":"ENTER","track_id":3,"zone_id":"danger_door","bbox":[100.0,200.0,180.0,420.0],"foot_point":[140.0,420.0],"frame_number":212,"video_source":"data/videos/test.mp4"}
```

### `outputs/result.mp4`

시각화 결과 영상.

포함 정보:

- 사람 bbox
- track_id 라벨
- zone polygon
- foot_point
- ENTER / DWELL / EXIT 이벤트 색상
- 최근 이벤트 배너

> `outputs/result.mp4`는 실행 결과물이므로 Git에 포함하지 않는다.

---

## 6. 팀원 A/B/C 산출물 계약

### A (Vision AI / 모델 기준선 / 실시간 입력)

담당 모듈: `tracking`, `events`, `geofencing`, `video_overlay`, `scripts/`

출력:

```text
outputs/events.jsonl    # 이벤트 로그 (한 줄 = Event JSON)
outputs/result.mp4      # bbox + track_id + zone + 이벤트 오버레이 결과 영상
POST /events            # Phase 2 구현 완료
PUT /status/current     # Phase 2 구현 완료
```

### B (FastAPI / SQLite / Backend)

담당 모듈: `src/api/`

입력:

```text
POST /events (Vision AI → FastAPI)
PUT /status/current (Vision AI → FastAPI)
```

출력:

```text
GET /events, /events/recent, /summary, /zones   # Phase 1.5 구현 완료
GET /status/current                             # Phase 2 구현 완료
outputs/kidcafe_events.db  # SQLite 이벤트 누적 저장
```

### C (MVP: Streamlit 검증 대시보드 종료 / Phase 1.5 이후: React Dashboard)

담당 모듈: `frontend/`

입력:

```text
GET /events/recent   # 최근 이벤트 (Phase 2: 3초 polling)
GET /summary         # KPI (Phase 2: 10초 polling)
GET /status/current  # 현재 상태 (Phase 2: 2초 polling)
GET /events          # 이벤트 목록 (필터/페이지 진입 시)
```

---

## 7. Phase별 인터페이스 구분

**MVP (파일 기반) — 완료**

- 모든 입출력은 로컬 파일 시스템 기반
- `outputs/events.jsonl`, `events.csv`, `summary.json`, `result.mp4`
- 영상 입력은 저장 파일(`.mp4`)만 지원

**Phase 1.5 (서버 기반 준비) — 완료**

- FastAPI REST API (`src/api/`)
- SQLite 이벤트 저장 (`outputs/kidcafe_events.db`)
- React mock Dashboard (`frontend/`)

**Phase 2 (실시간 연결) — 완료**

- 웹캠 / RTSP 실시간 입력
- Event → `POST /events` 전송
- Current Status → `PUT /status/current` 전송
- React polling 기반 실시간 갱신
- WebSocket은 Phase 4 이후 검토

---

## 7-A. Event와 Current Status 분리 원칙 (Phase 2 계약)

```text
Event        → 발생 기록, 누적 저장    → POST /events
CurrentStatus → 현재 상태, 최신 값 갱신 → PUT /status/current
```

**현재 감지 인원, 위험구역 현재 인원은 Event 로그가 아니라 /status/current 기준으로 처리한다.**

이유: Event 로그만으로는 현재 추적 중인 인원 수와 위험구역 실시간 점유를 정확히 계산하기 어렵다.

### PUT /status/current 요청 예시 (A → B)

```json
{
  "source": "camera_01",
  "frame_number": 1230,
  "active_track_count": 4,
  "zone_occupancy": [
    {
      "zone_id": "exit_area",
      "zone_name": "출입구 위험구역",
      "current_count": 1,
      "risk_level": "HIGH"
    }
  ],
  "updated_at": "2026-06-08T10:15:30+09:00"
}
```

### GET /status/current 응답 예시 (B → C)

```json
{
  "status": "success",
  "data": {
    "source": "camera_01",
    "frame_number": 1230,
    "active_track_count": 4,
    "zone_occupancy": [
      {
        "zone_id": "exit_area",
        "zone_name": "출입구 위험구역",
        "current_count": 1,
        "risk_level": "HIGH"
      }
    ],
    "updated_at": "2026-06-08T10:15:30+09:00"
  },
  "message": null
}
```

### C 역할 — Dashboard KPI 데이터 소스 (Phase 2.5 기준)

MonitoringPage의 KPI와 목록은 다음 기준으로 매핑한다.

```text
/summary.today_event_count
→ DashboardSummary.today_event_count

/summary.recent_10min_event_count
→ DashboardSummary.recent_event_count

/status/current.active_track_count
→ MonitoringPage activeTrackCount state

/status/current.zone_occupancy
→ MonitoringPage zones state / danger zone occupancy

/events/recent?minutes=10&limit=5
→ 최근 10분 이벤트 목록
```

`DashboardSummary.active_tracks`와 `danger_zone_occupancy`는 기존 mock 호환을 위해 남아 있으며, API mode 화면은 `/status/current` 값을 사용한다.

추가 원칙:

- 오늘 이벤트(`today_event_count`): `Asia/Seoul` 기준
- 최근 10분(`recent_10min_event_count`): Backend UTC 현재 시각 기준
- 집계 기준 컬럼: `event.timestamp`(영상 상대 시각)가 아닌 `events.created_at`(저장 시각)
- `today_event_count`, `recent_10min_event_count` 집계 실패 시 `0`이나 목록 길이로 대체하지 않는다.

> `risk_level`: `"NORMAL" | "HIGH"` — Phase 2 required 필드. Vision AI가 `PUT /status/current` 전송 시 반드시 포함하며, Phase 3에서도 이 값 그대로 유지한다.
> `LOW | MEDIUM | HIGH`는 `risk_level`의 확장이 아니라 Frontend `SafetyEvent.severity` 파생 표시값이다 (본 문서 9절 Severity 정책 참조).

---

## 7-B. Phase 2 React Polling 기준

| API | 호출 주기 |
|---|---|
| `GET /status/current` | 2초 |
| `GET /events/recent?minutes=10&limit=5` | 3초 |
| `GET /summary` | 10초 |
| `GET /events` | 페이지 진입 또는 필터 변경 시 |

WebSocket은 Phase 2.5와 Phase 3에서도 제외하며 Phase 4 이후 검토한다.

---

## 8. Phase 2 InputSource 인터페이스

Phase 2에서는 파일 영상, 웹캠, RTSP/IP 카메라 입력을 동일한 Vision AI 파이프라인으로 처리하기 위해 입력 소스를 추상화한다.

### 목적

- 기존 파일 영상 파이프라인 유지
- 웹캠/RTSP 입력 추가 시 `main.py` 변경 최소화
- 입력 종류와 관계없이 Vision AI 파이프라인은 frame 단위로 동일하게 동작
- `Event.video_source` 필드를 source 식별자로 일관되게 사용

### 공통 인터페이스

```python
class InputSource:
    def open(self) -> None:
        """입력 소스를 연다."""

    def read(self) -> tuple[bool, Any]:
        """다음 프레임을 읽는다. 반환값은 (success, frame)."""

    def release(self) -> None:
        """입력 소스를 정리한다."""

    @property
    def fps(self) -> float:
        """입력 FPS. 알 수 없으면 fallback 값 반환."""

    @property
    def width(self) -> int:
        """프레임 가로 픽셀."""

    @property
    def height(self) -> int:
        """프레임 세로 픽셀."""

    @property
    def source_id(self) -> str:
        """Event.video_source에 들어갈 source 식별자."""

    @property
    def total_frames(self) -> int | None:
        """총 프레임 수. 실시간 소스(webcam/RTSP)는 None."""
```

### 구현 후보

```text
FileVideoSource
- 파일 영상 입력
- 예: data/videos/test.mp4
- source_id: 파일 경로

WebcamSource
- 노트북/USB 웹캠 입력
- 예: camera index 0
- source_id: webcam:0

RTSPSource
- IP 카메라 RTSP 입력
- 예: rtsp://...
- source_id: camera_01
```

### Phase 2 구현 우선순위

```text
1. FileVideoSource로 기존 동작 유지
2. WebcamSource 추가
3. RTSPSource 추가
4. reconnect / frame drop / latency 측정
```

### 주의사항

- Phase 2에서 FileVideoSource / WebcamSource / RTSPSource 구현을 완료했다.
- reconnect 고도화와 장시간 안정화는 Phase 2.5에서 검증한다.
- 기존 파일 영상 MVP 파이프라인은 깨지지 않아야 한다.
- `Event.video_source`는 파일 경로 또는 camera_id로 사용한다.

---

## 9. Phase 3 공용 계약

> 상태: EventType·ZoneType·EventCause·DB migration·Frontend 타입 반영 완료 (`feature/phase-3-event-contract`)
> 실제 감지 로직(FALL_SUSPECT 판정, zone_type 안전정책 룰)은 후속 A/B/C PR에서 구현
> 기준선: v0.2.5-dashboard

### ZoneType 계약

도형 타입(`type`)과 안전정책 타입(`zone_type`)을 분리한다.

```text
type: polygon          ← 도형 종류 (기존 유지)
zone_type: play | exit | restricted | danger  ← 안전정책 분류 (Phase 3 신규)
```

- `zone_type`은 Phase 3부터 필수 필드
- 허용되지 않은 값이면 `ZoneLoader`에서 `ValueError` 발생
- `slide_zone` 같은 `zone_id`는 그대로 유지 가능
- Backend Zone JSON(`data/zones/*.json`)에 `zone_type` 반영 완료 (`sample.json`→`danger`, `benchmark_test5.json`→`exit`)
- Frontend `ZoneType`/mock에서 `"slide"` → `"danger"` 교체 완료

```python
ZoneType = Literal["play", "exit", "restricted", "danger"]
```

**기존 Zone 매핑**

| zone_id | zone_type |
|---|---|
| `playground_bottom_right` (sample.json) | `danger` |
| `door_area` (benchmark_test5.json) | `exit` |

**이름 필드 기준**

- 내부 Zone dataclass / JSON: `name` 유지
- API 응답: `zone_name`으로 정규화 (`/zones`에서 변환)

---

### FALL_SUSPECT·EventCause 계약

```json
{
  "event_type": "FALL_SUSPECT",
  "track_id": 3,
  "zone_id": "__global__",
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

**필드 의미**

| 필드 | 의미 |
|---|---|
| `confidence` | detector/tracker confidence (기존) |
| `event_confidence` | 낙상 판정 점수 (0.0~1.0 또는 null) |
| `cause.score` | 외부 접촉 원인 후보 휴리스틱 점수 |

- 원인 근거 부족 시 `cause: null`
- `FALL_SUSPECT`가 아닌 이벤트: `event_confidence=null`, `cause=null`
- 부분적으로 누락된 `cause` 객체는 허용하지 않음
- Dashboard 표기: `외부 접촉 의심 · Track #7`
- 실제 충돌 확인으로 표현하지 않음

**EventCause 검증 규칙**

```text
type: "NEARBY_TRACK"
track_id: 0 이상의 정수
score: 0.0~1.0
evidence.min_distance_norm: 0 이상의 실수
evidence.closing_speed_norm: 0 이상의 실수
evidence.time_to_fall_sec: 0 이상의 실수
```

- `event_confidence`: `0.0~1.0` 또는 `null`
- `cause`: 위 필드를 모두 포함한 전체 객체 또는 `null`

**낙상 PoC 상태 흐름**

```text
NORMAL → FALLING_CANDIDATE → FALL_CONFIRMED → COOLDOWN
```

- Track당 낙상 이벤트는 `FALL_CONFIRMED` 전이 시 1회만 생성
- `FALL_CONFIRMED` 판정 시 낙상 시작 직전 0.5~1초 Track 기록을 소급 조회해 `cause` 후보를 결정
- `COOLDOWN` 중 재진입은 새 낙상으로 집계하지 않음
- Track 소실 시 grace period 이후 상태를 초기화

**Severity 정책**

```text
CurrentStatus.risk_level:         NORMAL | HIGH            (Phase 2 계약 유지, Backend 필드)
Frontend SafetyEvent.severity:    LOW | MEDIUM | HIGH       (Phase 3 신규, 파생 표시값)
```

`severity`는 Backend API·DB 필드가 아니라 `event_type`으로부터 Frontend에서 계산하는 파생 표시값이다.

| EventType | Severity |
|---|---|
| ENTER_RESTRICTED | HIGH |
| DANGER_ZONE_DWELL | HIGH |
| FALL_SUSPECT | HIGH |
| APPROACH_EXIT (Stretch, 구현 시) | MEDIUM |

- Severity는 `event_type` 기준으로 결정하며 `cause` 유무로 바뀌지 않음
- Phase 3에서는 Frontend 매핑으로 처리하고, API·DB 저장은 Phase 4에서 재검토

**직렬화 형식**

| 저장소 | 형식 |
|---|---|
| JSONL | `cause` 객체 그대로 |
| API 요청·응답 | `cause` 객체 그대로 |
| SQLite | `cause_json` TEXT (JSON 직렬화) |
| CSV | `cause_json` 문자열 컬럼 |

**Phase 3 Event 확장 구조**

```python
EventType = Literal[
    "ENTER", "DWELL", "EXIT",
    "ENTER_RESTRICTED", "DANGER_ZONE_DWELL", "FALL_SUSPECT",
]

@dataclass
class EventCauseEvidence:
    min_distance_norm: float
    closing_speed_norm: float
    time_to_fall_sec: float

@dataclass
class EventCause:
    type: Literal["NEARBY_TRACK"]
    track_id: int
    score: float
    evidence: EventCauseEvidence

@dataclass
class Event:
    # 기존 필드 유지
    event_id: str
    timestamp: str
    event_type: EventType
    track_id: int
    zone_id: str
    bbox: List[float]
    foot_point: List[float]
    frame_number: int
    video_source: str
    # Phase 3 추가 (optional, 하위 호환)
    confidence: Optional[float] = None
    event_confidence: Optional[float] = None
    cause: Optional[EventCause] = None
```

---

## 10. 변경 절차

1. Discord/카톡에서 변경 아이디어 공유
2. `types.py`와 `interfaces.md` 동시 수정
3. Breaking Change 여부 확인
4. Breaking Change면 PR 제목/본문에 `[Breaking Change]` 표기
5. 팀 리뷰 후 머지
