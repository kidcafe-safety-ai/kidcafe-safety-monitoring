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

**Date**: 2026-05-XX
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

**Date**: 2026-05-XX
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