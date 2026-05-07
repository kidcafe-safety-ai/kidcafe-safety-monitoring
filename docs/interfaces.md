# System Interfaces Specification

모듈 간 데이터 형식 표준. **이 문서가 변경되면 팀 공유 필수.**

## 1. TrackingResult (Detection & Tracking 모듈 출력)

### 정의
한 프레임의 추적 결과를 담는 데이터 구조.

### 구조
```python
@dataclass
class Track:
    track_id: int                # 사람 고유 ID
    bbox: List[float]            # [x1, y1, x2, y2]
    foot_point: List[float]      # [cx, y2]
    confidence: float            # 0.0~1.0

@dataclass
class TrackingResult:
    frame_number: int
    timestamp: str               # ISO 8601
    video_source: str
    tracks: List[Track]
```

## 2. Event (Geofencing & Events 모듈 출력)

### 정의
위험구역 이벤트 한 건.

### 구조
```python
EventType = Literal["ENTER", "DWELL", "EXIT"]

@dataclass
class Event:
    event_id: str                # UUID
    timestamp: str               # ISO 8601
    event_type: EventType
    track_id: int
    zone_id: str
    bbox: List[float]
    foot_point: List[float]
    frame_number: int
    video_source: str
```

## 3. Zone (Geofencing 모듈 입력)

### JSON 형식
```json
[{
  "zone_id": "danger_door",
  "name": "출입문 (위험)",
  "type": "polygon",
  "points": [[0.1, 0.2], [0.3, 0.2], [0.3, 0.5], [0.1, 0.5]],
  "rules": {
    "enter_alert": true,
    "dwell_threshold_sec": 5
  }
}]
```

**좌표:** 정규화 (0.0 ~ 1.0)

## 4. 변경 절차

1. Discord,카톡에서 아이디어 공유
2. types.py와 interfaces.md 동시 수정
3. PR 올리기 (`[Breaking Change]` 표기)
4. 팀 리뷰 후 머지