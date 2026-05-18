# Architecture Decision Records

## ADR-001: Tracking 라이브러리로 Ultralytics built-in 채택

**Date**: 2026-05-15
**Status**: Accepted

### Context
다중 객체 추적을 위해 ByteTrack 사용 결정.

### Options Considered

**Option 1: boxmot (별도 라이브러리)**
-  19.x / 10.x 버전 API 구조 변경
-  `create_tracker()` 필수 인자 요구
-  ByteTrack 직접 import 불가
-  버전별 API 불일치

**Option 2: Ultralytics built-in tracking**  채택
-  `model.track()` 한 줄로 detection + tracking 통합
-  별도 라이브러리 없이 안정 동작
-  ByteTrack/BotSort 둘 다 지원

### Decision
MVP 단계에서 Ultralytics built-in tracking 사용.

### Consequences
- 환경 설정 부담 감소
- `src/detection/yolo_detector.py`는 제거 (ByteTracker가 detection까지 통합)
- 트래커 세부 튜닝 어려울 경우 ADR-004로 재검토

### References
- 검증 영상: [Pexels 856731](https://www.pexels.com/video/kids-playing-at-the-playground-856731/)
- 검증 결과: bbox + track_id 정상 출력, 간헐적 ID 변경은 MVP 범위 허용

---

## ADR-002: PyTorch 2.5.1 버전 고정

**Date**: 2026-05-15
**Status**: Accepted

### Context
YOLO 모델 로딩 시 PyTorch 2.6+에서 `weights_only` 관련 `UnpicklingError` 발생.

### Decision
- `torch==2.5.1`
- `torchvision==0.20.1`
- `torchaudio==2.5.1`

### Consequences
-  YOLO 모델 안정 로딩
-  추후 PyTorch 2.6+ 호환성 재검토 시 ADR-005로 기록

---

## ADR-003: shapely covers() 사용 (contains 대신)

**Date**: 2026-05-15
**Status**: Accepted

### Context
Track의 발 위치가 Zone polygon 안에 있는지 판정.

### Decision
`polygon.covers(point)` 사용.

### Reason
- `contains()`는 경계선 위 점을 False로 처리
- 픽셀 → 정규화 변환의 부동소수점 오차로 경계에 걸리는 경우 흔함
- `covers()`는 경계 위도 True

### Consequences
-  Zone 경계에서 누락 방지

---

## ADR-004: EventManager 시그니처 변경 (Breaking Change)

**Date**: 2026-05-17
**Status**: Accepted

### Context
DWELL 이벤트 구현 시 zone별 dwell_threshold_sec와 FPS 정보가 필요해졌다.

기존 EventManager() 구조에서는:

* zone별 체류 임계시간 접근 불가
* 영상 시간 기준 timestamp 계산 불가

### Decision

EventManager.__init__(zones, fps) 형태로 시그니처 변경.

### Migration

# Before
event_manager = EventManager()
# After
event_manager = EventManager(zones=zones, fps=fps)

### Consequences
* DWELL 이벤트 구현 가능
* zone별 체류 규칙 적용 가능
* 영상 시간 기반 timestamp 계산 가능
* 기존 코드와 호환되지 않는 Breaking Change 발생

---

## ADR-005: timestamp를 영상 시간 기준으로 통일

**Date**: 2026-05-17
**Status**: Accepted

### Context
기존 datetime.now() 기반 시스템 시간은 영상 시점과 동기화되지 않았다.

예:
* 영상 시작 후 8초 시점 이벤트라도
* 실제 저장 시간은 현재 PC 시간으로 기록됨

이 경우:
* 영상 ↔ 이벤트 동기화 어려움
* 타임라인 차트 구성 어려움
* Streamlit 모니터링 페이지에서 특정 이벤트 시점 탐색 어려움

### Decision
timestamp를 frame_number / fps 기반의 영상 상대 시간으로 통일.
형식:
HH:MM:SS.mmm

예:
00:00:08.500

### Consequences
* 영상 시점 ↔ 이벤트 완전 동기화 가능
* B의 통계 차트 X축 시간 데이터 활용 가능
* C의 모니터링 페이지에서 이벤트 탐색 가능
* 실제 처리 시각이 필요하면 processed_at 별도 필드 필요 (Phase 2)

---

## ADR-006: 결과 영상 코덱으로 mp4v 채택
**Date**: 2026-05-17
**Status**: Accepted

### Context
OpenCV VideoWriter를 사용해 결과 영상(result.mp4)을 저장할 때 코덱 선택 필요.

후보:
* mp4v
* avc1 / h264
* MJPG

### Decision
MVP 단계에서는 mp4v 코덱 사용.

### Reason
* macOS / Linux 환경 호환성 우수
* OpenCV 기본 설치만으로 동작
* FFmpeg 별도 설치 불필요
* 팀원 로컬 환경에서 바로 실행 가능
* 시연용 품질로 충분

### Consequences
* 환경 의존성 최소화
* 결과 영상 즉시 생성 가능
* h264 대비 압축률 낮음
* 장기 저장/배포용은 추후 재검토 필요

---

## ADR-007: 1차 MVP 탐지 모델은 YOLOv8n + ByteTrack 조합 사용
**Date**: 2026-05-17
**Status**: Accepted

### Context
현재 프로젝트의 1차 목표는:
* 사람 탐지
* 위험구역 판정
* ENTER/DWELL/EXIT 이벤트 생성
* 결과 영상 시각화

실제 테스트 결과:
* CCTV처럼 멀리 촬영된 영상에서는 사람 bbox가 일부 프레임에서 끊김
* 작은 객체 탐지 성능 제한 존재
* track_id가 자주 변경되는 현상 발생

### Decision
1차 MVP에서는:
* YOLOv8n
* Ultralytics built-in ByteTrack

### Reason
* 구현 속도가 빠름
* 로컬 환경에서도 충분히 실행 가능
* Ultralytics track() API 활용 가능
* MVP 수준의 파이프라인 검증에는 충분한 성능
* 팀 개발 속도와 안정성을 우선 고려

### Limitations
* 원거리 CCTV 영상에서 작은 사람 탐지 약함
* bbox 깜빡임 존재
* 가려짐/재등장 시 ID 변경 발생
* ByteTrack만으로 장기 ID 유지 어려움
* ReID 기능 부재

### Future Work
* YOLOv8s / YOLOv8m 이상 모델 검토
* ReID(OSNet / StrongSORT) 적용
* 작은 객체 탐지 개선
* 장기 track_id 유지 안정화
* 실제 키즈카페 CCTV 데이터 기반

---