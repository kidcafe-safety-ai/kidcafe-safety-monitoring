# Kidcafe Safety AI

Vision AI 기반 키즈카페 아동 안전 모니터링 시스템

한이음 드림업 프로젝트 (2026.04 ~ 2026.10)

---

## 빠른 시작

### 권장 환경

- Python 3.10.x
- macOS / Ubuntu tested

### 환경 셋업

```bash
# 1. 저장소 클론
git clone https://github.com/kidcafe-safety-ai/kidcafe-safety-monitoring.git
cd kidcafe-safety-monitoring

# 2. 가상 환경 생성
python3.10 -m venv .venv
source .venv/bin/activate  # macOS/Linux
# .venv\Scripts\activate   # Windows

# 3. 패키지 설치
pip install -r requirements.txt
```

---

## 프로젝트 구조

```text
src/
├── common/          # 공통 타입
├── detection/       # YOLO 탐지 (A 담당)
├── tracking/        # 다중 객체 추적 (A 담당)
├── geofencing/      # 위험구역 판단 (B 담당)
├── events/          # 이벤트 상태머신 (B 담당)
├── visualization/   # Streamlit UI (C 담당)
└── main.py

data/
├── videos/          # 입력 영상
└── zones/           # 구역 정의 JSON

docs/
├── interfaces.md    # 모듈 간 인터페이스
└── decisions.md     # 아키텍처 결정 기록

outputs/             # 결과 (JSONL, CSV)
tests/               # 유닛 테스트
notebooks/           # 실험용
```

---

## 역할 분담

> 현재 구조와 역할 분담은 1차 MVP 기준이며,  
> ReID, Pose Estimation, Multi-camera Tracking은  
> 고도화 단계에서 별도 모듈로 확장한다.

| 팀원 | 담당 |
|------|------|
| A | Detection, Tracking (YOLO + ByteTrack) |
| B | Geofencing, Events (Zone + 상태머신) |
| C | Visualization (Streamlit UI) |

---

## 협업 규칙

### Git

- **Branch**: `feature/*` 사용
- **Commit**: `feat:`, `fix:`, `docs:`, `refactor:` 프리픽스
- **PR**: 최소 1명 리뷰 후 머지
- **main 브랜치 직접 push 금지**

### 작업

- **2시간 룰**: 막히면 즉시 공유
- **70% 원칙**: 70% 완성 후 PR
- **주차별 통합**: 매주 화요일 회의 전까지

---

## Dependencies

### Version Strategy

현재 MVP 단계에서는 팀 환경 통일과 재현성을 위해  
핵심 의존성 버전을 고정하여 사용한다.

#### Core Dependencies

- ultralytics==8.0.206
- opencv-python==4.8.1.78
- shapely==2.0.1
- numpy==1.26.4
- pandas==2.2.2
- streamlit==1.34.0
- matplotlib==3.8.4

#### Development / Testing

- pytest==8.2.0
- black==24.4.2
- flake8==7.0.0
- isort==5.13.2

> 추후 운영 환경 및 배포 단계에서  
> 일부 라이브러리는 범위 기반(`>=`) 전략으로 전환 가능
---

## 1차 MVP 일정

| 주 | 내용 |
|----|------|
| Week 0 | 폴더 구조, 환경 셋업 |
| Week 1 | Mob: YOLO + ByteTrack Hello World |
| Week 2 | 분담: 각 모듈 구현 |
| Week 3 | 통합, 이벤트 로직 |
| Week 4 | 안정화, 시연 |