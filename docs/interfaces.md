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

| 타입 | 의미 | 발생 조건 |
|------|------|---------|
| ENTER | 진입 | 사람이 zone에 새로 들어옴 |
| DWELL | 체류 | zone에 `dwell_threshold_sec` 이상 머무름 (zone당 1회) |
| EXIT | 이탈 | 사람이 zone에서 나감 |

### 이벤트 발생 기준

- 기준점은 bbox 중심이 아니라 **foot_point**를 사용한다.
- `foot_point = [bbox 중심 x, bbox 하단 y]`
- 사람이 구역에 들어갔는지는 foot_point가 zone polygon 내부에 있는지로 판단한다.
- polygon 경계 위의 점도 zone 내부로 인정한다. (`shapely.covers()` 사용)

### timestamp 형식

- 형식: `HH:MM:SS.mmm`
- 의미: 영상 내 상대 시각 (시스템 시간 아님)
- 계산: `frame_number / fps`

### 구조

```python
EventType = Literal["ENTER", "DWELL", "EXIT"]

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

Track의 zone 상태 변화를 관리하여 ENTER / DWELL / EXIT 이벤트를 생성하는 상태머신.

### 생성자

```python
EventManager(zones: List[Zone], fps: float)
```

### 파라미터

| 이름 | 타입 | 설명 |
|------|------|------|
| `zones` | `List[Zone]` | zone별 `dwell_threshold_sec` 접근용 |
| `fps` | `float` | DWELL 시간 계산 및 timestamp 계산용 |

### 이벤트 상태 흐름

```
zone 밖
  ↓
ENTER
  ↓
zone 안에 머무름
  ↓
DWELL (dwell_threshold_sec 이상 체류 시, zone당 1회)
  ↓
EXIT
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

## 6. 팀원 A/B/C 산출물 계약 (MVP 기준)

MVP 1단계 기준의 팀원별 입출력 인터페이스.

### A (Vision AI Backend + 결과 영상)

담당 모듈: `tracking`, `events`, `geofencing`, `video_overlay`

출력:

```text
outputs/events.jsonl    # 이벤트 로그 (한 줄 = Event JSON)
outputs/result.mp4      # bbox + track_id + zone + 이벤트 오버레이 결과 영상
```

### B (Data Analysis + Pipeline 운영)

담당 모듈: `main.py`, `event_writer`, `event_aggregator`, `charts`

입력:

```text
outputs/events.jsonl
```

출력:

```text
outputs/events.csv      # 이벤트 로그 CSV
outputs/summary.json    # KPI 요약 JSON
```

관련 모듈: `event_aggregator.py`, `charts.py`

### C (Streamlit 검증 대시보드)

담당 모듈: `visualization/app.py`, `visualization/pages`

입력:

```text
outputs/events.jsonl
outputs/events.csv
outputs/summary.json
outputs/result.mp4
data/zones/sample.json
```

---

## 7. MVP / Phase 2 인터페이스 구분

**MVP (파일 기반)**

- 모든 입출력은 로컬 파일 시스템 기반
- `outputs/events.jsonl`, `events.csv`, `summary.json`, `result.mp4`
- 영상 입력은 저장 파일(`.mp4`)만 지원

**Phase 2 이후 (서버 기반, 미구현)**

- FastAPI REST API
- WebSocket 실시간 이벤트 스트림
- DB (PostgreSQL 또는 SQLite) 연동

---

## 8. Phase 2 InputSource 인터페이스 초안

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

    def get_fps(self) -> float:
        """입력 FPS를 반환한다. 알 수 없으면 30.0."""

    def get_size(self) -> tuple[int, int]:
        """프레임 크기를 (width, height)로 반환한다."""

    def get_source_id(self) -> str:
        """Event.video_source에 들어갈 source 식별자를 반환한다."""
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
- source_id: webcam_0

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

- Phase 1.5에서는 입력 인터페이스 초안만 확정하고 실제 RTSP 구현은 Phase 2에서 진행한다.
- 기존 파일 영상 MVP 파이프라인은 깨지지 않아야 한다.
- `Event.video_source`는 파일 경로 또는 camera_id로 사용한다.
- 위 인터페이스는 MVP에 포함되지 않으며 Phase 2에서 설계·구현한다.

---

## 9. 변경 절차

1. Discord/카톡에서 변경 아이디어 공유
2. `types.py`와 `interfaces.md` 동시 수정
3. Breaking Change 여부 확인
4. Breaking Change면 PR 제목/본문에 `[Breaking Change]` 표기
5. 팀 리뷰 후 머지
