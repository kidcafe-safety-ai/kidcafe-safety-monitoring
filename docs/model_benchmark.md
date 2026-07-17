# YOLO 모델 벤치마크

> **작성일**: 2026-05-30  
> **작성자**: 정종민 (A / Vision AI Backend)  
> **상태**: Phase 1.5 기준 모델 1차 선정 완료  
> **관련 문서**: [`README.md`](../README.md), [`interfaces.md`](interfaces.md), [`roadmap.md`](roadmap.md), [`decisions.md`](decisions.md), [`conf_tuning.md`](conf_tuning.md), [`tracking_analysis.md`](tracking_analysis.md)

---

## Executive Summary

Phase 1.5에서 Phase 2 실시간 입력에 사용할 1차 기준 모델로 **YOLO26n**을 선정한다.

선정 근거는 아래와 같다.

| 기준 | 결과 |
|---|---|
| 공식 YOLO 지표 | YOLO26n은 YOLOv8n보다 높은 COCO mAP와 더 낮은 CPU ONNX 추론 시간을 제공 |
| 프로젝트 FPS | 평균 21.3fps로 비교 모델 중 최고 |
| 빠른 이동/밀집 환경 | test2, test5에서 실제 인원 대비 초과 ID 수가 가장 적음 |
| 정성 평가 | 겹침 구간에서 bbox와 ID 라벨 흐름이 상대적으로 안정적으로 관찰됨 |
| 운영 판단 | 실시간성, 추적 안정성, 경량성을 모두 만족하는 1차 후보 |

본 문서는 공식 YOLO 평가 지표와 프로젝트 적용 지표를 분리한다.  
공식 모델 성능은 Ultralytics 문서의 COCO 기준 지표를 사용하고, 프로젝트 성능은 우리 영상 파이프라인에서 측정한 시스템 benchmark로 기록한다.

---

## 1. 목적

Phase 1.5의 목표는 최종 모델 확정이 아니라, Phase 2 실시간 입력 개발에 사용할 1차 기준 모델을 선정하는 것이다.

이번 실험의 판단 기준은 아래 순서다.

1. 공식 YOLO 성능표 기준으로 모델 후보의 accuracy-speed tradeoff를 확인한다.
2. 우리 프로젝트 영상에서 실제 처리 FPS와 추적 안정성을 측정한다.
3. result.mp4를 확인해 bbox, ID 라벨, 겹침 구간 안정성을 정성 평가한다.
4. 실시간 입력 단계에서 사용할 1차 기준 모델을 선정한다.

---

## 2. 비교 모델

| 모델 | 역할 | 판단 목적 |
|---|---|---|
| YOLOv8n | MVP baseline | 현재 구현 기준선 |
| YOLOv8s | 안정적 비교 후보 | 정확도 증가가 실시간성 손실을 상쇄하는지 확인 |
| YOLO26n | 최신 경량 후보 | 실시간 운영 기준 모델 후보 |
| YOLO26s | 최신 정확도 후보 | 공식 mAP 증가가 프로젝트 추적 안정성으로 이어지는지 확인 |

---

## 3. 실험 환경

```text
ultralytics: 8.4.56
device:      auto (Mac MPS)
conf:        0.3
venv:        .venv-benchmark
tracker:     ByteTrack
class:       person only
```

모든 모델은 동일한 영상, 동일한 confidence threshold, 동일한 ByteTrack 설정에서 비교했다.

---

## 4. 공식 YOLO 지표

Ultralytics 공식 문서에서 제공하는 Detection 기준 성능표를 비교 기준으로 사용한다.  
공식 지표는 COCO validation 기준이며, 우리 프로젝트 영상에서 직접 산출한 값이 아니다.

| 모델 | size | mAP val 50-95 | mAP val 50-95(e2e) | Speed CPU ONNX | params | FLOPs |
|---|---:|---:|---:|---:|---:|---:|
| YOLOv8n | 640 | 37.3 | - | 80.4ms | 3.2M | 8.7B |
| YOLOv8s | 640 | 44.9 | - | 128.4ms | 11.2M | 28.6B |
| YOLO26n | 640 | 40.9 | 40.1 | 38.9ms | 2.4M | 5.4B |
| YOLO26s | 640 | 48.6 | 47.8 | 87.2ms | 9.5M | 20.7B |

공식 지표 기준 해석:

- YOLO26n은 YOLOv8n보다 mAP가 높고 CPU ONNX 추론 시간이 낮다.
- YOLO26s는 YOLO26n보다 mAP가 높지만 CPU ONNX 추론 시간이 약 2.24배 크다.
- YOLO26 계열은 NMS-free end-to-end 구조와 edge/low-power deployment를 주요 특징으로 한다.
- YOLOv8은 안정적인 accuracy-speed tradeoff를 가진 기존 baseline으로 볼 수 있다.

공식 문서:

- Ultralytics YOLO26 Docs: https://docs.ultralytics.com/models/yolo26/
- Ultralytics YOLOv8 Docs: https://docs.ultralytics.com/models/yolov8/
- Ultralytics Benchmark Mode: https://docs.ultralytics.com/modes/benchmark/

---

## 5. 프로젝트 측정 지표

본 실험은 COCO 정답 라벨 기반 mAP 재측정이 아니다.  
우리 프로젝트 입력 영상에서 모델을 동일 조건으로 실행한 **file-video system benchmark**다.

### 라벨 없는 영상으로 먼저 비교한 이유

Phase 1.5의 목적은 최종 모델 정확도 증명이 아니라 Phase 2 실시간 입력 개발에 사용할 1차 기준 모델을 빠르게 선정하는 것이다.  
따라서 이 단계에서는 정답 bbox 라벨이 있는 데이터셋을 새로 구축하기보다, 실제 운영 환경과 유사한 실내 영상을 사용해 아래 항목을 먼저 확인했다.

```text
1. 우리 로컬 장비에서 실시간에 가까운 FPS가 나오는가
2. Ultralytics ByteTrack과 안정적으로 연동되는가
3. 빠른 이동/겹침 구간에서 track_id가 과도하게 분리되지 않는가
4. geofencing 이벤트 생성 파이프라인에 과도한 노이즈를 만들지 않는가
5. result.mp4 기준으로 bbox와 ID 라벨 흐름이 운영상 확인 가능한가
```

즉, 본 실험은 모델의 절대 정확도를 산출하기 위한 정식 detection benchmark가 아니라, 프로젝트 파이프라인 안에서 모델 후보를 고르기 위한 운영 적합성 평가다.

또한 현재 단계에서는 ReID, debounce/hysteresis, 실시간 입력 안정화가 적용되기 전이다.  
따라서 라벨링 데이터로 tracking/event 정확도를 측정하더라도 detection, tracking, zone rule의 영향을 분리하기 어렵다.  
정식 정확도 평가는 실시간 파이프라인과 안전 룰이 안정화된 뒤, 라벨링된 자체 촬영 또는 유사 키즈카페 영상으로 별도 수행한다.

따라서 공식 YOLO 지표와 프로젝트 지표를 아래처럼 구분한다.

| 구분 | 지표 | 의미 | 논문/보고서 사용 방식 |
|---|---|---|---|
| 공식 지표 | mAP val 50-95 | COCO detection 정확도 | 공식 모델 성능 비교 |
| 공식 지표 | Speed CPU ONNX | 공식 CPU ONNX 추론 시간 | 모델 경량성 비교 |
| 공식 지표 | params / FLOPs | 모델 크기와 연산량 | 배포 비용 비교 |
| 프로젝트 지표 | FPS | 우리 파이프라인 전체 처리 속도 | 시스템 실시간성 평가 |
| 프로젝트 지표 | frame time | frame별 `model.track()` 호출 평균 시간 | 추론/추적 호출 비용 평가 |
| 프로젝트 지표 | unique IDs | 영상 전체 생성 track_id 수 | ID fragmentation proxy |
| 프로젝트 지표 | avg det/frame | 프레임당 평균 person detection 수 | 탐지 민감도 경향 참고 |
| 프로젝트 지표 | ENTER / EXIT / DWELL | 현재 geofencing 이벤트 수 | 이벤트 노이즈 참고 |
| 정성 지표 | result.mp4 검토 | bbox, ID 라벨, 겹침 구간 안정성 | 운영 적합성 판단 |

중요한 해석 기준:

- `unique IDs`는 정확한 ID switch 지표가 아니다.
- 실제 등장 인원보다 unique IDs가 많을수록 track fragmentation이 많았다고 해석한다.
- `avg det/frame`은 정답 라벨이 없으므로 recall/precision을 직접 의미하지 않는다.
- ENTER/EXIT/DWELL은 아직 debounce, hysteresis, ReID가 없으므로 최종 이벤트 정확도로 해석하지 않는다.

---

## 6. 비교 영상

| ID | 조건 | Zone | 평가 목적 |
|---|---|---|---|
| test1 | 복도형, 1~2명, CCTV 가까움 | 없음 | 기본 탐지/추적 안정성 |
| test2 | 사람들 빠르게 지나감, CCTV 가까움 | 없음 | 빠른 이동, ID fragmentation |
| test5 | 빠르게 방으로 들어옴, 살짝 원거리 | 문앞 구역 | 밀집/겹침, ENTER/EXIT 이벤트 노이즈 |

---

## 7. test1 결과

### 영상 조건

```text
구도:     긴 복도형, CCTV 가까움
조명:     원거리 어두움, 사람 등장 시 조명 켜짐
사람 수:  2명
시나리오: 사람1이 멀리서 앞으로 걸어와 방에 들어갔다가 다시 나와 멀리 이동.
          사람2가 멀리서 나오면서 사람1과 맞물리며 지나감.
해상도:   1280x720, 29fps, 60초
```

### 정량 지표

| 모델 | FPS | frame time | unique IDs | avg det/frame |
|---|---:|---:|---:|---:|
| YOLOv8n | 21.92 | 42ms | 6 | 0.53 |
| YOLOv8s | 13.46 | 71ms | 5 | 0.59 |
| YOLO26n | 23.28 | 40ms | 7 | 0.54 |
| YOLO26s | 13.17 | 72ms | 6 | 0.53 |

### 정성 평가

| 모델 | 관찰 내용 | 평가 |
|---|---|---|
| YOLOv8n | 어두운 구간과 부분 가림에서 bbox 끊김이 상대적으로 큼 | 보류 |
| YOLOv8s | 초기 등장 구간을 가장 이른 시점에 포착, 탐지 민감도 높음 | 탐지 안정성 우수 |
| YOLO26n | 8n보다 bbox 흐름이 양호하고, 겹침 구간의 ID 라벨 흐름이 상대적으로 안정적 | 유력 |
| YOLO26s | 26n 대비 체감 이득이 크지 않고 FPS가 절반 수준 | 보류 |

### 소결

- test1에서는 YOLOv8s가 초기 탐지 민감도에서 강점을 보였다.
- YOLO26n은 FPS가 가장 높고, 겹침 구간에서 bbox/ID 흐름이 상대적으로 안정적으로 관찰됐다.
- YOLO26s는 YOLO26n 대비 실시간성 손실이 크지만, 해당 영상에서는 명확한 운영 이득이 크지 않았다.

---

## 8. test2 결과

### 영상 조건

```text
구도:     CCTV 매우 가까움
사람 수:  실제 등장 14명
시나리오: 사람들이 매우 빠르게 나타났다 사라짐. 50% 이상 겹치는 구간 다수.
해상도:   640x480, 25fps, 40초
```

### 정량 지표

| 모델 | FPS | frame time | unique IDs | 초과 ID | avg det/frame |
|---|---:|---:|---:|---:|---:|
| YOLOv8n | 19.05 | 51ms | 23 | +9 | 0.93 |
| YOLOv8s | 11.02 | 89ms | 25 | +11 | 0.97 |
| YOLO26n | 21.38 | 45ms | 20 | +6 | 0.93 |
| YOLO26s | 11.80 | 83ms | 24 | +10 | 0.98 |

### 정성 평가

| 모델 | 관찰 내용 | 평가 |
|---|---|---|
| YOLOv8n | 빠른 통과 구간에서 ID가 자주 새로 생김 | 보류 |
| YOLOv8s | 탐지 수는 많지만 unique ID도 증가 | 실시간성 부족 |
| YOLO26n | 가장 낮은 초과 ID, 가장 높은 FPS | 유력 |
| YOLO26s | 26n보다 느리고 ID 안정성 이득도 부족 | 보류 |

### 소결

- YOLO26n은 실제 인원 14명 기준 초과 ID가 +6으로 가장 낮았다.
- 빠른 이동과 겹침이 많은 영상에서 YOLO26n이 가장 좋은 FPS/ID fragmentation 균형을 보였다.
- YOLOv8s와 YOLO26s는 공식 mAP는 높지만, 본 영상에서는 실시간성과 추적 안정성 이득이 부족했다.

---

## 9. test5 결과

### 영상 조건

```text
구도:     살짝 원거리, 문앞 zone 설정
사람 수:  실제 등장 14명
시나리오: 사람들이 빠르게 연속으로 방에 들어옴. 방 안이 꽉 차며 bbox 겹침 다수.
해상도:   640x480, 25fps, 40초
```

### 정량 지표

| 모델 | FPS | frame time | unique IDs | 초과 ID | avg det/frame | ENTER | EXIT |
|---|---:|---:|---:|---:|---:|---:|---:|
| YOLOv8n | 19.06 | 51ms | 29 | +15 | 2.84 | 28 | 26 |
| YOLOv8s | 10.78 | 91ms | 32 | +18 | 2.90 | 30 | 28 |
| YOLO26n | 19.14 | 50ms | 24 | +10 | 2.73 | 32 | 30 |
| YOLO26s | 10.85 | 90ms | 41 | +27 | 2.92 | 29 | 27 |

### 정성 평가

| 모델 | 관찰 내용 | 평가 |
|---|---|---|
| YOLOv8n | 문앞 빠른 통과와 겹침 구간에서 ID fragmentation 증가 | 보류 |
| YOLOv8s | 탐지 민감도는 높지만 FPS와 ID 안정성 모두 불리 | 보류 |
| YOLO26n | 밀집 환경에서 초과 ID가 가장 낮고 FPS도 가장 높음 | 유력 |
| YOLO26s | unique IDs가 41로 급증, 실시간성도 부족 | 보류 |

### 소결

- YOLO26n은 test5에서도 초과 ID +10으로 가장 안정적이었다.
- ENTER/EXIT 이벤트는 모든 모델에서 실제 인원 대비 많이 발생했다.
- 이 이벤트 노이즈는 모델만의 문제가 아니라 문앞 빠른 통과, 현재 foot_point 기반 2D zone 판정, debounce/hysteresis 부재가 함께 만든 결과다.
- 따라서 geofencing 이벤트 정확도는 Phase 3에서 별도 고도화 후 재평가한다.

---

## 10. 전체 결과

### 프로젝트 FPS

| 모델 | test1 | test2 | test5 | 평균 | 실시간 후보 |
|---|---:|---:|---:|---:|---|
| YOLOv8n | 21.92 | 19.05 | 19.06 | 20.0 | 조건부 |
| YOLOv8s | 13.46 | 11.02 | 10.78 | 11.8 | 부적합 |
| YOLO26n | 23.28 | 21.38 | 19.14 | 21.3 | 적합 |
| YOLO26s | 13.17 | 11.80 | 10.85 | 12.0 | 부적합 |

### ID fragmentation proxy

| 모델 | test1 실제 2명 | test2 실제 14명 | test5 실제 14명 |
|---|---:|---:|---:|
| YOLOv8n | 6(+4) | 23(+9) | 29(+15) |
| YOLOv8s | 5(+3) | 25(+11) | 32(+18) |
| YOLO26n | 7(+5) | 20(+6) | 24(+10) |
| YOLO26s | 6(+4) | 24(+10) | 41(+27) |

### 모델별 종합 판단

| 모델 | 장점 | 한계 | 판단 |
|---|---|---|---|
| YOLOv8n | 기존 MVP baseline, 속도 양호 | 어두운 구간/밀집 구간에서 상대적으로 불안정 | 보류 |
| YOLOv8s | test1 초기 탐지 민감도 우수 | 평균 11.8fps로 실시간 운영 부담 | 제외 |
| YOLO26n | 공식 지표와 프로젝트 지표 모두 경량/실시간성 우수, test2/test5 ID fragmentation proxy 최저 | test1 어두운 초기 구간은 8s보다 늦게 잡는 장면 있음 | 채택 |
| YOLO26s | 공식 mAP 최고 | 평균 12.0fps, test5 unique IDs 급증 | 제외 |

---

## 11. 최종 선정

### 1차 기준 모델

```text
YOLO26n
```

### 선정 사유

1. 공식 YOLO 지표에서 YOLO26n은 YOLOv8n보다 높은 COCO mAP와 더 낮은 CPU ONNX 추론 시간을 보인다.
2. 우리 프로젝트 영상에서도 YOLO26n은 평균 FPS 21.3으로 가장 높았다.
3. test2, test5에서 실제 등장 인원 대비 초과 ID 수가 가장 적었다.
4. result.mp4 정성 검토에서도 빠른 이동/겹침 구간의 bbox와 ID 라벨 흐름이 상대적으로 안정적이었다.
5. YOLO26s는 공식 mAP는 높지만, 본 실험에서는 실시간성 손실이 커 운영 후보로 부적합했다.

### 상업 프로젝트 관점의 판단

상업/운영형 시스템에서는 단일 이미지 mAP만으로 모델을 선택하지 않는다.  
실시간 CCTV 기반 안전 모니터링에서는 아래 조건을 함께 만족해야 한다.

```text
1. 처리 FPS가 입력 영상 FPS에 근접할 것
2. 빠른 이동/겹침 상황에서 track_id가 과도하게 분리되지 않을 것
3. 모델 크기와 추론 시간이 운영 장비에 부담되지 않을 것
4. 이벤트 생성 파이프라인에서 노이즈를 과도하게 만들지 않을 것
```

YOLO26n은 위 조건을 가장 균형 있게 만족했으므로 Phase 2 실시간 입력의 1차 기준 모델로 채택한다.

---

## 12. 논문/보고서 사용 기준

본 결과는 아래 표현으로 사용할 수 있다.

```text
Ultralytics 공식 COCO benchmark에서 YOLO26n은 YOLOv8n 대비 높은 mAP와 낮은 CPU ONNX 추론 시간을 보였다.
본 프로젝트의 실내 영상 기반 시스템 benchmark에서도 YOLO26n은 평균 FPS 21.3으로 가장 높은 처리 속도를 보였고,
빠른 이동 및 밀집 환경에서 실제 등장 인원 대비 초과 track_id 수가 가장 적었다.
이에 따라 YOLO26n을 실시간 키즈카페 안전 모니터링 시스템의 1차 기준 모델로 선정하였다.
```

사용 시 주의:

- 이 결과는 COCO mAP를 재측정한 것이 아니다.
- 프로젝트 영상에 정답 bbox 라벨이 없으므로 precision, recall, mAP는 산출하지 않았다.
- `unique IDs`는 정식 IDF1/MOTA/ID switch가 아니라 ID fragmentation proxy다.
- 최종 논문에서 정식 성능 지표가 필요하면 라벨링된 데이터셋으로 detection mAP와 tracking IDF1/MOTA를 별도 측정해야 한다.

추후 최종 성능 평가 계획:

```text
1. 팀원 재현 촬영 또는 실제/유사 키즈카페 영상 확보
2. 개인정보 보호를 위한 촬영 동의, 비식별 처리, 얼굴/민감정보 보호 기준 정리
3. 일부 영상에 대해 person bbox 라벨링
4. 이벤트 구간 라벨링
   - ENTER
   - DWELL
   - EXIT
   - FALL_SUSPECT (Phase 3 opt-in PoC 구현 완료, Validation 개선 후속) / COLLISION_SUSPECT (Phase 4 이후 재검토)
5. 필요 시 track_id 연속성 수동 기준 작성
6. 최종 보고서/논문용 정식 지표 산출
```

최종 평가에서 사용할 수 있는 지표:

| 평가 대상 | 지표 |
|---|---|
| Detection | precision, recall, mAP, false positive, false negative |
| Tracking | ID switch, IDF1, MOTA 또는 수동 ID 유지율 |
| Event | event precision, event recall, false alert count, missed event count |
| Real-time | FPS, latency, frame drop, reconnect time |

따라서 현재 문서의 결과는 Phase 2 기준 모델 후보 선정 근거로 사용하고, 최종 논문/보고서의 정확도 평가는 별도 라벨링 데이터셋으로 보강한다.

---

## 13. Phase 2 재검증 항목

```text
- YOLO26n + ByteTrack 실시간 웹캠 환경 FPS 재확인
- 웹캠/RTSP 입력에서 frame drop, latency, reconnect 영향 측정
- YOLO26n의 NMS-free/end-to-end 구조와 ByteTrack 연동 안정성 확인
- 실제 또는 유사 키즈카페 영상에서 추가 검증
- 필요 시 YOLOv8n을 fallback baseline으로 유지
```
