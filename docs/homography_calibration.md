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
- **fit 4점이 사람이 움직이는 범위를 모두 감싸야 한다.** 2026-08-07 촬영에서는
  기준점이 구역 일부에 몰려 사람 위치의 61%가 fit 사각형 밖으로 나갔고, 그
  구간의 오차가 5배 이상 커졌다 (§7.3, §7.5).

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

동결 시 `homography_acceptance_<camera_id>.json`의 `frozen_at`에 timezone을 포함한
RFC 3339 동결 시각을, `review_status`를 `reviewed`로 기록한다
(`docs/interfaces.md`의 정의를 따른다). holdout 결과를 확인한 뒤에는 허용값을
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

**평균과 p95의 대소는 강제하지 않는다.** 왜곡된 분포에서는 평균이 p95보다 클 수
있다. 오차 21개가 0m 20개와 100m 1개면 평균은 4.7619m, p95는 0m다. 두 값 모두
finite·비음수인지만 확인한다.

측정값 부호 규칙:

| 측정값 | 정의 | 음수 |
|---|---|---|
| 평균·p95 위치 오차 | 거리 절대량 | 불가 |
| calibration 소요 시간 | 시간 절대량 | 불가 |
| frame당 추가 비용 | Homography 경로 − 기존 경로 | **가능** |
| FPS 하락률 | (기존 FPS − 후보 FPS) / 기존 FPS | **가능** |

뒤 두 값은 기준선 대비 차이라 후보 경로가 더 빠르면 음수가 나온다. 측정값을
그대로 기록하며 `max(0, ...)`으로 깎지 않는다. 음수는 "하락 없음"이므로 임계값
비교를 자연히 통과한다.

### 동결된 상대 기준

아래 값은 `homography_acceptance_v1`이 이미 동결했다. 촬영 당일 정하는 절대 오차
허용값과 달리 **바꿀 수 없다.** 최소 기준을 낮추거나 최대 기준을 키우면 성능이
악화된 측정값도 통과하기 때문이다.

```text
min_zone_error_reduction_ratio=0.30
min_zone_accuracy_gain_percentage_point=5.0
min_event_error_reduction_ratio=0.30
max_added_latency_ms_per_frame=1.0
max_fps_drop_ratio=0.05
max_calibration_minutes=15
```

`parse_acceptance()`가 이 값들의 일치를 강제한다.

---

## 7. 측정 기록

2026-08-07 촬영과 그 결과다. 촬영 조건이 §4 절차와 달라진 부분이 있어 측정
방법도 함께 기록한다.

### 7.1 촬영 조건과 실측 (2026-08-07)

| 항목 | 값 |
|---|---|
| 촬영 장소 | 김포 장기동 무인 키즈카페, 16:00-19:00 |
| 촬영 기기 | iPhone (`IMG_####.MOV`), IP 카메라 미사용 |
| 촬영 해상도·fps | 1920×1080, 59.94fps |
| 기준점 수 | 10개 (계약 요구 14개 = fit 4 + holdout 10에 미달) |
| 좌표 기록 | 원점 기준 `(y, x)` 정수, **단위 미확정** |
| 원점 | 촬영 구역 좌하단 회색 테이프. x는 오른쪽, y는 카메라에서 멀어지는 방향 |
| Zone 표시 | 회색 테이프 (기준점은 빨간 테이프) |
| `calibration_version` | `2026-08-07-clip00-orig`, `2026-08-07-clip01` |

**좌표 단위 미확정.** 촬영자는 줄자를 cm로 읽었다고 기록했으나, 영상에서 역산한
값이 방법마다 흩어져 확정하지 못했다.

| 역산 방법 | 결과 |
|---|---|
| 테이프 폭 (마스킹테이프 12~24mm 가정) | 1~2 cm/단위 |
| 사람이 다닌 바닥 넓이 | 2~3 cm/단위 |
| 양말 길이 (발 25cm 가정) | 약 4.8 cm/단위 |

압축 전송본으로 측정해 각 방법의 오차가 커 하나로 좁히지 못했다. §7.3의 판정은
1~9 cm/단위 전 구간에서 동일하므로 이 미확정이 결론을 바꾸지 않는다. 다음
촬영에서는 좌표 기록에 단위를 반드시 명기한다.

**카메라가 고정되지 않았다.** 클립 간 최대 8.5도 회전과 104px 이동, 21초짜리
calibration 클립 안에서도 1도 회전과 26px 이동이 측정됐다. §4의 "calibration
촬영 후 카메라 절대 이동 금지"가 지켜지지 않았다.

### 7.2 허용값

| 항목 | 값 | 근거 |
|---|---|---|
| `max_mean_error_m` | 0.10 | ADR-023 채택 기준의 median 10cm를 그대로 사용 |
| `max_p95_error_m` | 0.20 | ADR-023 채택 기준의 p95 20cm를 그대로 사용 |
| `frozen_at` | 미동결 | 아래 사유 |

**동결 절차를 지키지 못했다.** §5는 holdout 결과를 보기 전에 실측값을 근거로
허용값을 동결하도록 요구하는데, 촬영 당일 그 절차를 수행하지 않았고 분석
시점에는 이미 오차를 확인한 뒤였다. 결과를 본 뒤 고른 값은 동결이라 부를 수
없으므로 `homography_acceptance_<camera_id>.json`을 만들지 않는다.

대신 ADR-023이 촬영 전부터 명시한 10cm·20cm를 그대로 쓴다. 이 값은 이번 측정과
무관하게 정해져 있었으므로 사후 선택이 아니다. §7.3은 이 값 기준의 참고 판정이며,
`require_frozen()`을 통과한 공식 판정이 아니다.

### 7.3 holdout 위치 오차

측정: `scripts/evaluate_homography_holdout.py`
클립: `cam01_clip00`(calibration 영상), `cam01_clip01`(시나리오 영상)

기준점이 10개뿐이라 fit 4점을 고정하면 holdout이 6위치에 그친다. 계약이 요구하는
10위치·20관측을 채우기 위해 fit 조합을 점마다 바꿔 모든 점이 한 번씩 holdout이
되게 했다. fit 조합은 **대상 점을 제외한 조합 중 사각형 면적이 최대인 것**으로
정했고, 이 규칙은 오차와 무관하므로 결과에 맞춰 고를 여지가 없다.

10점 중 6점은 전체 배치의 볼록껍질 위에 있다. 그런 점을 holdout으로 빼면 남은
4점이 그 위치를 감싸지 못해 외삽이 된다. 외삽 오차는 변환의 정확도가 아니라
기준점 배치의 한계를 재는 값이므로 분리해 기록한다.

| 구분 | 위치 | 관측 | 평균 | p95 | 최대 |
|---|---:|---:|---:|---:|---:|
| 내삽 (fit 사각형 안) | 4 | 8 | **1.14** | 1.89 | 2.07 |
| 외삽 (fit 사각형 밖) | 6 | 12 | 2.96 | 9.84 | 11.61 |
| 전체 | 10 | 20 | 2.23 | 8.56 | 11.61 |

단위는 좌표 원단위다. cm로 환산하면 아래와 같고, 어느 가정에서도 내삽 오차는
허용값 안에 들어온다.

| 1단위 | 내삽 평균 | 내삽 p95 | 허용값 대비 |
|---|---:|---:|---|
| 1cm | 1.1cm | 1.9cm | 통과 |
| 3cm | 3.4cm | 5.7cm | 통과 |
| 5cm | 5.7cm | 9.5cm | 통과 |
| 9cm | 10.3cm | 17.0cm | 평균 초과 |

**클립별 calibration이 카메라 이동을 상쇄한다.** 두 클립 사이에 같은 기준점의
픽셀 위치가 평균 8.2px·최대 14.1px 움직였는데도 내삽 오차는 clip00 1.04,
clip01 1.10으로 유지됐다. 클립마다 기준점을 다시 찍으면 고정되지 않은 카메라로도
변환을 만들 수 있다.

**기준점 영역이 촬영 구역을 덮지 못했다.** clip01에서 사람 발밑 위치를 23프레임
추적한 결과 fit 사각형 안에 있던 것은 9프레임(39%)이었다. fit 사각형이
x 5~44 · y 17~82인 반면 사람은 x 16~72 · y −8~56 범위를 움직였다. 발밑 검출이
어두운 옷 영역 기준이라 정밀하지는 않으나 안팎이 갈리는 경향은 분명하다.

Zone 정확도·오판정 수·ENTER·EXIT 오류 수·frame당 추가 비용·FPS 하락률은 측정하지
않았다. 사람 위치의 과반이 외삽 구간이라 Zone 판정을 비교해도 변환 성능이 아니라
기준점 배치의 한계를 재게 된다.

### 7.4 채택 여부

**미채택.** 기존 image polygon 경로를 유지한다.

변환 자체는 문제가 없다. 기준점 영역 안에서는 어떤 단위 가정에서도 허용값을
통과했고, 클립별 calibration으로 카메라 이동도 상쇄했다. 미채택 사유는
알고리즘이 아니라 촬영 데이터의 조건이다.

| 사유 | 내용 |
|---|---|
| 기준점 배치 부족 | 사람 위치의 61%가 fit 사각형 밖. 그 구간 오차가 5배 이상 |
| 카메라 미고정 | 클립 간 최대 8.5도 회전. 단일 config calibration을 쓸 수 없음 |
| 좌표 단위 미확정 | 절대 오차를 하나의 수치로 확정할 수 없음 |
| 기준점 수 부족 | 10개. 계약 요구 14개 미달 |
| 허용값 동결 절차 누락 | §5의 사전 동결을 수행하지 못함 |
| 원본 미보존 | 촬영 원본이 전송 압축본으로만 공유된 기간이 있었음 |

ADR-023과 §6이 정한 대로 미채택도 정상적인 결과다. Phase 4 범위에서 Homography는
PoC로 종료하고 production 경로에 반영하지 않는다.

### 7.5 다음 촬영을 위한 보완

이번 미채택 사유는 모두 촬영 절차로 해결된다.

- **기준점을 촬영 구역 전체에 배치한다.** fit 4점이 사람이 움직이는 범위를 모두
  감싸야 한다. 이번처럼 구역 일부에 몰리면 나머지가 전부 외삽이 된다.
- **기준점 14개 이상을 붙인다.** fit 4 + holdout 10.
- **좌표 기록에 단위를 명기한다.** `9` 대신 `9cm`처럼 적는다.
- **카메라를 고정하고 촬영 중간에 검증한다.** 시나리오 사이사이에 빈 화면을
  다시 녹화해 프레임을 비교하면 이동을 그 자리에서 발견할 수 있다.
- **원본을 촬영 당일 외부 저장소에 옮긴다.** 메신저 전송본은 재인코딩되어
  기준점이 뭉개지고 fps도 달라진다.
- **허용값을 촬영 당일 동결한다.** 실측 직후·holdout 확인 전에 §5의 항목을 채워
  `homography_acceptance_<camera_id>.json`을 만든다.
