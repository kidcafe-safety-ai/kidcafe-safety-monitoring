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

### Phase 2.5 backend API smoke test 양식

이 양식은 B 역할(FastAPI / SQLite) 점검용이다. USB 웹캠 실측, React 화면 확인, Docker 실행 확인은 필수 항목이 아니며 직접 확인하지 않았으면 `N/A`로 기록한다.
기존 `tests/test_api_basic.py`와 신규 `tests/test_api_stability.py`를 함께 사용해 Phase 2.5 B 역할의 Backend API smoke 범위를 확인한다.
`tests/test_api_basic.py`는 `POST /events`, `GET /events`, `GET /events/recent`, `GET /summary`, `GET /zones`, `PUT /status/current`, `GET /status/current` 기본 동작을 회귀 확인한다.
`tests/test_api_stability.py`는 CORS preflight, FastAPI validation error 응답 형식, CurrentStatus의 `zone_name` optional 처리, `KIDCAFE_DB_PATH` 기반 테스트 DB 분리 기준을 보강 확인한다.

````md
## YYYY-MM-DD — Phase 2.5 backend API smoke test

### 테스트 정보

- 날짜:
- 담당자:
- 브랜치:
- FastAPI 실행 명령어:
- DB 파일 경로:
- 테스트 DB 환경변수:

### 실행 명령어

PowerShell 예시:

```powershell
$env:KIDCAFE_DB_PATH = "<temp-or-local-test-db-path>"
uvicorn src.api.main:app --reload --port 8000
curl.exe http://localhost:8000/health
curl.exe http://localhost:8000/zones
curl.exe http://localhost:8000/summary
curl.exe http://localhost:8000/status/current
curl.exe http://localhost:8000/events/recent
```

`POST /events`, `PUT /status/current`는 curl.exe, Swagger, 또는 pytest로 확인한다.

### API smoke 결과

- GET /health:
- GET /zones:
- POST /events:
- GET /events:
- GET /events/recent:
- GET /summary:
- PUT /status/current:
- GET /status/current:
- CORS 개발 origin 확인:
- FastAPI validation error 응답 형식:
- CurrentStatus zone_name optional 처리:
- 테스트 DB 분리:
- React polling 확인 여부: N/A 또는 확인 결과

### Git 포함 제외 확인

- `outputs/` 산출물 포함 여부:
- DB 파일 포함 여부:
- `.env` 포함 여부:
- `*.pt` 포함 여부:

### 결과

- 성공 / 부분 성공 / 실패:

### 이슈

- 문제:
- 원인:
- 후속 조치:
````

---

## 기록

> Phase 2.5 완료 기준: 2026-06-28 macOS Docker E2E 검증 통과. 상세 결과는 하단 각 섹션 참고.

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

> **Update (2026-06-29)**: 현재 구현에서는 최근 이벤트 목록을
> `/events/recent?minutes=10&limit=5`로 조회하고, 최근 10분 이벤트 수 KPI는
> `/summary.recent_10min_event_count`를 사용한다. 아래 내용은 당시 검증 기록이다.

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

---

## 2026-06-25 — Phase 2.5 webcam E2E 안정화 테스트

### 목적

Phase 2.0에서 성공한 webcam E2E 흐름이 Phase 2.5 기준으로 반복 실행 가능한지 확인한다.

### 통과 기준

- 300프레임 smoke test 정상 종료
- 2700프레임 장시간 테스트 정상 종료
- API 전송 / SQLite 저장 / React 표시 확인
- API 장애 시 pipeline 크래시 없음

### 테스트 정보

- 날짜: 2026-06-25
- 작성자: 정종민 (A / Vision AI)
- 브랜치: test/phase-2-5-realtime-stability
- 입력 소스: webcam 내장 (device=0)
- 해상도: 640x480
- 모델: yolo26n.pt
- device: mps (auto 선택, Apple Silicon)
- zones: data/zones/sample.json (zone: playground_bottom_right)

### 실행 명령어

```bash
# smoke test
.venv/bin/python -m src.main \
  --source-type webcam --source 0 \
  --api-url http://localhost:8000 \
  --model yolo26n.pt --infer-device auto \
  --width 640 --height 480 --frames-limit 300 --show

# 장시간 안정화 테스트
.venv/bin/python -m src.main \
  --source-type webcam --source 0 \
  --api-url http://localhost:8000 \
  --model yolo26n.pt --infer-device auto \
  --width 640 --height 480 --frames-limit 2700 --show
```

### 환경

```text
해상도:       640x480
CAP_FPS:      30.0
infer_device: mps (auto 선택)
FastAPI:      uvicorn src.api.main:app --reload --port 8000
React:        VITE_API_MODE=api VITE_API_BASE_URL=http://localhost:8000 npm run dev
DB:           outputs/kidcafe_events.db
```

### 1단계 — 300프레임 smoke test

```text
처리 frame: 300
이벤트: 4건 (ENTER×2, EXIT×2)
track_id: 1 (전체 구간 안정)
FPS: 13.4~22.1 (steady-state ~15 FPS)
API 전송: 정상
SQLite 저장: 정상
React 표시: 최근 이벤트 표시 확인
```

결과: **성공**

### 2단계 — 2700프레임 장시간 안정화 테스트 (~3분)

```text
처리 frame: 2700
이벤트: 40건
  - ENTER: 20건
  - EXIT:  19건
  - DWELL:  1건 (track_id=1, frame 1709)
FPS: 9.9~22.1 (steady-state ~14-15 FPS)
frame read 실패 / 중단: 없음
API 전송: 정상
SQLite 저장: 정상 (최근 10건 확인)
React KPI: 현재 감지 인원 변동 표시 확인
React zone: playground_bottom_right HIGH 상태 표시 확인
React 최근 이벤트: ENTER/EXIT/DWELL 표시 확인
```

#### /status/current 확인

```json
{
  "source": "webcam:0",
  "frame_number": 2693,
  "active_track_count": 1,
  "zone_occupancy": [
    {
      "zone_id": "playground_bottom_right",
      "zone_name": "test video zone",
      "current_count": 1,
      "risk_level": "HIGH"
    }
  ]
}
```

#### SQLite 최근 10건

```text
EXIT|40|playground_bottom_right|2663|webcam:0
ENTER|40|playground_bottom_right|2660|webcam:0
ENTER|1|playground_bottom_right|2653|webcam:0
EXIT|1|playground_bottom_right|2564|webcam:0
ENTER|1|playground_bottom_right|2496|webcam:0
EXIT|34|playground_bottom_right|2355|webcam:0
ENTER|34|playground_bottom_right|2353|webcam:0
EXIT|1|playground_bottom_right|2343|webcam:0
EXIT|34|playground_bottom_right|2342|webcam:0
ENTER|34|playground_bottom_right|2336|webcam:0
```

결과: **성공**

### 3단계 — API 장애 테스트 (600프레임)

FastAPI를 실행 중 종료(Ctrl+C)한 상태에서 Vision AI 600프레임 계속 실행.

```text
API 종료 시점: frame ~210
WARNING 발생: 4회 (PUT /status/current 실패)
pipeline 유지: 정상 (WARNING 후 계속 진행)
600프레임 정상 완료: 확인
React fallback 표시: API 연결 실패 banner 표시 확인
```

WARNING 로그 예시:

```text
[WARNING] PUT /status/current 요청 실패 (API 서버 확인 필요):
HTTPConnectionPool(host='localhost', port=8000): Max retries exceeded
(Caused by NewConnectionError: [Errno 61] Connection refused)
```

결과: **성공 — API 종료 시 pipeline 크래시 없음, WARNING 후 계속 진행**

### 이벤트 흔들림 관찰

```text
- 화면 밖 이탈 후 재입장 시 ByteTrack이 새 track_id 할당
  → 단명 track_id 다수 발생 (5, 23, 25, 27, 28, 33, 34, 40)
- zone 경계 근처에서 ENTER/EXIT 빠른 반복 관찰
  → 대표 사례: track_id=28, frame 1807~1814 (7프레임 내 ENTER/EXIT 3회 반복)
- 원인: zone 경계 근처 foot_point 진동 + bbox 흔들림
- Phase 3 debounce / hysteresis 고도화 근거로 기록
```

### RTSP / IP 카메라

RTSP/IP 카메라 테스트는 Phase 2.5에서 수행하지 않음. 장비 미확보 상태.
RTSPSource 구조는 코드베이스에 존재하며, 장비 확보 후 Phase 3 또는 별도 테스트에서 수행 예정.

### 최소 통과 기준 체크리스트

```text
[x] 300프레임 smoke test 성공
[x] 2700프레임 장시간 테스트 성공 (~3분)
[x] FastAPI POST /events 수신 확인
[x] PUT /status/current 수신 확인
[x] SQLite 저장 확인
[x] React 최근 이벤트 표시 확인
[x] React KPI / zone 상태 표시 확인
[x] API 서버 종료 시 pipeline 유지 확인
[x] 결과 docs/realtime_test.md 기록
```

### 결과

- **Phase 2.5 A 역할 안정화 테스트 성공**
- 웹캠 → YOLO26n + ByteTrack → 이벤트 생성 → FastAPI → SQLite → React 전 구간 정상 동작 확인
- API 장애 시 pipeline 크래시 없이 WARNING 후 계속 진행
- 이벤트 흔들림(경계 ENTER/EXIT 반복, track_id 단명) 관찰 완료 → Phase 3 debounce 설계 입력

### 후속 조치

- Phase 2.5 처리: A 단독 안정화 테스트 기준 추가 수정 없음
- Phase 3로 이관: zone 경계 debounce / hysteresis, track_id 재할당 suppression
- C (USB 웹캠) 테스트 결과: 2026-06-28 섹션에 추가 완료

---

## 2026-06-28 — Windows USB 웹캠 Phase 2.5 반복 E2E 테스트

### 테스트 정보

- 날짜: 2026-06-28
- 작성자: 현수 (C / Frontend)
- 브랜치: `feature/react-dashboard`
- USB 웹캠: Logitech HD Pro Webcam C920 (`OpenCV index=0`)
- 내장 웹캠: 720p HD Camera (`OpenCV index=1`)
- 모델: `yolo26n.pt`
- 추론 장치: CPU (`torch 2.5.1+cpu`, CUDA 사용 불가)
- OpenCV: 4.8.1
- ultralytics: 8.4.75 (로컬 Windows 실험 환경 기준; 저장소 기준 버전은 8.4.56)
- zone: `data/zones/sample.json` (`playground_bottom_right`)
- FastAPI / React: Docker Compose 실행

장치 탐색 결과 C920은 1920x1080 입력이 가능한 `index=0`, 내장 카메라는 최대 1280x720인 `index=1`로 식별했다. `index=0`, `index=1` 모두 프레임 read에 성공했고 `index=2`, `index=3`은 열리지 않았다.

### 실행 명령어

```powershell
# 640x480 추론 smoke test
.\venv\Scripts\python.exe scripts\test_webcam.py `
  --camera-device 0 --frames 90 --conf 0.4 `
  --width 640 --height 480 --infer-device cpu

# Full HD 추론 비교
.\venv\Scripts\python.exe scripts\test_webcam.py `
  --camera-device 0 --frames 30 --conf 0.4 `
  --width 1920 --height 1080 --infer-device cpu

# FastAPI / SQLite E2E 측정
.\venv\Scripts\python.exe scripts\test_webcam.py `
  --camera-device 0 --frames 300 --conf 0.4 `
  --width 640 --height 480 --infer-device cpu `
  --api-url http://localhost:8000

# 실제 메인 파이프라인 실행
.\venv\Scripts\python.exe -m src.main `
  --source-type webcam --source 0 `
  --api-url http://localhost:8000 `
  --model yolo26n.pt --infer-device cpu `
  --width 640 --height 480 --frames-limit 180 --conf 0.4 `
  --output outputs/usb_c920_events.jsonl `
  --csv-output outputs/usb_c920_events.csv `
  --summary-output outputs/usb_c920_summary.json `
  --overlay-output outputs/usb_c920_result.mp4

# API 장애 시나리오
.\venv\Scripts\python.exe scripts\test_webcam.py `
  --camera-device 0 --frames 60 --conf 0.4 `
  --width 640 --height 480 --infer-device cpu `
  --api-url http://localhost:8999
```

### 1단계 — 원시 캡처 안정성

| 요청 해상도 | 측정 프레임 | 성공 | drop | 측정 시간 | 캡처 FPS |
| --- | ---: | ---: | ---: | ---: | ---: |
| 640x480 | 300 | 300 | 0 | 9.93초 | 30.21 |
| 1920x1080 | 90 | 90 | 0 | 17.92초 | 5.02 |

- 두 해상도 모두 프레임 read 실패는 없었다.
- C920은 Full HD에서 `CAP_FPS=5.0`으로 협상되어 640x480보다 캡처 속도가 크게 낮아졌다.
- 현재 Windows CPU 환경의 실시간 추론 기본값은 640x480이 적합하다.

### 2단계 — 해상도별 YOLO 추론

| 해상도 | 프레임 | avg FPS | avg latency | p95 | max | drop | 이벤트 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 640x480 | 90 | 3.20 | 289.1ms | 326.8ms | 2023.5ms | 0 | 없음 |
| 1920x1080 | 30 | 3.50 | 219.0ms | 221.8ms | 1201.0ms | 0 | ENTER 2, EXIT 2 |

- 첫 640x480 실행은 모델/CPU 초기 warm-up 영향으로 평균 FPS가 낮게 측정됐다.
- Full HD에서도 추론 및 이벤트 생성은 성공했지만 카메라 입력 자체가 5 FPS로 제한됐다.
- 두 실행 모두 track 감지와 정상 종료를 확인했다.

### 3단계 — 300프레임 FastAPI / SQLite E2E

```text
processed_frames: 300
dropped_frames: 0
total_elapsed_sec: 48.14
avg_fps: 6.23
avg_latency_ms: 153.4
p95_latency_ms: 209.6
max_latency_ms: 967.0
events: ENTER 3 / DWELL 1 / EXIT 2
API 전송: 성공 6 / 실패 0
```

API 및 DB 반영 결과:

```text
테스트 전 GET /summary total_events: 1
테스트 후 GET /summary total_events: 7
GET /status/current source: webcam:0
GET /status/current frame_number: 270
GET /status/current active_track_count: 1
GET /status/current zone_occupancy: 1개
SQLite webcam:0 이벤트: 6건
SQLite 유형: ENTER 3 / DWELL 1 / EXIT 2
```

결과: **성공 — 이벤트 6건 전송 및 SQLite 저장, CurrentStatus 반영 확인**

### 4단계 — 실제 `src.main` 180프레임 E2E

```text
processed_frames: 180
events: ENTER 1 / DWELL 1 / EXIT 0
POST /events: 2회
PUT /status/current: 14회
API 4xx / 5xx: 0회
최종 CurrentStatus frame_number: 172
최종 active_track_count: 1
```

생성 산출물:

```text
outputs/usb_c920_events.jsonl
outputs/usb_c920_events.csv
outputs/usb_c920_summary.json
outputs/usb_c920_result.mp4 (925,504 bytes)
```

`usb_c920_summary.json` 결과:

```json
{
  "total_events": 2,
  "enter_count": 1,
  "dwell_count": 1,
  "exit_count": 0,
  "total_tracks": 1,
  "video_count": 1,
  "avg_dwell_seconds": 5.0
}
```

300프레임 측정과 메인 파이프라인 실행을 합친 SQLite `webcam:0` 이벤트는 총 8건이며 유형은 ENTER 4, DWELL 2, EXIT 2로 확인됐다.

결과: **성공 — 실제 CLI, 2초 CurrentStatus 전송, 로컬 산출물 및 API 저장 정상**

### 5단계 — API 장애 60프레임 테스트

연결되지 않는 `http://localhost:8999`를 API URL로 지정했다.

```text
processed_frames: 60
dropped_frames: 0
events: ENTER 4 / EXIT 4
API 전송: 성공 0 / 실패 8
pipeline 종료 코드: 0
avg_fps: 0.99
avg_latency_ms: 973.4
p95_latency_ms: 4419.1
max_latency_ms: 9751.1
```

- API 요청 실패가 발생해도 파이프라인은 크래시 없이 60프레임을 완료했다.
- 동기식 HTTP timeout이 이벤트마다 누적되어 처리 속도가 정상 API E2E의 6.23 FPS에서 0.99 FPS로 감소했다.
- 기능 안정성은 통과했지만 API 장애 시 추론 성능 저하는 후속 개선 대상으로 기록한다.

결과: **부분 성공 — 파이프라인 유지 성공, 장애 중 처리량 저하 확인**

### React Dashboard 연결 확인

```text
GET http://localhost:3000: 200
GET /health: 200
GET /status/current: 200
GET /events/recent?limit=10: 200
GET /summary: 200
VITE_API_MODE: api
VITE_API_BASE_URL: http://localhost:8000
```

- React Dashboard가 실제 API mode로 제공되는 것을 확인했다.
- 웹캠 이벤트와 CurrentStatus가 화면에서 사용하는 API 응답에 반영된 것을 확인했다.
- 이번 자동 테스트에서는 브라우저 화면의 육안 표시 및 Network polling 캡처는 별도로 수행하지 않았다.

### 결과

- **USB C920 Phase 2.5 반복 테스트 성공**
- 장치 연결, 640x480 및 Full HD 캡처, YOLO 추론, ENTER/DWELL/EXIT 생성, FastAPI 전송, SQLite 저장, CurrentStatus 갱신, React API mode 제공까지 확인했다.
- Windows CPU 환경에서는 640x480을 기본 해상도로 사용하는 것이 적절하다.
- Full HD는 프레임 누락은 없지만 카메라 협상 FPS가 5로 제한된다.

### 이슈 및 후속 조치

1. API 장애 시 동기식 요청 timeout으로 추론 FPS가 크게 감소한다.
   - Phase 2.5에서는 크래시 없이 계속 실행되는 기준은 충족한다.
   - 후속 개선 시 비동기 전송, 전송 queue 또는 더 짧은 connect timeout을 검토한다.
2. zone 경계에서 짧은 ENTER/EXIT 반복이 다시 관찰됐다.
   - 기존 Phase 3 debounce / hysteresis 개선 항목을 유지한다.
3. UI 육안 확인과 polling 주기 캡처는 운영자 브라우저에서 한 번 더 확인한다.

---

## 2026-06-28 — Phase 2.5 macOS Docker E2E 검증

### 테스트 정보

- 날짜: 2026-06-28
- 작성자: 종민 (A / Vision AI)
- 브랜치: test/phase-2-5-docker-e2e-macos
- 환경: macOS, Docker Desktop 4.79.0, Docker Engine 29.5.3, Docker Compose v5.1.4
- 입력 소스: Mac 내장 웹캠 (device index 0), 640×480
- 모델: yolo26n.pt, infer-device: mps (auto)

### 실행 명령어

```bash
docker compose up --build -d

.venv/bin/python -m src.main \
  --source-type webcam \
  --source 0 \
  --api-url http://localhost:8000 \
  --model yolo26n.pt \
  --infer-device auto \
  --width 640 \
  --height 480 \
  --frames-limit 300 \
  --output outputs/a_docker_events.jsonl \
  --csv-output outputs/a_docker_events.csv \
  --summary-output outputs/a_docker_summary.json \
  --overlay-output outputs/a_docker_result.mp4 \
  --show
```

### Docker 실행 결과

| 항목 | 결과 |
| --- | --- |
| kidcafe-api | healthy |
| frontend | Up |
| FastAPI | http://localhost:8000 |
| React Dashboard | http://localhost:3000 |

### Vision AI 처리 결과

| 항목 | 결과 |
| --- | --- |
| processed_frames | 300 |
| dropped_frames | 0 |
| avg_fps | 약 11~15 FPS |
| events | 9건 (ENTER 5, EXIT 4) |
| pipeline 종료 코드 | 0 (정상) |

### API 확인

- `PUT /status/current`: source=webcam:0, frame_number=299, active_track_count=1 전송 확인
- `GET /events/recent`: 9건 반환 (ENTER / EXIT)
- `GET /summary`: total_events=9 정상
- SQLite DB: ENTER 5건, EXIT 4건 저장 확인

### Docker 재시작 후 DB 유지 확인

- `docker compose down` → `docker compose up -d` 후 `GET /summary`의 `total_events=9` 유지 확인
- SQLite DB의 ENTER 5건, EXIT 4건과 CurrentStatus 유지 확인
- bind mount(`./outputs:/app/outputs`) 구조 정상 동작 확인

### 결론

- 로컬 Vision AI → Docker FastAPI → SQLite → React Dashboard E2E 흐름 정상 동작
- macOS + Docker 환경에서 Phase 2.5 재현 가능한 실행 환경 검증 완료
- 웹캠 → YOLO + ByteTrack → 이벤트 9건 생성 → Docker FastAPI POST /events → SQLite 저장 전 구간 확인

---

## 2026-07-18 — Phase 3 B 공간 안전정책 적용 전후 비교

### 목적

동일한 파일 영상에서 `EventManager`의 zone 전이 확인시간을 비활성화한 기준과
Phase 3 기본값을 비교해 반복 이벤트 억제, 확정 지연, 처리량 영향을 확인한다.

현재 구현은 `foot_point` 좌표 자체에 smoothing을 적용하지 않는다. 매 프레임의
raw `foot_point`로 polygon 포함 여부를 계산한 뒤, 그 zone 판정 결과를 시간
조건으로 확인해 confirmed zone 상태를 안정화한다.

### 환경 및 방법

| 항목 | 값 |
| --- | --- |
| 실행 환경 | Windows, Python 가상환경 |
| 입력 | `data/videos/test.mp4` 전체 409프레임 |
| 입력 FPS | 25.0 |
| 모델 | `yolo26n.pt`, confidence 0.5 |
| zone | `data/zones/sample.json` (`danger`) |
| 안정화 비활성 기준 | 진입 0초, 이탈 0초, Track 소실 유예 0초 |
| Phase 3 기본값 | 진입 0.3초, 이탈 0.5초, Track 소실 유예 0.5초 |

빠른 반전은 동일 `track_id`·`zone_id`에서 서로 다른 이벤트가 13프레임
(약 0.52초) 이내 연속 발생한 경우로 계산했다. 영상 인코딩은 측정에서 제외하고
두 실행 모두 동일한 detection·tracking·geofencing 경로를 사용했다.

### 결과

| 지표 | 안정화 비활성 | Phase 3 기본값 |
| --- | ---: | ---: |
| 전체 이벤트 | 28 | 15 |
| ENTER | 14 | 8 |
| EXIT | 14 | 7 |
| 0.52초 이내 빠른 반전 | 12 | 0 |
| 실행시간 | 33.572초 | 29.157초 |
| 처리량 | 12.183 FPS | 14.027 FPS |

- 전체 이벤트는 28건에서 15건으로 46.4% 감소했다.
- 빠른 ENTER/EXIT 반전은 12건에서 0건으로 감소했다.
- 매칭된 ENTER 확정 지연은 모두 8프레임, 평균 0.32초였다.
- 매칭된 EXIT 확정 지연의 중앙값은 12프레임, 0.48초였다.
- Track 15는 소실 후 재관측 영향으로 EXIT가 29프레임 뒤 확정됐다.
- 안정화 실행에서 처리량 저하는 관찰되지 않았다. 단, 두 실행을 순차 수행해
  모델·파일 캐시의 영향을 받을 수 있으므로 FPS 상승을 정책의 성능 개선으로
  해석하지 않는다.

### 판정 및 한계

- 이 영상에서는 temporal hysteresis가 경계의 짧은 이벤트 반전을 억제했다.
- `sample.json`의 dwell 기준이 5초이므로 비교 구간에는
  `DANGER_ZONE_DWELL`이 발생하지 않았다.
- 샘플 영상에 zone 진입 ground truth가 없어 false positive·false negative
  정확도는 산출하지 않았다. annotation 기반 정량 평가는 Phase 3 통합 기간
  중 수행하지 못했으며 Phase 4 실제 카메라 데이터 평가로 이관한다.
- 실행 산출물은 `outputs/phase3-b-baseline.*`과
  `outputs/phase3-b-stabilized.*`이며 Git에 포함하지 않는다.

---

## 2026-07-18 — Phase 3 B SQLite 동시 쓰기 검증

`tests/test_sqlite_concurrency.py`에서 하나의 격리된 테스트 DB에 32개 worker를
동시에 시작했다.

- `FALL_SUSPECT` 이벤트 24건 동시 저장
- source가 서로 다른 CurrentStatus 8건 동시 upsert
- `event_confidence`와 `cause_json` 포함
- 이벤트 ID 중복·행 손실·`database is locked` 오류 없음
- events 24행과 current_status 8행 저장 확인

검증 명령어:

```bash
python -m pytest tests/test_sqlite_concurrency.py -q
```

결과: **1 passed**. 현재 연결 설정에서 검증 범위를 충족해 WAL이나 별도 timeout
설정은 추가하지 않았다.

---

## 2026-07-22 — Phase 3 A 낙상 통합 및 장애 안정성 검증

### 목적과 범위

동결된 낙상 PoC를 실제 실행 경로에 연결해 `FALL_SUSPECT`가 로컬 산출물,
FastAPI, SQLite, React Dashboard와 Live Frame까지 동일한 계약으로 전달되는지
확인했다. 실제 접촉 원인 후보의 정확도 평가는 이번 통합 범위에 포함하지
않았고, 고정 fixture로 `cause` 전파 계약만 검증했다.

### 환경과 고정 입력

| 항목 | 값 |
| --- | --- |
| OS / 하드웨어 | macOS 15.6.1, MacBook Air M1(8-core CPU, 7-core GPU), 16 GB |
| Python / 추론 장치 | Python 3.10.20, `auto` → CPU (`torch.backends.mps.is_available()=False`) |
| 주요 라이브러리 | torch 2.5.1, Ultralytics 8.4.56, OpenCV 4.8.1 |
| Docker | Engine 29.5.3, Compose v5.1.4 |
| API / Frontend | Docker Compose, `localhost:8000` / `localhost:3000` |
| 모델 | `yolo26n-pose.pt` + `fall_detector_v1.pt` |
| 설정 | `configs/fall_detection.json` |
| 낙상 입력 | CAUCAFall `S7_fall_backwards`, 720×480, 252프레임, 20 FPS |
| 성능 비교 | 동일 입력, 각 조건 사전 1회 warm-up 후 3회 |
| 측정 범위 | frame loop만 측정, 최초 30프레임 제외 steady-state 중앙값 |

실행별 SQLite 파일, 이벤트, 영상, metrics, 실패 JSONL은
`outputs/phase3_integration/` 아래에 격리했으며 Git에는 포함하지 않는다.

### E2E 결과

| 구간 | 결과 |
| --- | --- |
| 로컬 Vision AI | frame 83에서 `FALL_SUSPECT` 1건 생성 |
| 원인 근거 없음 | 실제 단일 인원 Event의 `cause=null` 유지 |
| FastAPI / SQLite | Event 필드와 `cause_json=NULL` 일치 |
| Dashboard | `FALL_SUSPECT`와 `원인 후보 없음` 표시 확인 |
| Live Frame | 실행 중 `200 image/jpeg`, 640×480, frame header 확인 |
| stale 정책 | 실행 종료 후 3초가 지난 frame은 계약대로 `204` 반환 |

`NEARBY_TRACK`은 고정 fixture(Event Track 10, 후보 Track 11)를 기존
`POST /events`에 전송했다. API 응답과 SQLite `cause_json`이 일치했고,
Dashboard 알림 기록에 `외부 접촉 의심 · Track #11`이 표시됐다. 이 확인은
전송·저장·표시 계약 검증이며 Vision attribution 정확도 결과가 아니다.

### 동결 지표 회귀

Signal Cache 재생으로 설정·상태머신 회귀 여부를 확인했다.

| 지표 | Development S1~6 | S7~8 tuning/diagnostic |
| --- | ---: | ---: |
| Recall | 83.3% | 100% |
| timely Recall | 66.7% | 90% |
| False alarm/min | 0.0 | 2.34 |
| 중복 Event 영상 | 0 | 0 |

S7~8은 반복 진단과 설정 선택에 사용했으므로 최종 Validation으로 해석하지
않는다. Subject 9~10 holdout은 열람하거나 실행하지 않았다.

### 능동 인원 성능과 API 장애

동일한 S7 낙상 영상에서 낙상 기능 OFF/API 정상, ON/API 정상,
ON/API 연결 실패(`localhost:8999`)를 각각 3회 측정했다.

| 조건 | FPS | avg latency | p95 latency | max latency | Event / 완료 |
| --- | ---: | ---: | ---: | ---: | --- |
| 낙상 OFF, API 정상 | 9.461 | 0.106초 | 0.177초 | 0.270초 | 252프레임 완료 |
| 낙상 ON, API 정상 | 5.098 | 0.196초 | 0.303초 | 0.461초 | frame 83 Event, 252프레임 완료 |
| 낙상 ON, API 장애 | 4.919 | 0.203초 | 0.345초 | 0.460초 | frame 83 Event, 252프레임 완료 |

- 낙상 기능 ON 비용은 정상 API 기준 FPS 46.1% 감소로 목표(20% 이내)를
  충족하지 못했다. PoseTracker와 보조 detector 비용을 포함한 결과이므로
  기능은 계속 opt-in·기본 비활성으로 유지하고 최적화는 Phase 4로 이관한다.
- API 장애의 추가 FPS 감소는 낙상 ON 정상 대비 3.5%로 목표(20% 이내)를
  충족했다. 세 장애 실행 모두 파이프라인이 끝까지 완료됐고, 최종 전송에
  실패한 frame 83 Event가 실행별 실패 JSONL에 `request_failed`, 2회 시도로
  보존됐다. 로컬 Event 산출물도 유지됐다.

계획된 `data/videos/test1.mp4 --frames-limit 600` 비교도 모든 조건에서
완료됐지만, 첫 600프레임에는 유효한 인원 Event가 없어 보조 모델의 lazy
loading 경로가 실행되지 않았다. 따라서 이 결과는 no-person idle path
안정성 확인에만 사용하고 낙상 기능 비용 계산에는 사용하지 않았다.

### 판정

- Vision AI → JSONL → FastAPI → SQLite → Dashboard / Live Frame 전파 통과
- `cause=null` 및 고정 `NEARBY_TRACK` 계약 전파 통과
- API 장애 중 비차단 처리와 실패 Event 보존 통과
- 동결 낙상 지표 회귀 없음
- 능동 인원 경로 FPS 목표 미달: 코드 블로커가 아닌 opt-in PoC 한계로 기록

---

## 2026-07-22 — FALL_SUSPECT MPS runtime 최적화

### 범위

통합 검증 이후 보조 detector 비용만 줄이는 별도 opt-in 프로파일을 측정했다.
모델·상태머신·Event/API 계약은 바꾸지 않았다. 안정적인 직립 Pose에서는 보조
detector를 생략하고, 불확실·하강·비정상 자세이면 즉시 fallback한 뒤 최대
3-frame 간격으로 실행한다.

### 회귀 결과

| 지표 | Development S1~6 | S7~8 tuning/diagnostic |
| --- | ---: | ---: |
| Recall | 83.3% | 100% |
| timely Recall | 66.7% | 90% |
| False alarm/min | 0.0 | 1.75 |
| 중복 Event 영상 | 0 | 0 |

기존 S7~8 FAR 2.34/min 대비 약 25% 감소했지만 운영 목표 0.2/min은 미달이다.
Subject 9~10 holdout은 사용하지 않았다.

### MPS 측정

`S7_fall_backwards`, 720×480, 252프레임을 API·Live Frame 없이 실행했다.
`infer-device`와 보조 모델 장치는 모두 MPS이며 최초 30프레임을 제외했다.
아래 값은 interval 후보 선택을 위한 각 1회 실행 결과다.

| 프로파일 | FPS | avg latency | p95 latency | max latency | Event frame |
| --- | ---: | ---: | ---: | ---: | ---: |
| 낙상 OFF | 14.571 | 0.0686초 | 0.0889초 | 0.1307초 | - |
| 낙상 ON, 매 frame | 7.663 | 0.1305초 | 0.2468초 | 0.4586초 | 83 |
| Pose gate + interval 2 | 12.498 | 0.0800초 | 0.1197초 | 0.1543초 | 87 |
| **Pose gate + interval 3** | **13.568** | **0.0737초** | **0.1178초** | **0.1581초** | **87** |
| Pose gate + interval 4 | 13.755 | 0.0727초 | 0.1150초 | 0.1900초 | 87 |

Interval `4`의 추가 이득은 실행 편차 수준이라 evidence를 더 자주 갱신하는
interval `3`을 채택했다. 선택 후 OFF/ON 순서를 교차해 각각 3회 재측정했다.

| 조건 | steady-state FPS 중앙값 | OFF 대비 하락률 | Event 재현 |
| --- | ---: | ---: | --- |
| 낙상 OFF | 14.5712 | - | 3회 모두 0건 |
| Pose gate + interval 3 | 13.511 | 7.3% | 3회 모두 frame 87에서 1건 |

절대 목표 11.66 FPS와 상대 하락률 20% 이내를 모두 통과했다.

이 측정은 앞 절의 CPU 기반 API E2E 3회 중앙값을 대체하지 않는다. MPS 로컬
파일 경로의 반복 최적화 검증이며, API·Live Frame 포함 반복 측정과 다른 장치는
Phase 4에서 확인한다. 기능과 최적화 옵션은 기본 비활성으로 유지한다.

---

## 2026-07-27 — Phase 3 종료 게이트 요약

### 범위

Phase 3 종료 전 최종 확인으로, 종료 문서 정리 직후 병합 전 마지막으로 회귀
스위트와 빌드·설정 검증을 다시 실행했다. 코드 변경은 없고 문서 갱신만 포함한다.

### 결과

| 항목 | 결과 |
| --- | --- |
| `git diff --check` | 공백 오류 없음 |
| `flake8 src tests` | 위반 없음 |
| `pytest -q` | 835 passed, 3 skipped |
| `frontend`: `npm ci && npm run build` | 통과 (dist 산출물 생성 확인) |
| `docker compose config --quiet` | 통과 |
| `git ls-files outputs` | `outputs/.gitkeep`만 추적 |

### 판정

- 회귀·빌드·설정 검증 전부 통과, 코드 블로커 없음
- Phase 3 범위: 공간 안전정책, `FALL_SUSPECT` PoC, `cause` 전파,
  Live Frame, AlertHistory 실 API 연동, API 장애 중 추론 지속 및 실패
  Event 보존, M1/MPS 낙상 runtime 최적화(7.3% FPS 하락) — 모두 통합·회귀
  확인 완료
- 낙상 오탐(FAR) 개선, 실제 접촉 원인 정확도, Subject 9~10 holdout,
  외부 데이터 재학습은 이번 게이트에 포함하지 않고 Phase 4로 이관한다
- 위 결과를 근거로 Phase 3 종료 조건을 충족한 것으로 판정한다
