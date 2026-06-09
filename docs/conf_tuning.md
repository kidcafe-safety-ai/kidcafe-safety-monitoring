# Confidence Threshold 정성 튜닝 기록

> **작성일**: 2026-05-17
> **작성자**: 정종민( A Vision AI Backend)
> **관련 문서**: [`README.md`](../README.md), [`interfaces.md`](interfaces.md), [`tracking_analysis.md`](tracking_analysis.md), [`decisions.md`](decisions.md)

---

## 1. 목적

YOLOv8n 기반 사람 탐지에서 **confidence threshold** 값에 따른 탐지 결과 차이를 비교하고, MVP 1단계에서 사용할 기본값을 정하기 위해 작성한다.

---

## 2. 실험 환경

| 항목 | 내용 |
|------|------|
| 입력 영상 | 초기 검증 영상 (파일 영상 기반 MVP 검증용) |
| 해상도 | 1920x1080 |
| FPS | 25 |
| 모델 | `yolov8n.pt` |
| 추적기 | Ultralytics built-in ByteTrack |
| Zone | `playground_bottom_right` |
| 출력 파일 | `outputs/events.jsonl`, `outputs/result.mp4` |

---

## 3. 실험 방법
본 실험은 정량 mAP 평가가 아니라 MVP 영상 기준 정성 관찰 실험이다.
각 confidence 값에 대해 동일한 영상을 처리하며, 다음 명령어로 실행한다.

```bash
# conf 0.3
python -m src.main --conf 0.3

# conf 0.5
python -m src.main --conf 0.5

# conf 0.7
python -m src.main --conf 0.7
```

각 실행 후 `outputs/result.mp4`를 시청하며 다음을 정성적으로 관찰한다.

- 사람 bbox 안정성 (깜빡임 여부)
- `track_id` 변경 빈도
- ENTER / DWELL / EXIT 이벤트 발생 횟수
- 멀리 있는 사람 탐지 여부
- 오탐 (사람이 아닌 객체 탐지) 여부

---

## 4. 비교 결과

| Conf | 관찰 결과 | 장점 | 단점 | 판단 |
|------|----------|------|------|------|
| **0.3** | 더 많은 사람을 잡지만 bbox가 흔들리고 이벤트가 많아짐 | Recall 높음 | 오탐/깜빡임 증가 | 실험용 |
| **0.5** | 탐지 수와 안정성의 균형이 가장 좋음 | 균형적 | 작은 객체 일부 누락 | **기본값 채택** |
| **0.7** | 확실한 사람만 탐지됨 | 오탐 감소 | 멀리 있는 사람 누락 증가 | 보수적 설정 |

---

## 5. 시각적 관찰 상세

### 5.1 Conf 0.3 — 낮은 임계

- 멀리 있는 작은 사람도 탐지
- 그림자, 배경 객체를 사람으로 오탐
- bbox 위치가 프레임마다 흔들림 (깜빡임)
- `track_id`가 자주 분리되어 ENTER/EXIT 이벤트 과다 발생

### 5.2 Conf 0.5 — 표준 임계 

- 명확하게 보이는 사람은 거의 모두 탐지
- bbox 안정성 양호
- 오탐 거의 없음
- 멀리 있는 사람은 가끔 누락
- 가려졌다 재등장 시 `track_id` 새로 부여

### 5.3 Conf 0.7 — 높은 임계

- 탐지된 객체는 거의 모두 정확
- 작은/멀리 있는 사람 자주 누락
- ENTER 이벤트 발생 빈도 감소 (놓치는 위험 상황 증가 가능)

---

## 6. 결론

MVP 1단계에서는 `conf=0.5`를 **기본값**으로 사용한다.

이유:

- `conf=0.3`은 작은 객체를 더 많이 탐지하지만 bbox 깜빡임과 ENTER/EXIT 이벤트 증가가 발생한다.
- `conf=0.7`은 오탐은 줄지만 CCTV처럼 멀리 찍힌 사람을 놓칠 가능성이 커진다.
- `conf=0.5`는 **탐지 수와 안정성 사이의 균형**이 가장 적절하다.

CLI 옵션으로 변경 가능하므로, 영상 환경에 따라 조정할 수 있다.

```bash
python -m src.main --conf 0.5    # 기본값
python -m src.main --conf 0.4    # 작은 객체 영상
python -m src.main --conf 0.6    # 오탐 줄이고 싶을 때
```

---

## 7. 트레이드오프 정리

```text
낮은 conf (0.3)              높은 conf (0.7)
  ↓                              ↓
탐지 많음 (Recall ↑)         탐지 정확 (Precision ↑)
오탐 많음 (Precision ↓)      누락 많음 (Recall ↓)
False Alert 빈발              진짜 위험 놓칠 수도
이벤트 과다 발생              이벤트 부족
```

---

## 8. Phase 2 개선 방향

향후 실제 키즈카페 영상 데이터를 확보한 뒤, 환경별로 threshold를 재조정한다.

### 8.1 환경별 재조정 대상

- CCTV 거리 영상
- 조명 변화가 큰 영상
- 사람이 많은 혼잡 영상
- 출입문/위험구역 중심 영상

### 8.2 동적 Threshold

- 영역별 다른 conf 적용 (먼 구역은 낮게, 가까운 구역은 높게)
- 시간대별/조명별 자동 조정

### 8.3 모델 교체 후 재실험

[`model_benchmark.md`](model_benchmark.md)에서 YOLO26n을 Phase 2 실시간 입력 1차 기준 모델 후보로 선정했다.  
Phase 2에서 YOLO26n을 실제 웹캠/RTSP 환경에 적용한 뒤 동일한 confidence threshold 실험을 반복하여 최적 conf를 재산정한다.

→ 모델이 강해지면 최적 conf 값이 달라질 수 있음.

---

## 9. 한이음 수행계획서 매핑

| 수행계획서 명시 기술 | 현재 MVP 단계 | Phase 2 적용 |
|---------------------|--------------|-------------|
| 룰 기반 이벤트 판단 로직 (오탐 감소) | `conf=0.5` 고정 + DWELL 임계시간 적용 | 영역별/시간대별 동적 conf |
| 작은 객체 탐지 정밀도 | YOLOv8n + `conf=0.5` | YOLO26n 1차 후보 검증 + 동적 conf |
