# KidCafe Safety AI

Vision AI 기반 키즈카페 아동 안전 모니터링 시스템

한이음 드림업 프로젝트 (2026.04 ~ 2026.10)

![status](https://img.shields.io/badge/status-MVP_1_done-brightgreen)
![python](https://img.shields.io/badge/python-3.10-blue)
![tests](https://img.shields.io/badge/tests-pytest_passed-green)
![license](https://img.shields.io/badge/license-Internal-lightgrey)

---

## 개요

KidCafe Safety AI는 YOLO + ByteTrack + Geofencing 기반으로 위험구역 진입 및 장시간 체류를 감지하는 Vision AI 안전 모니터링 시스템이다.

현재 MVP 1단계 기준 목표는 **저장 영상 기반 end-to-end 검증**이다.

```text
저장 영상
→ 사람 탐지 / 추적
→ Zone 기반 ENTER / DWELL / EXIT 이벤트 생성
→ events.jsonl / events.csv / summary.json / result.mp4 저장
→ Streamlit 검증 대시보드에서 결과 확인
```

Streamlit 대시보드는 MVP 검증용 임시 UI이며, 실제 운영형 대시보드는 Phase 2 이후 React 기반으로 전환할 예정이다.

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
- 검증 영상: [Pexels 15385683](https://www.pexels.com/ko-kr/video/shopping-15385683/)
- 권장 해상도: 1920x1080 또는 1280x720
- 권장 길이: 10~30초

### 3. 실행

```bash
# 기본 실행
python -m src.main

# 전체 옵션
python -m src.main \
  --video data/videos/test.mp4 \
  --zones data/zones/sample.json \
  --output outputs/events.jsonl \
  --csv-output outputs/events.csv \
  --summary-output outputs/summary.json \
  --overlay-output outputs/result.mp4 \
  --conf 0.5 \
  --frames-limit 300 \
  --log-level INFO

# 도움말
python -m src.main --help
```

> `yolov8n.pt` 모델 파일은 Git에 포함하지 않는다. 최초 실행 시 Ultralytics가 자동 다운로드하며, 다운로드된 `.pt` 파일은 `.gitignore`에 의해 추적되지 않는다.

### 4. Streamlit 검증 대시보드

```bash
streamlit run src/visualization/app.py
```

### 5. 결과 확인

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

### 6. 테스트

```bash
pytest -q
```

---

## 프로젝트 구조

```
kidcafe-safety-monitoring/
├── src/
│   ├── common/              # 공통 타입 + 이벤트 IO/집계/분석 API
│   │   ├── types.py
│   │   ├── event_writer.py
│   │   ├── event_io.py
│   │   ├── event_time.py
│   │   ├── event_counter.py
│   │   ├── event_aggregator.py
│   │   ├── dwell_analyzer.py
│   │   ├── track_report.py
│   │   ├── insight_generator.py
│   │   └── pipeline_logging.py
│   ├── tracking/            # YOLO + ByteTrack
│   │   └── bytetrack_wrapper.py
│   ├── geofencing/          # Zone 판정
│   │   ├── zone_loader.py
│   │   └── zone_checker.py
│   ├── events/              # 상태머신
│   │   └── event_manager.py
│   ├── visualization/       # 결과 영상 + Streamlit 검증 대시보드
│   │   ├── video_overlay.py
│   │   ├── app.py
│   │   ├── dashboard_data.py
│   │   ├── charts.py
│   │   ├── event_charts.py
│   │   ├── track_charts.py
│   │   └── pages/
│   └── main.py              # 파이프라인 진입점
├── data/
│   ├── videos/              # 입력 영상 (.gitignore)
│   └── zones/               # Zone JSON
├── docs/
│   ├── interfaces.md        # 모듈 간 인터페이스 + A/B/C 산출물 계약
│   ├── decisions.md         # ADR 기록 (ADR-001 ~ ADR-009)
│   ├── roadmap.md           # Phase 1~5 개발 로드맵
│   ├── tracking_analysis.md
│   ├── conf_tuning.md
│   ├── model_benchmark.md
│   ├── dashboard_api.md
│   ├── dashboard_analysis.md
│   └── dashboard_mvp_summary.md
├── tests/
│   └── test_*.py
├── outputs/                 # 실행 결과 (.gitignore)
├── notebooks/               # 실험용
├── requirements.txt
└── README.md
```

---

## 역할 분담 (MVP 1단계)

| 팀원 | 담당 | 주력 모듈 |
|------|------|---------|
| **A** | Vision AI Backend + 결과 영상 | tracking, events, geofencing, video_overlay |
| **B** | Data Analysis + Pipeline 운영 | main.py, event_writer, event_aggregator, charts | 
| **C** | Streamlit 검증 대시보드 | visualization/app.py, visualization/pages | 

> ReID, Pose Estimation, Multi-camera는 **Phase 2 별도 모듈**로 확장

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

| 옵션 | 기본값 | 설명 |
|------|--------|------|
| `--video` | `data/videos/test.mp4` | 입력 영상 경로 |
| `--zones` | `data/zones/sample.json` | Zone 정의 JSON |
| `--output` | `outputs/events.jsonl` | 이벤트 출력 경로 |
| `--csv-output` | `outputs/events.csv` | CSV 이벤트 로그 출력 경로 |
| `--summary-output` | `outputs/summary.json` | KPI summary JSON 출력 경로 |
| `--overlay-output` | `outputs/result.mp4` | 결과 영상 출력 |
| `--conf` | `0.5` | YOLO confidence threshold (0~1) |
| `--frames-limit` | `None` | 처음 N프레임만 처리 (테스트용) |
| `--show` | `False` | 실시간 시각화 창 (cv2.imshow) |
| `--log-level` | `INFO` | 로그 레벨 (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |

---

## Dependencies

### Version Strategy

MVP 단계에서는 **재현성**과 **환경 통일**을 위해 핵심 의존성 버전 고정.

### Core

| 패키지 | 버전 | 용도 |
|--------|------|------|
| `ultralytics` | 8.0.206 | YOLO + ByteTrack |
| `opencv-python` | 4.8.1.78 | 영상 I/O + 시각화 |
| `shapely` | 2.0.1 | Polygon 판정 |
| `numpy` | 1.26.4 | 수치 연산 |
| `pandas` | 2.2.2 | 데이터 분석 (B) |
| `streamlit` | 1.34.0 | UI (C) |
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

## MVP 1단계 상태

MVP 1단계는 **파일 영상 기반 end-to-end 검증 버전**으로 종료한다.

| 영역 | 상태 |
|-----|------|
| YOLO + ByteTrack 탐지/추적 | Done |
| Zone JSON 로드 및 Geofencing | Done |
| ENTER / DWELL / EXIT 이벤트 생성 | Done |
| 결과 영상 `outputs/result.mp4` 생성 | Done |
| 이벤트 로그 `events.jsonl`, `events.csv` 생성 | Done |
| KPI summary `summary.json` 생성 | Done |
| Streamlit 검증 대시보드 | Done |
| IP 카메라 / RTSP 실시간 입력 | Phase 2 |
| FastAPI / DB / WebSocket | Phase 2 |
| React 운영 대시보드 | Phase 2 |
| ReID / Pose Estimation / Multi-camera | Phase 2 |

Phase 2 개발은 **2026-06-01부터 착수 예정**이며, 세부 개발 단계와 일정은 현재 정리 중이다.

---

## Architecture Decisions

주요 의사결정 기록 (전체: [`docs/decisions.md`](docs/decisions.md)):

### 관련 문서

- [`docs/roadmap.md`](docs/roadmap.md) — Phase 1~5 개발 로드맵
- [`docs/interfaces.md`](docs/interfaces.md) — 모듈 간 인터페이스 + A/B/C 산출물 계약
- [`docs/tracking_analysis.md`](docs/tracking_analysis.md) — Track ID 안정성 분석
- [`docs/conf_tuning.md`](docs/conf_tuning.md) — Confidence threshold 튜닝
- [`docs/model_benchmark.md`](docs/model_benchmark.md) — Phase 2 기준 모델 1차 비교

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

## 알려진 한계 (Phase 2로 이연)

현재 MVP에서 확인된 한계 — 모두 다음 단계에서 개선 예정:

| 한계 | 원인 | Phase 2 개선 방안 |
|------|------|----------------|
| CCTV 거리 탐지 약함 | YOLOv8n (MVP 경량 모델) | YOLO26n 1차 후보 검증 및 필요 시 모델 교체 |
| 작은 객체 bbox 깜빡임 | 작은 객체 confidence 흔들림 | 모델 업그레이드 + 후처리 |
| track_id 자주 변경 | ReID 없음 | OSNet 기반 ReID 도입 |
| 가려짐 후 재등장 시 ID 분리 | ByteTrack만으로는 한계 | StrongSORT 또는 ReID 보강 |
| Streamlit 일부 화면의 데모/후속 기능 | MVP 검증용 UI | React 운영 대시보드에서 재설계 |
| 필터/알림/자녀 리포트 일부 미완성 | Phase 2 기능 | FastAPI/React 연동 후 구현 |
> 상세 분석: [`docs/tracking_analysis.md`](docs/tracking_analysis.md)

---

## 참고 자료

- [Ultralytics YOLOv8 Docs](https://docs.ultralytics.com/)
- [ByteTrack 논문](https://arxiv.org/abs/2110.06864)
- [Shapely Docs](https://shapely.readthedocs.io/)
- [Streamlit Docs](https://docs.streamlit.io/)
- [검증 영상 (Pexels 15385683)](https://www.pexels.com/ko-kr/video/shopping-15385683/)

---

## License

한이음 드림업 프로젝트 결과물. 외부 사용 시 문의.
