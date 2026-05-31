# Track ID 안정성 분석 (MVP 1단계)

> **작성일**: 2026-05-17
> **작성자**: 정종민( A Vision AI Backend)
> **관련 문서**: [`README.md`](../README.md), [`interfaces.md`](interfaces.md), [`decisions.md`](decisions.md)

---

## 1. 목적

본 문서는 KidCafe Safety AI의 MVP 1단계에서 사용한 `YOLOv8n + ByteTrack` 기반 추적 결과를 분석하기 위한 문서이다.

현재 단계의 목표는 **완벽한 장기 ID 유지가 아니라**, 다음 전체 파이프라인이 실제 영상에서 동작하는지 확인하는 것이다.

```text
영상 입력
→ 사람 탐지
→ track_id 부여
→ 위험구역 판정
→ ENTER / DWELL / EXIT 이벤트 생성
→ result.mp4 시각화
```

---

## 2. 실험 환경

| 항목 | 내용 |
|------|------|
| 입력 영상 | `data/videos/test.mp4` |
| 영상 유형 | CCTV처럼 멀리서 촬영된 영상 |
| 해상도 | 1920x1080 |
| FPS | 25 |
| 모델 | `yolov8n.pt` |
| 추적기 | Ultralytics built-in ByteTrack (`model.track`) |
| Confidence threshold | 0.5 |
| Zone | `playground_bottom_right` |
| 출력 파일 | `outputs/events.jsonl`, `outputs/result.mp4` |

---

## 3. 현재 관찰 결과

실제 테스트 영상에서 다음 현상을 확인하였다.

### 3.1 track_id 변경 빈도

현재 MVP에서는 같은 사람으로 보이는 객체도 상황에 따라 `track_id`가 자주 변경된다.

주요 상황:

- 사람이 멀리 있어 bbox 크기가 작을 때
- 사람끼리 겹치거나 가려질 때
- 잠시 탐지가 끊겼다가 다시 탐지될 때
- 화면 가장자리 또는 복잡한 배경에서 움직일 때
- Confidence가 프레임마다 흔들릴 때

### 3.2 bbox 깜빡임

일부 프레임에서 사람 bbox가 유지되지 않고 깜빡이는 현상이 확인되었다.

원인:

- YOLOv8n은 매우 가벼운 모델이어서 작은 객체 탐지 성능이 제한적임
- CCTV처럼 멀리서 찍힌 사람은 픽셀 크기가 작아 Confidence가 낮아짐
- 탐지가 한두 프레임 끊기면 ByteTrack도 기존 ID를 유지하기 어려움

### 3.3 이벤트 증가 현상

`track_id`가 자주 변경되거나 bbox가 깜빡이면 동일 사람이 zone 근처에 있어도 ENTER / EXIT 이벤트가 여러 번 발생할 수 있다.

예시:

```text
Frame 97   ENTER | track_id=3
Frame 98   EXIT  | track_id=3
Frame 98   ENTER | track_id=2
```

이는 현재 MVP 구조에서 예상 가능한 한계이다.

---

## 4. MVP 단계에서의 허용 여부

현재 한계는 존재하지만, **MVP 1단계에서는 허용 가능**하다고 판단한다.

이유:

1. 현재 목표는 완벽한 ReID가 아니라 **전체 파이프라인 검증**이다.
2. 사람 탐지 → 위험구역 판정 → 이벤트 생성 → 결과 영상 저장 흐름은 정상 동작한다.
3. `outputs/events.jsonl`과 `outputs/result.mp4`가 생성되며, B/C가 이후 분석 및 UI 작업을 진행할 수 있다.
4. ID 안정성은 Phase 2에서 ReID를 도입해 개선하는 것이 더 적절하다.

---

## 5. 현재 구조의 한계

| 한계 | 원인 | 영향 |
|------|------|------|
| `track_id` 자주 변경 | ReID 없음 | 동일 인물이 여러 ID로 분리될 수 있음 |
| bbox 깜빡임 | YOLOv8n의 작은 객체 탐지 한계 | ENTER/EXIT 이벤트 증가 |
| 멀리 있는 사람 탐지 약함 | CCTV 거리 + 작은 픽셀 객체 | 일부 사람 누락 |
| 가려짐 후 재등장 시 ID 분리 | ByteTrack 단독 한계 | 장기 추적 어려움 |

---

## 6. Phase 2 개선 방향

MVP 이후 고도화 단계에서는 다음 개선이 필요하다.

### 6.1 모델 교체

현재 YOLOv8n은 속도는 빠르지만 작은 객체 탐지에 약하다.

개선 후보:

- YOLO26n (Phase 1.5 모델 benchmark 기준 1차 후보)
- YOLOv8s
- YOLOv8m
- 실제 키즈카페 CCTV 데이터로 fine-tuning

### 6.2 ReID 도입
현재 MVP에서는 ReID보다 전체 이벤트 파이프라인 안정화와 인터페이스 정리가 우선이라고 판단하였다.

장기 ID 유지를 위해 ReID 모듈 도입이 필요하다.

개선 후보:

- OSNet 기반 ReID
- StrongSORT
- BoT-SORT 검토

### 6.3 후처리 개선

이벤트 과다 발생을 줄이기 위해 다음 로직을 추가할 수 있다.

- ENTER/EXIT debounce
- 최소 유지 프레임 조건
- 짧은 탐지 끊김 보정
- Zone 경계 근처 hysteresis 적용

---

## 7. 결론

현재 `YOLOv8n + ByteTrack` 구조는 **MVP 1단계의 목표에는 적합**하다.

다만 CCTV처럼 멀리서 촬영된 실내 영상에서는 작은 사람 객체에 대해 bbox 깜빡임과 `track_id` 변경이 발생한다.

따라서 현재 단계에서는 **전체 파이프라인 검증용으로 사용**하고, Phase 2에서 다음 개선을 진행한다.

```text
YOLO26n 1차 후보 검증
+ 필요 시 YOLOv8s/m 추가 비교
+ ReID (OSNet / StrongSORT)
+ 이벤트 후처리 (debounce / hysteresis)
+ 실제 키즈카페 데이터 기반 재튜닝
```

이를 통해 **장기 ID 유지율과 이벤트 정확도를 높이는 방향**으로 고도화한다.

---

## 8. 한이음 수행계획서 매핑

본 문서의 한계 분석과 개선 방향은 한이음 수행계획서의 다음 기술과 연계된다.

| 수행계획서 명시 기술 | 현재 MVP 단계 | Phase 2 적용 |
|---------------------|--------------|-------------|
| YOLOv10/11 기반 객체 탐지 | YOLOv8n (MVP 경량 모델로 검증) | YOLO26n 1차 후보 검증 후 필요 시 YOLOv8s/m 또는 YOLOv10/11 비교 |
| ByteTrack/StrongSORT 다중 추적 | ByteTrack 단독 | StrongSORT 또는 ReID 결합 |
| OSNet 기반 경량 ReID | 미적용 | 도입 예정 |
| Cross-Camera ReID | 미적용 | 다중 카메라 환경에서 도입 |
| 룰 기반 이벤트 판단 로직 | ENTER/DWELL/EXIT 기본 구현 | debounce, hysteresis 등 정교화 |
