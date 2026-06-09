# KidCafe Safety AI

Vision AI 기반 키즈카페 아동 안전 모니터링 시스템

한이음 드림업 프로젝트 (2026.04 ~ 2026.10)

![status](https://img.shields.io/badge/status-Phase_1.5_done-brightgreen)
![python](https://img.shields.io/badge/python-3.10-blue)
![tests](https://img.shields.io/badge/tests-pytest_passed-green)
![license](https://img.shields.io/badge/license-Internal-lightgrey)

---

## 개요

KidCafe Safety AI는 YOLO + ByteTrack + Geofencing 기반으로 위험구역 진입 및 장시간 체류를 감지하는 Vision AI 안전 모니터링 시스템이다.

**현재 상태: MVP 1차 완료 + Phase 1.5 완료**

```text
Vision AI Pipeline
→ Event Schema v1 (ENTER / DWELL / EXIT)
→ FastAPI + SQLite
→ React Dashboard (Phase 1.5 기준 UI)
```

> Streamlit 대시보드는 MVP 검증용으로 사용되었으며 현재는 비활성 상태다.
> React Dashboard (`frontend/`) 가 Phase 1.5 기준 운영 UI다.

---

## 빠른 시작

### 권장 환경
- Python 3.10.x
- macOS / Ubuntu tested

### 1. 환경 셋업

```bash
# 저장소 클론
git clone https://github.com/kidcafe-safety-ai/kidcafe-safety-monitoring.git
cd kidcafe-safety-monitoring

# 가상환경 생성 (Python 3.10 권장)
python3.10 -m venv .venv
source .venv/bin/activate          # macOS/Linux
# .venv\Scripts\activate           # Windows

# 패키지 설치
pip install -r requirements.txt
```

### 2. 테스트 영상 준비
검증용 영상을 `data/videos/test.mp4`에 배치합니다.
- 권장 해상도: 1920x1080 또는 1280x720
- 권장 길이: 10~30초

### 3. 실행

```bash
# 파일 영상 (기본)
python -m src.main --source-type file --source data/videos/test.mp4

# 웹캠 실시간
python -m src.main \
  --source-type webcam \
  --source 0 \
  --model yolo26n.pt \
  --infer-device auto \
  --width 640 --height 480 \
  --frames-limit 300 \
  --show

# RTSP IP 카메라 (--rtsp-alias 로 URL이 로그/이벤트에 노출되지 않음)
python -m src.main \
  --source-type rtsp \
  --source rtsp://user:pass@192.168.1.10/stream \
  --rtsp-alias camera_01 \
  --model yolo26n.pt \
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

> YOLO 모델 파일(`*.pt`)은 Git에 포함하지 않는다. 최초 실행 시 Ultralytics가 자동 다운로드하며, 다운로드된 `.pt` 파일은 `.gitignore`에 의해 추적되지 않는다.
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

### 6. 결과 확인

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

### 7. 테스트

```bash
pytest -q
```

---

## 프로젝트 구조

```
kidcafe-safety-monitoring/
├── src/
│   ├── api/                 # FastAPI 서버 (Phase 1.5 추가)
│   │   ├── main.py
│   │   ├── schemas.py
│   │   ├── database.py
│   │   ├── repositories.py
│   │   └── routers/
│   ├── common/              # 공통 타입 + 이벤트 IO/집계/분석 API
│   ├── tracking/            # YOLO + ByteTrack
│   ├── geofencing/          # Zone 판정
│   ├── events/              # 상태머신
│   ├── visualization/       # 결과 영상/차트 legacy 유틸 (Streamlit app/pages 종료)
│   └── main.py              # 파이프라인 진입점
├── frontend/                # React Dashboard (Phase 1.5 추가)
│   ├── src/
│   │   ├── pages/           # MonitoringPage, EventsPage
│   │   ├── components/      # KpiCard, EventTable, EventChart 등
│   │   ├── api/             # eventsApi.ts (mock → Phase 2에서 FastAPI 교체)
│   │   ├── mocks/           # Phase 1.5 mock 데이터
│   │   └── types/           # event.ts
│   └── package.json
├── scripts/                 # 벤치마크 도구 (Phase 1.5)
│   ├── run_benchmark.py
│   └── draw_zone.py
├── data/
│   ├── videos/              # 입력 영상 (.gitignore)
│   └── zones/               # Zone JSON
├── docs/
│   ├── interfaces.md        # A/B/C 공통 계약 (가장 중요)
│   ├── decisions.md         # ADR 기록
│   ├── roadmap.md           # Phase 로드맵
│   ├── api_contract.md      # B/C API 기준
│   ├── model_benchmark.md   # Phase 1.5 모델 비교 결과
│   ├── realtime_test.md     # Phase 2 실시간 실험 로그
│   └── ...
├── tests/
│   └── test_*.py
├── outputs/                 # 실행 결과 (.gitignore)
├── requirements.txt
└── README.md
```

---

## 역할 분담 (Phase 1.5 기준)

| 팀원 | 담당 | 주력 모듈 |
|------|------|---------|
| **A** | Vision AI / 모델 기준선 / 실시간 입력 준비 | tracking, events, geofencing, scripts/ |
| **B** | FastAPI / SQLite / Backend | src/api/ |
| **C** | React Dashboard | frontend/ |

> Phase 2: A는 실시간 입력 연결, B는 API 안정화, C는 mock → API 연동

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
| `--conf` | `0.5` | YOLO confidence threshold (0~1) |

### Zone / API

| 옵션 | 기본값 | 설명 |
|------|--------|------|
| `--zones` | `data/zones/sample.json` | Zone 정의 JSON |
| `--api-url` | `None` | FastAPI 서버 URL. 지정 시 이벤트/상태를 전송 (예: `http://localhost:8000`) |

### 출력

| 옵션 | 기본값 | 설명 |
|------|--------|------|
| `--output` | `outputs/events.jsonl` | 이벤트 출력 경로 |
| `--csv-output` | `outputs/events.csv` | CSV 이벤트 로그 출력 경로 |
| `--summary-output` | `outputs/summary.json` | KPI summary JSON 출력 경로 |
| `--overlay-output` | `outputs/result.mp4` | 결과 영상 출력 |

### 실행 제어

| 옵션 | 기본값 | 설명 |
|------|--------|------|
| `--frames-limit` | `None` | 처음 N프레임만 처리 (테스트용) |
| `--show` | `False` | 실시간 시각화 창 (`cv2.imshow`). 종료: `q` |
| `--log-level` | `INFO` | 로그 레벨 (`DEBUG` / `INFO` / `WARNING` / `ERROR`) |

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
| 웹캠 / RTSP 실시간 입력 연결 | Phase 2 |
| React mock → API 연동 | Phase 2 |
| Current Status API (`/status/current`) | Phase 2 |
| WebSocket 실시간 push | Phase 2.5 |
| ReID / 낙상 / 충돌 감지 | Phase 3 |

Phase 2 개발은 **2026-06-08 착수**. 핵심 목표: 웹캠 기반 end-to-end 실시간 연결.

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
| ADR-011 | Phase 2 실시간 갱신은 polling 우선 | WebSocket은 Phase 2.5 이후 |
| ADR-012 | Event 로그와 Current Status 분리 | 현재 인원은 Event 누적으로 계산 불가 |
| ADR-013 | Phase 2는 웹캠 기반 end-to-end 우선 | RTSP는 fallback 가능 |

---

## 협업 규칙

### Git
- **Branch**: `feature/*` 사용
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
| CCTV 거리 탐지 약함 | YOLOv8n (MVP 경량 모델) | Phase 2: YOLO26n 실시간 테스트 |
| 작은 객체 bbox 깜빡임 | 작은 객체 confidence 흔들림 | Phase 2: 모델 업그레이드 + 후처리 |
| track_id 자주 변경 | ReID 없음 | Phase 3: OSNet 기반 ReID 도입 |
| 가려짐 후 재등장 시 ID 분리 | ByteTrack만으로는 한계 | Phase 3: StrongSORT 또는 ReID 보강 |
| 필터 / 알림 / 자녀 리포트 | 운영 고도화 기능 | Phase 2.5 이후 우선순위 재검토 |
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
