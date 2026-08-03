# Homography Calibration 기준·측정 절차

Phase 4 Homography floor-plane PoC(ADR-023)의 좌표계 정의, calibration 기준점
배치 기준, 2026-08-07 촬영 당일 측정 절차를 기록한다.

이 문서는 촬영 전에 확정해야 하는 항목만 다룬다. 절대 오차 허용값 동결과
holdout 비교 결과는 촬영 이후 `homography_acceptance_v1`과 평가 기록에서
관리한다.

> 촬영은 하루뿐이고 재촬영 일정이 없다. 이 문서의 3-5절이 촬영 전에 확정되지
> 않으면 Homography PoC 전체를 수행할 수 없다.

관련 문서: [`decisions.md` ADR-023](decisions.md),
[`interfaces.md`](interfaces.md), [`data_sources.md`](data_sources.md)

---

## 1. 범위

- 고정 카메라 1대, 단일 평면 바닥
- config 기반 calibration, 기본 비활성(`enabled=false`)
- 픽셀 `foot_point` → meter `floor_point` sparse 변환
- floor-coordinate Zone polygon 판정 후 기존 `zone_type`·rule·debounce 적용
- Event의 pixel `foot_point`와 기존 image-coordinate 경로는 그대로 유지

Phase 4 범위에서 제외한다.

- calibration 편집 UI
- cross-camera 좌표 통합
- 다중 평면·경사 바닥
- 카메라 자동 재보정

---

## 2. 좌표계 정의

### 2.1 floor 좌표계

| 항목 | 정의 |
|---|---|
| 단위 | meter (`coordinate_unit: "meter"`) |
| 원점 `(0, 0)` | 촬영 구역 좌측 하단 기준점 |
| `+X` 축 | 원점에서 촬영 구역 우측 방향, 카메라 화면 가로에 대응 |
| `+Y` 축 | 원점에서 카메라로부터 멀어지는 방향 (화면 위쪽) |
| 평면 | 바닥면 `Z=0`, 높이 성분은 사용하지 않음 |

- 오른손 좌표계가 아니라 **바닥면 2D 평면 좌표**다. `Z`는 정의하지 않는다.
- 원점은 촬영 내내 이동하지 않는 물리적 표식(바닥 테이프 교차점)으로 잡는다.
- `origin_description`에 원점의 물리적 위치를 한 문장으로 기록한다.
- 좌표값은 소수점 둘째 자리(cm 단위)까지 기록한다.

### 2.2 image 좌표계

- 단위: pixel, 원점은 프레임 좌상단 `(0, 0)`
- `image_points_px`는 촬영 해상도 기준 절대 픽셀값이다. 정규화하지 않는다.
- `frame_size`와 실제 영상 해상도가 다르면 fail-fast한다.

### 2.3 기존 image-normalized Zone과의 관계

- 기존 Zone Settings는 image-normalized polygon을 계속 사용한다.
- floor-plane Zone은 `data/zones/floor_<camera_id>.json`에 별도로 둔다
  (`coordinate_space: "floor_meters"`).
- 두 경로는 동일 Track·foot point 입력으로 비교하며, 채택 기준을 모두 통과한
  경우에만 별도 PR로 production 계약을 확장한다.

---

## 3. Calibration 기준점 배치 기준

### 3.1 fit point (calibration 학습점)

- 최소 4개
- 촬영 구역 바닥의 **가장 넓은 사각형**에 가깝게 배치한다.
- 4개가 image·floor 각각에서 **동일 직선 위에 놓이면 안 된다.**
- 전부 카메라 프레임 안에 들어와야 하고 인물·집기에 가려지지 않아야 한다.
- fit point는 최종 오차 계산에서 제외한다.

### 3.2 holdout point (검증점)

`homography_acceptance_v1` 요건이다.

| 항목 | 최소 기준 |
|---|---|
| 서로 다른 위치 | 10개 |
| 총 관측 수 | 20회 이상 (위치당 2회 이상 반복 관측) |
| 거리 분포 | 근거리·중거리·원거리 각 구간 포함 |
| Zone 경계 | Zone 경계 주변 지점 포함 |

- holdout point는 fit point와 **물리적으로 겹치지 않는다.**
- holdout point는 runtime config에 넣지 않는다. `calibration_points.csv`에만
  기록한다.
- 반복 관측은 같은 물리 위치를 다른 프레임에서 다시 읽은 값이며, 픽셀 좌표가
  프레임마다 미세하게 달라지는 것이 정상이다.

### 3.3 배치도

```text
        카메라 (높이 H, 화면 아래쪽이 근거리)
                    │
                    ▼
   +Y (원거리)
    ▲
4.0 │  F4●────────────────────────●F3      F : fit point (4)
    │    │                        │        H : holdout point (10)
3.0 │    │   H09          H10     │
    │    │                        │        · 근거리 : Y ≈ 0.5
2.0 │    │        H08             │        · 중거리 : Y ≈ 1.5-2.0
    │    │                        │        · 원거리 : Y ≈ 2.5-3.0
1.5 │    │  H06    H07            │
    │    │                        │        Zone 경계선 ┈┈┈
0.5 │    │ H01  H02  H03  H04  H05│
    │    │                        │
0.0 │  F1●────────────────────────●F2
    └────┴────┴────┴────┴────┴────┴──▶ +X (우측)
       0.0  1.0  2.0  3.0  4.0  5.0  6.0

   원점 (0,0) = F1 = 촬영 구역 좌측 하단 바닥 표식
```

- 위 수치는 6.0m × 4.0m 구역을 가정한 **배치 형태 기준**이다. 실제 좌표는 촬영
  당일 실측값으로 대체한다.
- Zone 경계가 확정되면 경계선 양옆 각 1개 이상을 holdout에 포함시킨다.

---

## 4. 2026-08-07 촬영 당일 측정 절차

B가 기록을 담당하고, 기준점 설치와 실거리 측정은 팀이 보조한다.

### 4.1 준비물

- 줄자(5m 이상) 또는 레이저 거리계
- 바닥 표식용 마스킹 테이프, 유성 마커
- 기준점 라벨 카드 (`F1`-`F4`, `H01`-`H10`)
- 측정 기록지 또는 노트북(`calibration_points.csv` 직접 입력)

### 4.2 순서

1. **카메라 고정** — 위치·높이·각도·해상도·FPS를 확정하고 촬영이 끝날 때까지
   움직이지 않는다. 카메라가 움직이면 calibration을 처음부터 다시 한다.
2. **원점 표식** — 촬영 구역 좌측 하단에 원점 테이프를 붙이고 `+X`·`+Y` 축
   방향을 바닥에 표시한다.
3. **fit point 설치** — `F1`-`F4`를 붙이고 원점 기준 실거리를 측정해 기록한다.
4. **holdout point 설치** — `H01`-`H10`을 3.2절 분포 기준으로 붙이고 실거리를
   측정해 기록한다.
5. **calibration 프레임 촬영** — 모든 표식이 보이는 상태로 최소 10초 촬영한다.
   인물이 표식을 가리지 않게 한다.
6. **픽셀 좌표 읽기** — calibration 프레임에서 각 표식의 픽셀 좌표를 읽어
   기록한다. holdout은 서로 다른 프레임에서 2회 이상 읽는다.
7. **공간 실측** — 5절 항목을 측정해 기록한다.
8. **표식 유지** — 본 촬영 중 표식을 떼지 않는다. 부득이하게 제거하면 제거
   시점을 기록하고 이후 구간은 calibration 검증에서 제외한다.
9. **백업** — calibration 프레임과 기록지를 촬영 원본과 함께 2중 백업하고
   체크섬을 남긴다.

### 4.3 기록 산출물

| 파일 | 내용 |
|---|---|
| `configs/camera_calibration/<camera_id>.json` | fit point만 포함한 runtime config |
| `data/annotations/phase4/calibration_points.csv` | fit·holdout 전체 픽셀·실측 좌표 |
| `data/zones/floor_<camera_id>.json` | meter 단위 floor-plane Zone polygon |

`calibration_points.csv` 스키마는
`tests/fixtures/phase4_contract/calibration_points.csv`를 따른다.

```text
camera_id,calibration_version,point_id,point_role,observation_index,
image_x_px,image_y_px,floor_x_m,floor_y_m,review_status,notes
```

- `point_role`: `fit | holdout`
- `observation_index`: 같은 `point_id`의 반복 관측 번호, 1부터 시작
- `review_status`: `reviewed | needs_review`
- `calibration_version`: `<camera_id>-<촬영일 YYYYMMDD>-v<n>` (예: `cam01-20260807-v1`)

---

## 5. 절대 오차 허용값 동결에 필요한 실측 항목

촬영 전에 임의의 허용값(10cm·20cm 등)을 정하지 않는다. 아래 값을 촬영 당일
측정한 뒤, **holdout 결과를 보기 전에** `homography_acceptance_v1`의
`max_mean_error_m`·`max_p95_error_m`을 동결한다.

| 항목 | 용도 |
|---|---|
| 실측 바닥 크기 (X × Y, m) | 허용 오차의 상대 규모 산정 |
| Zone 경계 폭 (m) | 경계 오판정을 유발하지 않는 오차 상한 |
| calibration 기준점 측정 오차 (m) | 허용값의 하한 (측정 오차보다 엄격할 수 없음) |
| 촬영 해상도 (px) | 픽셀당 실거리 환산 |
| 카메라 높이 (m)·각도 | 원근 왜곡 정도 확인 |

동결 시 `homography_acceptance_<camera_id>.json`의 `frozen_at`에 동결 시각을,
`review_status`를 `frozen`으로 기록한다. holdout 결과를 확인한 뒤에는 허용값을
완화하지 않는다.

---

## 6. 채택 기준

아래를 **모두** 만족할 때만 production 경로로 채택한다 (ADR-023).

| 지표 | 기준 |
|---|---|
| 평균·p95 위치 오차 | 동결된 허용값 이하 |
| Zone inside/outside 정확도 | 기존 방식보다 개선 |
| Zone 오판정 수 | 30% 이상 감소 **또는** 정확도 5%p 이상 개선 |
| ENTER·EXIT Event 오류 수 | 30% 이상 감소 |
| 빠른 ENTER·EXIT 반전 | 증가 없음 |
| frame당 추가 비용 | 1ms 이하 |
| FPS 하락률 | 5% 이내 |
| camera·해상도 불일치 | fail-fast |
| calibration·재검증 소요 | 15분 이내 |
| 기존 image-coordinate Event 계약 | 회귀 없음 |

기존 방식에서 오류가 발생하지 않거나 Homography 개선이 불안정하면 채택하지
않는다. 이 경우 기존 image polygon을 유지하고 PoC 결과와 미채택 사유만
기록한다. 미채택도 정상적인 결과다.

위치 오차 정의:

- 예측 floor point와 실측 floor point 사이 meter 단위 Euclidean distance
- 평균: reviewed holdout 관측 전체의 산술평균
- p95: `numpy.percentile(errors, 95, method="linear")`
- 평균·p95는 meter와 centimeter를 함께 기록한다
- fit point는 오차 계산에서 제외한다

---

## 7. 측정 기록

촬영 후 실측값과 holdout 비교 결과를 아래에 추가한다.

### 7.1 촬영 공간 실측 (2026-08-07)

| 항목 | 값 |
|---|---|
| 실측 바닥 크기 | (촬영 후 기입) |
| Zone 경계 폭 | (촬영 후 기입) |
| 기준점 측정 오차 | (촬영 후 기입) |
| 촬영 해상도 | (촬영 후 기입) |
| 카메라 높이·각도 | (촬영 후 기입) |
| `calibration_version` | (촬영 후 기입) |

### 7.2 허용값 동결

| 항목 | 값 | 근거 |
|---|---|---|
| `max_mean_error_m` | (동결 후 기입) | |
| `max_p95_error_m` | (동결 후 기입) | |
| `frozen_at` | (동결 후 기입) | |

### 7.3 holdout 비교 결과

| 지표 | 기존 image 방식 | Homography | 판정 |
|---|---|---|---|
| 평균 위치 오차 | - | (기입) | |
| p95 위치 오차 | - | (기입) | |
| Zone 정확도 | (기입) | (기입) | |
| Zone 오판정 수 | (기입) | (기입) | |
| ENTER·EXIT 오류 수 | (기입) | (기입) | |
| 빠른 반전 수 | (기입) | (기입) | |
| frame당 추가 비용 | - | (기입) | |
| FPS 하락률 | - | (기입) | |

### 7.4 채택 여부

(촬영·분석 후 기입 — 채택 또는 미채택과 그 사유)
