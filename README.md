# KidCafe Safety AI

Vision AI 기반 키즈카페 아동 안전 모니터링 시스템

한이음 드림업 프로젝트 (2026.04-2026.10)

![status](https://img.shields.io/badge/status-Phase_4_active-blue)
![python](https://img.shields.io/badge/python-3.10-blue)
![tests](https://img.shields.io/badge/tests-pytest_passed-green)
![license](https://img.shields.io/badge/license-Internal-lightgrey)

---

## 개요

KidCafe Safety AI는 YOLO + ByteTrack + Geofencing 기반으로 위험구역 진입 및 장시간 체류를 감지하는 Vision AI 안전 모니터링 시스템이다.

**현재 상태: Phase 4 실제 키즈카페 촬영 기반 낙상 감지 고도화 완료**

현재 구현 기준(`v0.3.0-safety` 이후):

```text
Webcam / RTSP / File   ← 로컬 실행
→ YOLO26n + ByteTrack / PoseTracker
→ ENTER / DWELL / EXIT / ENTER_RESTRICTED / DANGER_ZONE_DWELL 이벤트
→ FallPipeline → FALL_SUSPECT + optional cause(NEARBY_TRACK)
→ AsyncEventDispatcher (비차단 전송, API 장애 시 로컬 보존)
→ FastAPI POST /events + PUT /status/current + Live Frame  ← Docker 실행 가능
→ SQLite 저장                                              ← Docker volume
→ React Dashboard (Live View·신규 Event·AlertHistory, REST polling)  ← Docker 실행 가능
```

검증 환경:

- macOS: 내장 웹캠 + Docker Compose (FastAPI·React·SQLite), Phase 4 E1 MPS E2E
- Windows: USB C920 웹캠 + Docker Compose (Phase 2.5 baseline)

Phase 4 E1 실행 코드는 Windows의 CPU/CUDA와 일반 파일 경로를 지원한다. 현재
E1 모델의 Windows 장비 E2E는 별도 최종 검증 대상으로 남아 있다.

> Streamlit 대시보드는 MVP 검증용으로 사용되었으며 현재는 비활성 상태다.
> React Dashboard (`frontend/`)는 REST polling 기반 운영 UI다. Docker frontend는 시연·검증용 Vite dev server로 운영 배포 구성은 아니다.

---

## 빠른 시작

### 권장 환경
- Python 3.10.x
- macOS / Windows / Ubuntu 지원

### 1. 환경 셋업

```bash
# 저장소 클론
git clone https://github.com/kidcafe-safety-ai/kidcafe-safety-monitoring.git
cd kidcafe-safety-monitoring

# 가상환경 생성 (Python 3.10 권장)
python3.10 -m venv .venv
source .venv/bin/activate

# 패키지 설치
pip install -r requirements.txt
```

Windows PowerShell:

```powershell
py -3.10 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

### 2. 테스트 영상 준비
검증용 영상을 `data/videos/test.mp4`에 배치합니다.
- 권장 해상도: 1920x1080 또는 1280x720
- 권장 길이: 10-30초

기본 CLI는 Phase 4 E1 낙상 모델을 사용한다. 제출·배포 패키지의 모델 artifact를
`outputs/fall_training/models/fall_detector_phase4_e1.pt`에 배치한다. 모델 없이
입력·Zone 경로만 확인할 때는 `--fall-detection-disabled`를 사용한다.

### 3. 실행

```bash
# 파일 영상 (E1 모델 준비 후 기본 실행)
python -m src.main --source-type file --source data/videos/test.mp4

# E1 모델 없이 입력·Zone 경로 확인
python -m src.main \
  --source-type file \
  --source data/videos/test.mp4 \
  --fall-detection-disabled

# 웹캠 실시간
python -m src.main \
  --source-type webcam \
  --source 0 \
  --infer-device auto \
  --width 640 --height 480 \
  --frames-limit 300 \
  --show

# RTSP IP 카메라 (--rtsp-alias 로 URL이 로그/이벤트에 노출되지 않음)
python -m src.main \
  --source-type rtsp \
  --source rtsp://user:pass@192.168.1.10/stream \
  --rtsp-alias camera_01 \
  --infer-device auto

# API 서버 포함 실행
python -m src.main \
  --source-type webcam \
  --source 0 \
  --api-url http://localhost:8000 \
  --frames-limit 300

# 도움말
python -m src.main --help
```

Windows PowerShell 기본 smoke 실행:

```powershell
python -m src.main --source-type file --source data/videos/test.mp4 --fall-detection-disabled
```

#### FALL_SUSPECT 실행

Phase 4 목표 키즈카페 구도에서 채택한 E1 낙상 모델이 기본 활성화된다.
PoseTracker, interval `3`, Pose NORMAL gate를 기본 프로파일로 사용한다.

```bash
python -m src.main \
  --source-type file \
  --source data/videos/test.mp4 \
  --api-url http://localhost:8000 \
  --live-frame-enabled

# M1/MPS에서 검증한 선택적 runtime 최적화 프로파일
python -m src.main \
  --source-type file \
  --source data/videos/test.mp4 \
  --infer-device mps \
  --fall-model-device mps \
  --api-url http://localhost:8000 \
  --live-frame-enabled

# 낙상 감지를 명시적으로 끄는 경량 실행
python -m src.main \
  --source-type file \
  --source data/videos/test.mp4 \
  --fall-detection-disabled
```

| 옵션 | 설명 |
|------|------|
| `--fall-detection-enabled` / `--fall-detection-disabled` | 기본 활성화된 `FALL_SUSPECT` 경로를 명시적으로 켜거나 끈다. 끄면 `yolo26n.pt` + ByteTracker 경로를 사용한다. |
| `--fall-profile` | 채택 모델 경로·SHA-256·활성 상태를 담은 동결 manifest. 기본값은 `configs/fall_e1_selected.json`이다. |
| `--fall-model-path` | 커스텀 `fall`/`nofall` 보조 detector 경로. 미지정 시 동결 profile의 모델을 사용한다. |
| `--fall-model-sha256` | 커스텀 모델의 SHA-256. `--fall-model-path`를 동결 모델과 다른 경로로 지정할 때 필수다. |
| `--fall-config` | 낙상 상태머신 설정 파일. 기본값은 `configs/fall_detection.json`이다. |
| `--fall-model-conf` / `--fall-model-iou-threshold` | 보조 detector confidence와 Track 매칭 IoU 임계값이다. 기본값은 각각 `0.5`, `0.3`이다. |
| `--fall-model-device` | 보조 detector 실행 장치. `auto`, `mps`, `cuda`, `cpu` 중 하나이며 기본값은 `auto`다. |
| `--fall-model-interval-frames` | 보조 detector 실행 간격이다. 기본값과 Phase 4 채택값은 `3`이다. |
| `--fall-pose-normal-gate-enabled` / `--fall-pose-normal-gate-disabled` | 모든 active Track이 안정적인 직립 Pose일 때 보조 detector 추론을 생략하는 gate를 켜거나 끈다. 기본 활성이다. |

`fall_detector_phase4_e1.pt`는 Git에 포함하지 않고 제출·배포 패키지의 모델
artifact로 별도 제공한다. 로컬 경로는
`outputs/fall_training/models/fall_detector_phase4_e1.pt`다. 파일을 받은 뒤에는
아래 SHA-256으로 동일한 모델인지 확인한다.

```bash
shasum -a 256 outputs/fall_training/models/fall_detector_phase4_e1.pt
# 41701c4686212447271f4dd81b71a14704b76cb9f38fe1c727d446477fbdd28b
```

Windows PowerShell:

```powershell
Get-FileHash outputs/fall_training/models/fall_detector_phase4_e1.pt -Algorithm SHA256
```

기본 CLI는 입력 소스를 열기 전에 동결 manifest의 모델 경로와 SHA-256을
검증한다. 모델 누락, 잘못된 profile 또는 hash 불일치가 있으면 실행을 중단한다.

E1은 실제 키즈카페의 목표 IP 카메라 구도에서 촬영한 성인 통제 재연 데이터로
fine-tuning하고, 학습 참여자와 분리한 데이터로 평가했다.

| 평가 항목 | 결과 |
| --- | ---: |
| 동일 diagnostic의 E0 → E1 Recall | 6.25% → 93.75% |
| 독립 참여자 test Recall / timely Recall | 93.3% / 93.3% |
| 독립 참여자 test FAR / 중복 Event | 0.0/min / 0건 |
| 주요 hard-negative 앉기 6편·줍기 7편 | false Event 0건 |

위 결과로 E1을 Phase 4 목표 환경 모델로 채택했다. 평가는 고정 카메라 1대와
통제된 성인 재연 범위이며, 장시간 RTSP와 다중 인원 Track·Cause는 별도 검증을
계속한다. 상세 분할과 동결값은 `docs/fall_evaluation.md` 및
`configs/fall_e1_selected.json`을 따른다.

Pose NORMAL gate와 interval `3`의 M1/MPS 단일 파일 steady-state 성능은 낙상 OFF
14.571 FPS, ON 13.511 FPS로 하락률 7.3%였다. 다른 장치와 장시간 RTSP 환경은
Phase 4 E2E에서 계속 확인한다.

> 기본 Ultralytics YOLO 모델 파일(`*.pt`)은 Git에 포함하지 않는다. 최초 실행 시 자동 다운로드되며, 다운로드된 `.pt` 파일은 `.gitignore`에 의해 추적되지 않는다. fine-tuned 낙상 보조 모델은 위 공유 위치에서 별도로 받아야 한다.
> Phase 2 기본 모델은 `yolo26n.pt`이며, `yolov8n.pt`는 MVP baseline/fallback으로 유지한다.

### 4. FastAPI 서버 실행

```bash
uvicorn src.api.main:app --reload --port 8000
# http://localhost:8000/docs
```

### 5. React Dashboard 실행

```bash
cd frontend
npm install
npm run dev
# http://localhost:5173

# 빌드
npm run build
```

### 6. Docker Compose 실행 (FastAPI + React + SQLite)

Vision AI는 로컬에서 실행하고, FastAPI·React·SQLite는 Docker Compose로 실행한다.

```bash
# .env 준비 (최초 1회)
cp .env.example .env

# 빌드 및 실행
docker compose up --build

# 백그라운드 실행
docker compose up --build -d

# 종료
docker compose down
```

| 서비스 | 주소 |
|--------|------|
| FastAPI | http://localhost:8000 |
| React Dashboard | http://localhost:3000 |

> Docker frontend 컨테이너는 Vite dev server(`npm run dev`)로 실행한다. 시연·통합 검증용이며 운영 배포 구성은 아니다.

Vision AI는 Docker 실행 중인 FastAPI로 이벤트를 전송한다.

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

### 7. 결과 확인

```bash
# 이벤트 로그
cat outputs/events.jsonl | head -5

# CSV / summary
head outputs/events.csv
cat outputs/summary.json

# 결과 영상 재생
open outputs/result.mp4              # macOS
# xdg-open outputs/result.mp4        # Linux
# start outputs/result.mp4           # Windows
```

### 8. 테스트

```bash
pytest -q
```

---

## 프로젝트 구조

```
kidcafe-safety-monitoring/
├── src/
│   ├── api/                 # FastAPI 서버
│   │   ├── main.py
│   │   ├── schemas.py
│   │   ├── database.py
│   │   ├── repositories.py
│   │   └── routers/
│   ├── common/              # 공통 타입 + 이벤트 IO/집계/분석 API + PipelineMetrics
│   ├── input/               # Webcam/RTSP/File 입력 소스
│   ├── tracking/            # YOLO + ByteTrack
│   ├── geofencing/          # Zone 판정
│   ├── events/              # 상태머신 (ENTER/EXIT/DWELL, ENTER_RESTRICTED, DANGER_ZONE_DWELL)
│   ├── safety/              # 낙상 상태머신·FallCauseAttributor·PoseNormalGate
│   ├── integrations/        # AsyncEventDispatcher, EventApiClient, Live Frame 비차단 전송
│   ├── visualization/       # 결과 영상/차트 legacy 유틸 (Streamlit app/pages 종료)
│   └── main.py              # 파이프라인 진입점
├── frontend/                # React Dashboard
│   ├── src/
│   │   ├── pages/           # Monitoring/Events/AlertHistory (API), Report/ZoneSettings (Mock)
│   │   ├── components/      # KpiCard, EventTable, EventChart, SystemSettingsModal 등
│   │   ├── api/             # eventsApi.ts (VITE_API_MODE 기반 mock/API 전환)
│   │   ├── mocks/           # mock 데이터
│   │   └── types/           # event.ts
│   ├── Dockerfile           # React 컨테이너 (Vite dev server)
│   └── package.json
├── Dockerfile.api           # FastAPI 컨테이너
├── docker-compose.yml       # FastAPI + React + SQLite volume
├── scripts/                 # annotation·학습·평가·Signal Cache 도구
│   ├── run_benchmark.py
│   ├── draw_zone.py
│   ├── generate_caucafall_annotations_v2.py
│   ├── train_fall_detector.py
│   ├── cache_fall_signals.py
│   ├── evaluate_fall.py
│   ├── evaluate_fall_from_cache.py
│   └── tracker_sweep.py
├── configs/                 # 낙상 상태머신·학습·데이터 분할 설정
│   ├── fall_detection.json
│   ├── caucafall_v5_split.json
│   └── camera_calibration/  # Phase 4 Homography calibration (기본 비활성)
├── data/
│   ├── videos/              # 입력 영상 (.gitignore)
│   └── zones/               # Zone JSON
├── docs/
│   ├── interfaces.md        # A/B/C 공통 계약 (가장 중요)
│   ├── decisions.md         # ADR 기록
│   ├── roadmap.md           # Phase 로드맵
│   ├── api_contract.md      # B/C API 기준
│   ├── model_benchmark.md   # Phase 1.5 모델 비교 결과
│   ├── docker_phase_2_5.md  # Docker 실행 가이드 (Phase 2.5)
│   ├── fall_evaluation.md   # 낙상 PoC 평가·튜닝·runtime 최적화 기록
│   ├── homography_calibration.md  # Phase 4 floor-plane 좌표계·측정 절차
│   ├── realtime_test.md     # Phase 2-3 실시간 실험 로그
│   └── ...
├── tests/
│   └── test_*.py
├── outputs/                 # 실행 결과 (.gitignore)
├── requirements.txt
└── README.md
```

---

## 역할 분담 (Phase 3 완료 기준)

| 팀원 | 담당 | 주력 모듈 |
|------|------|---------|
| **A** | Vision AI / 실시간 입력 파이프라인 | tracking, events, geofencing, input, safety, integrations, scripts/ |
| **B** | FastAPI / SQLite / Backend API | src/api/ |
| **C** | React Dashboard / API 연동 | frontend/ |

---

## Tests

```bash
# 전체 테스트
pytest -v

# 특정 모듈만
pytest tests/test_events.py -v
pytest tests/test_geofencing.py -v

# 커버리지 포함
pytest --cov=src --cov-report=term-missing
```

---

## 명령어 옵션 상세

### 입력 소스

| 옵션 | 기본값 | 설명 |
|------|--------|------|
| `--source-type` | `file` | 입력 소스 종류 (`file` / `webcam` / `rtsp`) |
| `--source` | `None` | 소스 경로 또는 ID. file: 파일 경로, webcam: 카메라 인덱스(0), rtsp: URL |
| `--video` | `data/videos/test.mp4` | [레거시] 파일 영상 경로. `--source-type file` 일 때 `--source` 미지정 시 사용 |
| `--width` | `None` | 웹캠 가로 해상도 요청 (예: `640`) |
| `--height` | `None` | 웹캠 세로 해상도 요청 (예: `480`) |
| `--rtsp-alias` | `None` | RTSP source_id 별칭. 지정 시 URL 대신 이 값이 이벤트/로그에 기록됨 (예: `camera_01`) |

### 모델 / 추론

| 옵션 | 기본값 | 설명 |
|------|--------|------|
| `--model` | `yolo26n.pt` | YOLO 모델 경로 |
| `--infer-device` | `auto` | 추론 장치 (`auto` / `mps` / `cuda` / `cpu`) |
| `--conf` | `0.5` | YOLO confidence threshold (0-1) |

### Zone / API

| 옵션 | 기본값 | 설명 |
|------|--------|------|
| `--zones` | `data/zones/sample.json` | Zone 정의 JSON |
| `--api-url` | `None` | FastAPI 서버 URL. 지정 시 이벤트/상태를 전송 (예: `http://localhost:8000`) |
| `--api-failed-events-output` | `outputs/api_failed_events.jsonl` | API 최종 전송 실패 Event JSONL 경로 |

`--zones` 기본값은 기존 단독 실행과의 하위 호환을 위해
`data/zones/sample.json`을 유지한다. Phase 4 Zone Settings 통합 실행에서는
setup 단계에서 seed를 `outputs/zones_runtime.json`으로 복사한 뒤 Vision AI에도
`--zones outputs/zones_runtime.json`을 명시해야 한다. Zone 저장 후에는 Vision
AI를 재시작해 변경 내용을 적용한다.

### 출력

| 옵션 | 기본값 | 설명 |
|------|--------|------|
| `--output` | `outputs/events.jsonl` | 이벤트 출력 경로 |
| `--csv-output` | `outputs/events.csv` | CSV 이벤트 로그 출력 경로 |
| `--summary-output` | `outputs/summary.json` | KPI summary JSON 출력 경로 |
| `--overlay-output` | `outputs/result.mp4` | 결과 영상 출력 |
| `--metrics-output` | `None` | frame-loop FPS/latency JSON 출력. 미지정 시 생성하지 않음 |

### 실행 제어

| 옵션 | 기본값 | 설명 |
|------|--------|------|
| `--frames-limit` | `None` | 처음 N프레임만 처리 (테스트용) |
| `--show` | `False` | 실시간 시각화 창 (`cv2.imshow`). 종료: `q` |
| `--log-level` | `INFO` | 로그 레벨 (`DEBUG` / `INFO` / `WARNING` / `ERROR`) |

`--metrics-output`은 모델 초기화와 종료 시 API queue flush를 제외한 프레임 루프를
측정한다. 전체 프레임 지표와 최초 30프레임을 제외한 steady-state 지표를 함께
기록하므로, 같은 입력·프레임 수·출력 설정으로 실행한 결과끼리 비교해야 한다.

---

## Dependencies

### Version Strategy

재현성과 환경 통일을 위해 핵심 의존성 버전을 고정한다.

### Core

| 패키지 | 버전 | 용도 |
|--------|------|------|
| `ultralytics` | 8.4.56 | YOLO + ByteTrack |
| `opencv-python` | 4.8.1.78 | 영상 I/O + 시각화 |
| `shapely` | 2.0.1 | Polygon 판정 |
| `numpy` | 1.26.4 | 수치 연산 |
| `pandas` | 2.2.2 | 데이터 분석 (B) |
| `streamlit` | 1.34.0 | MVP legacy visualization utilities |
| `matplotlib` | 3.8.4 | 차트 (B) |
| `torch` | 2.5.1 | YOLO 백엔드 (ADR-002) |

### Dev/Test

| 패키지 | 버전 |
|--------|------|
| `pytest` | 8.2.0 |
| `pytest-cov` | 5.0.0 |
| `black` | 24.4.2 |
| `isort` | 5.13.2 |
| `flake8` | 7.0.0 |

---

## 개발 현황

| 영역 | 상태 |
|-----|------|
| YOLO + ByteTrack 탐지/추적 | Done — MVP |
| Zone JSON 로드 및 Geofencing | Done — MVP |
| ENTER / DWELL / EXIT 이벤트 생성 | Done — MVP |
| 이벤트 로그 `events.jsonl`, `events.csv` 생성 | Done — MVP |
| Streamlit 검증 대시보드 | Done — MVP (검증용 종료) |
| YOLO 모델 1차 비교 (YOLO26n 선정) | Done — Phase 1.5 |
| FastAPI + SQLite 최소 API | Done — Phase 1.5 |
| React mock Dashboard 2페이지 | Done — Phase 1.5 |
| 실시간 입력 인터페이스 초안 | Done — Phase 1.5 |
| 웹캠 실시간 입력 연결 | Done — Phase 2 |
| RTSPSource 인터페이스 | 구현 완료, 실장비 검증 보류 |
| React mock → API 연동 | Done — Phase 2 |
| Current Status API (`/status/current`) | Done — Phase 2 |
| React Dashboard API mode 안정화 | Done — Phase 2.5 |
| Docker Compose (FastAPI·React·SQLite) | Done — Phase 2.5 |
| 내장 웹캠 E2E 안정화 (macOS) | Done — Phase 2.5 |
| USB C920 E2E 테스트 (Windows) | Done — Phase 2.5 |
| React Live View (영상 영역) | Done — Phase 3 (latest-frame polling) |
| AlertHistory 실제 API 읽기 연동 | Done — Phase 3 |
| WebSocket 실시간 push | Phase 4 이후 필요성 기반 재검토 |
| FALL_SUSPECT 낙상 감지 | Done — Phase 4 E1 목표 환경 모델 채택 및 기본 활성화, A03 Recall·timely Recall 93.3%, FAR 0.0/min |
| FALL_SUSPECT.cause 외부 접촉 원인 후보 추정 | Done — Phase 3 (근접·접근 근거 기반 PoC, 정량 정확도 미검증) |
| Phase 4 계약·평가 프로토콜 | Done — Contract v1·`phase4_fall_eval_v1` 동결 |
| 낙상 오탐 개선(hard-negative 재학습, 외부·촬영 데이터) | Done — Phase 4 E1 목표 환경 채택 |
| 경량 temporal classifier | E1과 실제 촬영 결과가 조건을 충족할 때만 검토 |
| BoT-SORT / StrongSORT / ReID | 실제 Event 오류를 유발하는 ID switch가 반복될 때만 검토 |
| Homography floor-plane Zone | Phase 4 기본 비활성 PoC |
| Zone Settings 저장·Report 실제 연동 | Phase 4 |

Phase 3에서 공간 안전정책 temporal hysteresis, `FALL_SUSPECT`/`cause` opt-in PoC와
런타임 통합, AlertHistory 실제 연동을 완료했다. 낙상 오탐 개선(hard-negative
재학습과 외부·촬영 데이터 검증)과 Subject 9-10 최종 holdout은 Phase 4로
이관한다. temporal classifier는 E1 이후에도 같은 문제가 실제 촬영에서
재현될 때만 조건부로 검토한다.

Phase 4는 계약과 평가 프로토콜을 먼저 동결한 뒤 실제 촬영 데이터로 개선안을
선택한다. 일정은 [`docs/roadmap.md`](docs/roadmap.md), 구현 계약은
[`docs/api_contract.md`](docs/api_contract.md), 평가 기준은
[`docs/fall_evaluation.md`](docs/fall_evaluation.md)를 따른다.

---

## Architecture Decisions

주요 의사결정 기록 (전체: [`docs/decisions.md`](docs/decisions.md)):

| ADR | 결정 | 사유 |
|-----|------|------|
| ADR-001 | Ultralytics built-in tracking 채택 | BoxMot API 불일치 |
| ADR-002 | PyTorch 2.5.1 버전 고정 | YOLO weights_only 호환성 |
| ADR-003 | shapely `covers()` 사용 | 경계 위 점 포함 (contains 대신) |
| ADR-004 | EventManager(zones, fps) | DWELL 구현 위한 Breaking Change |
| ADR-005 | timestamp 영상 시간 기준 | 시스템 시간 → HH:MM:SS.mmm |
| ADR-006 | mp4v 코덱 채택 | macOS/Linux 호환성 |
| ADR-007 | YOLOv8n + ByteTrack MVP 채택 | 전체 파이프라인 우선 검증 |
| ADR-008 | Dashboard API 모듈 분리 및 요약 출력 추가 | C 대시보드 연동을 위한 API/출력 확장 |
| ADR-009 | 파일 영상 기반 MVP 1차 종료 및 Phase 2 분리 | Streamlit 검증용 확정, React/FastAPI는 Phase 2 |
| ADR-010 | Streamlit 종료 및 React Dashboard 전환 | Phase 1.5 운영 UI 확정 |
| ADR-011 | Phase 2/2.5 실시간 갱신은 polling 유지 | WebSocket은 Phase 4 이후 필요성 기반 재검토 |
| ADR-012 | Event 로그와 Current Status 분리 | 현재 인원은 Event 누적으로 계산 불가 |
| ADR-013 | Phase 2는 웹캠 기반 end-to-end 우선 | RTSP는 fallback 가능 |
| ADR-014 | Phase 2.5 제한적 Docker 도입 | 운영 배포 아닌 실행 환경 통일과 시연 재현성 확보 |
| ADR-015 | Live View latest-frame polling | WebSocket·MJPEG 대비 구현 단순, FastAPI 단일 worker에 적합 |
| ADR-016 | FALL_SUSPECT.cause 기반 외부 접촉 원인 후보 기록 | 독립 COLLISION_SUSPECT는 오탐 제어 어려움, 낙상 확정 후 소급 조회가 실용적 |
| ADR-017 | AsyncEventDispatcher 기반 비차단 전송 | API 장애 시 추론 FPS 저하 방지, EventApiClient는 감싸는 구조로 유지 |
| ADR-018 | Phase 3 인증/인가 경계만 정의, 구현은 Phase 4 이관 | 계약 확정이 우선, 인증은 배포 단계 관심사 |
| ADR-019 | 공간 안전정책 temporal hysteresis | 경계 진동을 즉시 Event로 확정하지 않고 시간 기반 상태를 사용 |
| ADR-020 | Track ID 안정화 후 임계값 게이트 추가 중단 | 확인된 Recall 손실을 피하고 다음 정확도 개선을 데이터·모델 문제로 분리 |
| ADR-021 | opt-in Pose NORMAL 추론 스케줄링 | 불확실 구간은 원래 경로를 유지하면서 안정적 정상 구간의 보조 모델 비용 절감 |
| ADR-022 | Phase 4 계약·평가 프로토콜 선행 동결 | A/B/C 병렬 구현과 S9-10 holdout 오염 방지 |
| ADR-023 | Homography 기본 비활성·조건부 채택 | 실제 Zone 정확도 개선과 운영 비용을 측정한 뒤 production 여부 결정 |
| ADR-024 | 목표 카메라 E1 낙상 모델 채택 | 실제 키즈카페 actor-disjoint 평가를 근거로 기본 활성 프로파일 동결 |

---

## 협업 규칙

### Git
- **Branch**: `feature/*`, `docs/*`, `test/*`, `chore/*`, `integration/*` 사용
- **Commit**: Conventional Commits (`feat:`, `fix:`, `docs:`, `refactor:`, `chore:`)
- **PR**: 최소 1명 리뷰 후 머지
- **main 직접 push 금지**

### 작업
- **2시간 룰**: 막히면 즉시 팀에 공유
- **70% 원칙**: 70% 완성 후 PR
- **주차별 통합**: 매주 화요일 회의 전까지

---

## 알려진 한계 및 개선 계획

| 한계 | 원인 | 개선 계획 |
|------|------|----------------|
| 원거리·소형 객체 탐지 한계 | 경량 모델 및 촬영 환경 한계 | Phase 4: 라벨 데이터 평가 및 fine-tuning 검토 |
| 작은 객체 bbox 깜빡임 | 작은 객체 confidence 흔들림 | Phase 3 범위에서 미착수 — Phase 4: 후처리 보강 |
| track_id 자주 변경 | ReID 없음 | 실제 Event 오류를 유발하면 Phase 4에서 BoT-SORT부터 조건부 비교 |
| 가려짐 후 재등장 시 ID 분리 | ByteTrack만으로는 한계 | handoff로 해결되지 않는 Event 오류가 반복될 때만 ReID 후속 검토 |
| ENTER/EXIT 경계 흔들림 | zone 경계 foot_point 진동 | Phase 3에서 temporal hysteresis 적용 완료, 실제 카메라 재튜닝은 Phase 4 |
| 낙상 처리량 비용 | PoseTracker와 보조 detector를 함께 실행 | Pose NORMAL gate+interval 3을 기본 적용하고 다른 장치·API E2E를 계속 검증 |
| 카메라 구도별 성능 차이 | 구도·행동 분포 차이 | 실제 키즈카페 A03 기준 E1을 채택하고 다른 구도는 별도 검증 |
| 알림 조치 상태·리포트·설정 저장 미연동 | 조치 API 미구현, 일부 화면 Mock | Phase 4에서 Zone·Report를 연동하고 알림 조치 저장은 후속 범위 유지 |
> 상세 분석: [`docs/tracking_analysis.md`](docs/tracking_analysis.md)

---

## 참고 자료

- [Ultralytics YOLO Docs](https://docs.ultralytics.com/)
- [ByteTrack 논문](https://arxiv.org/abs/2110.06864)
- [Shapely Docs](https://shapely.readthedocs.io/)
- [FastAPI Docs](https://fastapi.tiangolo.com/)
- [React Docs](https://react.dev/)

---

## License

한이음 드림업 프로젝트 결과물. 외부 사용 시 문의.
