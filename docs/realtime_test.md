# Realtime Test Log

Phase 2 이후 실시간 입력 실험 기록 문서.
테스트마다 아래 양식을 복사해서 날짜 기준으로 추가한다.

---

## 양식

### Phase 2 기본 양식

```md
## YYYY-MM-DD — [입력 소스] [모델] 테스트

### 테스트 정보

- 날짜:
- 작성자:
- 브랜치:
- 입력 소스: file / webcam / rtsp
- 모델:
- 실행 명령어:

### 측정 지표

- FPS:
- latency (ms):
- frame drop 여부:
- reconnect 여부:
- 이벤트 수 (ENTER/DWELL/EXIT):
- SQLite 저장 확인:
- React 표시 확인:

### 결과

- 성공 / 실패:
- 관찰 내용:

### 이슈

- 문제:
- 원인 추정:
- 다음 액션:
```

### Phase 2.5 안정화 테스트 양식

```md
## YYYY-MM-DD — Phase 2.5 realtime stability test

### 테스트 정보

- 날짜:
- 담당자:
- 브랜치:
- 입력 소스: webcam (내장 / USB)
- camera index:
- 활성 zone:
- 해상도:
- 모델:
- device:
- 실행 시간 (분):
- frame limit:

### 실행 명령어

.venv/bin/python -m src.main \
  --source-type webcam \
  --source <index> \
  --api-url http://localhost:8000 \
  --model yolo26n.pt \
  --infer-device auto \
  --width 640 --height 480 \
  --frames-limit <N> \
  --show

### 측정 결과

- 평균 FPS:
- frame drop:
- 이벤트 수 (ENTER / EXIT):
- ENTER / EXIT 흔들림 여부:
- API 전송:
- SQLite 저장:
- React 표시:
- API 재기동 테스트:

### 결과

- 성공 / 부분 성공 / 실패:

### 이슈

- 문제:
- 원인:
- 후속 조치:
```

---

## 기록

---

## 2026-06-10 — webcam yolo26n Phase 2 초기 연결 테스트

### 테스트 정보

- 날짜: 2026-06-10
- 작성자: 정종민 (A)
- 브랜치: feature/realtime-input
- 입력 소스: webcam (camera_device=0, 내장 FaceTime HD Camera)
- 모델: yolo26n.pt
- device: mps (Apple Silicon)
- 실행 명령어: `python scripts/test_webcam.py --camera-device 0 --frames 90 --conf 0.4`

### 환경

```text
해상도:      1280x720
CAP_FPS:     30.0
ultralytics: 8.4.56
device:      mps (Apple Silicon)
```

### 측정 지표

- FPS: 13.27 (avg), 14.3 (steady-state frame 30+)
- latency avg: 74.5ms
- latency p95: 87.6ms
- latency max: 478.7ms (첫 프레임 — MPS 부분 재컴파일)
- frame drop 여부: 없음 (0/90)
- reconnect 여부: 해당 없음 (webcam)
- 이벤트 수: ENTER=0, DWELL=0, EXIT=0 (카메라 앞 사람 없음)
- SQLite 저장 확인: 미실시 (API 서버 미기동)
- React 표시 확인: 미실시

### 결과

- 성공
- warm-up 적용 후 steady-state에서 약 14 FPS 달성
- 벤치마크(파일 영상 기준 21.3 FPS) 대비 낮은 이유:
  - 파일 영상 벤치마크는 640x480, 현재 테스트는 1280x720
  - 파일 읽기 vs 실시간 카메라 읽기 오버헤드 차이
  - MPS 첫 프레임 부분 재컴파일 지연 잔여 (478ms)
- 640x480 해상도에서는 avg 14.93 FPS 확인 (별도 측정)

### 이슈

**이슈 1: MPS JIT warm-up 지연**
- 문제: 첫 프레임 latency 10초 이상
- 원인: MPS 백엔드 JIT 컴파일
- 조치: `ByteTracker.__init__`에 `model.predict()` dummy warm-up 추가 → 첫 프레임 478ms로 감소
- 잔여: 478ms는 `.track()` vs `.predict()` 호출 경로 차이. 허용 수준으로 판단.

**이슈 2: Continuity Camera 간섭**
- 문제: iPhone이 근처에 있으면 device=0이 iPhone 카메라로 연결됨 (1920x1080)
- 원인: macOS Continuity Camera 자동 선택
- 조치: iPhone 멀리하거나 시스템 설정에서 Continuity Camera 비활성화
- Phase 2에서는 개발용 테스트이므로 내장 카메라 기준으로 진행

**이슈 3: ultralytics 기본 device가 CPU**
- 문제: ultralytics 8.4.56에서 `model.track()` device 미지정 시 CPU 사용 (8.0.x는 auto)
- 원인: 버전 변경으로 device 자동 선택 동작 변경
- 조치: `ByteTracker`에 `_auto_device()` 추가, `model.track(device=self._device)` 명시

### 다음 액션

- API 서버(`uvicorn src.api.main:app`) 기동 후 `--api-url http://localhost:8000` 포함 재측정
- end-to-end 흐름 확인: 웹캠 → 이벤트 발생 → SQLite 저장 → React 표시

---

## 2026-06-10 — webcam yolo26n A 단독 smoke test

### 테스트 정보

- 날짜: 2026-06-10
- 작성자: 정종민 (A)
- 브랜치: feature/realtime-input
- 입력 소스: webcam (camera_device=0, 640x480)
- 모델: yolo26n.pt
- device: mps (Apple Silicon, auto 선택)
- 실행 명령어:
  `python scripts/test_webcam.py --camera-device 0 --infer-device auto --frames 300 --conf 0.4 --width 640 --height 480`

### 환경

```text
해상도:      640x480
CAP_FPS:     30.0
infer_device: mps (auto 선택)
ultralytics: 8.4.56
```

### 측정 지표 (300프레임 기준)

- FPS: 12.86 (avg)
- latency avg: 77.3ms
- latency p95: 107.1ms
- latency max: 413.9ms (첫 프레임 — MPS warm-up)
- frame drop: 0 / 300
- track_id 표시 여부: 확인 (track_id=1 탐지)
- ENTER / DWELL / EXIT: events.jsonl에 ENTER + EXIT 각 1건 기록 확인
- API 서버 미기동 시 pipeline 유지 여부: 유지 (Connection refused WARNING만 출력, 정상 종료)

### 결과

- 성공
- 300프레임 전 구간 frame drop 없음
- steady-state avg ~12.86 FPS (첫 프레임 warm-up 제외 시 ~13 FPS)
- API 서버 없을 때 WARNING 출력 후 pipeline 계속 진행 — 예외로 죽지 않음
- zone `playground_bottom_right` 기준으로 ENTER/EXIT 이벤트 정상 발생 및 저장

### 이슈

- 문제: 없음
- 원인 추정: -
- 다음 액션: API 서버 기동 후 end-to-end (웹캠 → API → SQLite → React) 연동 확인

---

## 2026-06-23 — Phase 2.0 E2E 인수 테스트 (webcam + FastAPI + React)

### 테스트 정보

- 날짜: 2026-06-23
- 작성자: 정종민
- 브랜치: docs/close-phase-2
- 입력 소스: webcam (device=0, 640x480)
- 모델: yolo26n.pt
- device: mps (Apple Silicon, auto 선택)
- 실행 명령어:
  ```bash
  .venv/bin/python -m src.main \
    --source-type webcam \
    --source 0 \
    --api-url http://localhost:8000 \
    --model yolo26n.pt \
    --infer-device auto \
    --width 640 --height 480 \
    --frames-limit 300 \
    --show
  ```

### 환경

```text
해상도:       640x480
CAP_FPS:      30.0
infer_device: mps (auto 선택)
ultralytics:  8.4.56
FastAPI:      uvicorn src.api.main:app --reload --port 8000
React:        VITE_API_MODE=api VITE_API_BASE_URL=http://localhost:8000 npm run dev
```

### 측정 지표 (300프레임 기준)

- FPS: 약 14~16 (steady-state)
- frame drop: 없음
- 총 이벤트: 24건 (ENTER/EXIT)
- 감지 track_id: 1, 7
- zone: playground_bottom_right

### E2E 흐름 확인 결과

```text
[x] 웹캠 300프레임 정상 처리
[x] ENTER / EXIT 이벤트 정상 생성 (24건)
[x] FastAPI POST /events 수신 정상
[x] PUT /status/current 전송 정상 (2초 주기)
[x] SQLite events 저장 확인
[x] GET /status/current 응답 확인 (active_track_count 표시)
[x] GET /events/recent 응답 확인 (ENTER/EXIT 목록)
[x] React API mode에서 KPI / zone 상태 / 최근 이벤트 표시 확인
```

### 결과

- **Phase 2.0 E2E smoke test 성공**
- 웹캠 → YOLO26n + ByteTrack → 이벤트 생성 → FastAPI → SQLite → React 전 구간 정상 동작 확인
- API 전송 포함 시 steady-state ~14 FPS 유지

### 이슈

- 없음. 이벤트 흔들림(ENTER→EXIT 빈번 반복)은 zone 경계 통과 동작이며 Phase 2.5 debounce 검토 대상.
- 장시간 안정성 검증은 Phase 2.5 P0 항목으로 이동.

---

## 2026-06-24 — Phase 2.5 React Dashboard API mode 표시 검증

### 테스트 정보

- 날짜: 2026-06-24
- 작성자: 현수 (C / Frontend)
- 브랜치: feature/react-dashboard
- 입력 소스: FastAPI 테스트 데이터 주입
- 모델: 해당 없음 (React Dashboard 표시 검증)
- 실행 명령어:
  ```powershell
  $env:VITE_API_MODE='api'
  $env:VITE_API_BASE_URL='http://localhost:8000'
  npm.cmd run dev --prefix frontend -- --host 127.0.0.1 --port 3000 --strictPort
  ```

### 검증 대상

- `GET /status/current`
  - 현재 감지 인원 KPI
  - zone 상태 패널
  - 2초 polling
- `GET /events/recent`
  - 최근 이벤트 목록
  - 최근 이벤트 수 KPI
  - 3초 polling
- `GET /summary`
  - 오늘 발생 이벤트 수 KPI
  - 10초 polling
- `GET /events`
  - 이벤트 기록 / 통계 화면의 차트와 테이블

### 적용된 React Dashboard 수정 확인

- 현재 감지 인원 KPI는 `summary.active_tracks` 대신 `/status/current` 2초 polling state인 `activeTrackCount`를 직접 사용하도록 정리했다.
- zone 상태는 `/status/current.zone_occupancy` 기준으로 표시한다.
- `ZoneStatusPanel`은 zone 배열이 비어 있으면 `현재 감지된 구역 상태가 없습니다.` empty 문구를 표시한다.
- `getDashboardSummary()`는 `/summary`만 호출하도록 축소했다.
- 위험구역 체류 인원 KPI는 `zones` state에서 `risk_level === "HIGH"`인 구역의 `current_count` 합계로 계산한다.
- 최근 이벤트 수 KPI는 `recentEvents.length`를 사용한다.
- `/summary` 10초 polling 시 `/status/current`, `/events/recent`가 추가 호출되는 중복 구조를 제거했다.

### 테스트 데이터

`PUT /status/current`

```json
{
  "source": "unknown",
  "frame_number": 2402,
  "active_track_count": 2,
  "zone_occupancy": [
    {
      "zone_id": "codex_high_zone",
      "zone_name": "E2E High Zone",
      "current_count": 2,
      "risk_level": "HIGH"
    },
    {
      "zone_id": "codex_normal_zone",
      "zone_name": "E2E Normal Zone",
      "current_count": 0,
      "risk_level": "NORMAL"
    }
  ]
}
```

`POST /events`

```json
{
  "event_id": "codex_e2e_20260624204159",
  "timestamp": "00:01:23.456",
  "event_type": "DWELL",
  "track_id": 9001,
  "zone_id": "codex_high_zone",
  "zone_name": "E2E 테스트 위험구역",
  "bbox": [10, 20, 110, 220],
  "foot_point": [60, 220],
  "frame_number": 2401,
  "video_source": "codex_e2e",
  "confidence": 0.99
}
```

### API 응답 확인

```text
GET /status/current
- active_track_count: 2
- zone_occupancy: 2개
- HIGH zone current_count: 2

GET /events/recent?limit=5
- data: 1건
- event_type: DWELL
- track_id: 9001
- zone_id: codex_high_zone

GET /events
- total: 1
- count: 1

GET /summary
- total_events: 1
- dwell_count: 1
- total_tracks: 1
- video_count: 1
```

### React 표시 확인

Monitoring 화면:

```text
현재 감지 인원: 2
오늘 발생 이벤트 수: 1
위험구역 체류 인원: 2
최근 이벤트 수: 1
최근 이벤트: 1건 / DWELL / Track 9001 / codex_high_zone
위험구역 상태: 2개 구역
- E2E High Zone / codex_high_zone / 2 / HIGH
- E2E Normal Zone / codex_normal_zone / 0 / NORMAL
```

이벤트 기록 / 통계 화면:

```text
이벤트 타입별 발생 수
- ENTER: 0
- DWELL: 1
- EXIT: 0

이벤트 테이블
- 1건
- 00:01:23.456 / DWELL / 9001 / codex_high_zone / 2401 / codex_e2e
```

### Network polling 확인

실제 API mode React 화면에서 확인한 steady-state 호출 주기:

```text
GET /status/current: 약 2초
GET /events/recent?limit=5: 약 3초
GET /summary: 약 10초
GET /events: 이벤트 기록 / 통계 화면 진입 시 호출
```

`/summary` 10초 polling 시점에 `/status/current`, `/events/recent`가 추가로 한 번 더 튀던 중복 호출은 제거됐다. 10초 지점에 `/status/current`가 같이 보이는 경우는 2초 polling 주기가 10초 배수와 겹친 정상 호출이다.

### API 실패 / fallback 확인

닫힌 API base URL(`http://localhost:8999`)을 쓰는 별도 React dev server로 실패 상황을 확인했다.

```text
요청 실패: net::ERR_CONNECTION_REFUSED
화면 표시:
- API 연결에 실패했습니다. mock 또는 기본값으로 화면을 표시합니다.
- 현재 감지 인원: 0
- 오늘 발생 이벤트 수: 0
- 위험구역 체류 인원: 0
- 최근 이벤트 수: 0
- 최근 이벤트: 0건
- 위험구역 상태: 0개 구역
- 현재 감지된 구역 상태가 없습니다.
```

### 상태별 확인

- loading: 초기 요청 중 `데이터를 불러오는 중입니다.` banner 표시 확인
- error: API 실패 banner 표시 확인
- empty: 이벤트 없음 / zone 없음 상태에서 empty 문구 표시 확인
- success: 테스트 current status와 이벤트가 React 화면에 실제 표시됨

### 결과

- 성공
- FastAPI → SQLite → React Dashboard 실제 표시 흐름 확인
- CurrentStatus가 현재 감지 인원 KPI와 zone 상태에 반영됨
- 최근 이벤트와 이벤트 기록 화면이 실제 API 데이터 기준으로 표시됨
- `/summary`는 Monitoring 화면의 오늘 발생 이벤트 수 KPI에 반영됨
- 이벤트 기록 / 통계 화면의 차트와 테이블은 현재 `/events` 데이터를 기준으로 구성됨

### 이슈

- 테스트로 주입한 `codex_e2e_20260624204159` 이벤트와 `unknown` current status는 SQLite에 남아 있다. 필요하면 별도 cleanup 또는 테스트 DB 분리 방식을 검토한다.
- 이벤트 기록 / 통계 화면이 반드시 `/summary` 기반이어야 한다면, 현재 `/events` 기반 차트/테이블 구조는 후속 논의가 필요하다.
