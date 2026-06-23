# Realtime Test Log

Phase 2 실시간 입력 실험 기록 문서.
테스트마다 아래 양식을 복사해서 날짜 기준으로 추가한다.

---

## 양식

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
