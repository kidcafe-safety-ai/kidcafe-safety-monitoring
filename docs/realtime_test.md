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
- C (USB 웹캠) 테스트 결과 수신 후 별도 섹션으로 추가 예정
