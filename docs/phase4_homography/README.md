# Phase 4 Homography PoC 평가 artifact

`docs/homography_calibration.md` 7절이 인용하는 수치의 원본이다. 영상 원본은
개인정보가 있어 Git에 넣지 않지만, 평가에 실제로 쓰인 비식별 입력과 결과는
여기에 보존해 제3자가 같은 수치를 재현할 수 있게 한다.

## 파일

| 파일 | 내용 |
|---|---|
| `cam01_*_picked.csv` | 클립 5개에서 각각 찍은 기준점 10개 픽셀 좌표 |
| `cam01_*_holdout.csv` | 위 파일 중 holdout 점만 실측 좌표와 함께 뽑은 것 |
| `holdout_designated.json` | **공식** 평가 결과 (role=fit 4점 고정) |
| `holdout_loo-all.json` | 보조 진단 (leave-one-out, 남은 9점 최소자승) |
| `holdout_loo-quad.json` | 보조 진단 (leave-one-out, 최대 면적 4점) |
| `cost_benchmark.json` | frame당 추가 비용·FPS 하락률 |
| `zone_eval_handover.md` | 채택 기준 2~5번 측정에 필요한 영상별 준비 상태·대응표 |
| `zone_intervals_draft.csv` | Zone 진입·이탈 검수용 헤더 초안 |
| `_checksums.md` | 위 파일과 calibration config의 SHA-256 |

runtime calibration config는 계약 위치인 `configs/camera_calibration/`에 있다.

## 재현 명령

```bash
# 공식 평가 — role=fit 4점으로 행렬 고정, role=holdout 점만 평가
python scripts/evaluate_homography_holdout.py \
  --points docs/calibration_points.csv \
  --picked docs/phase4_homography/cam01_clip00_orig_picked.csv \
  --picked docs/phase4_homography/cam01_clip01_picked.csv \
  --picked docs/phase4_homography/cam01_img7327_picked.csv \
  --picked docs/phase4_homography/cam01_img7328_picked.csv \
  --picked docs/phase4_homography/cam01_img7329_picked.csv \
  --unit-cm 1 \
  --fit-mode designated \
  --output docs/phase4_homography/holdout_designated.json

# 보조 진단 — --fit-mode를 loo-all 또는 loo-quad로 바꿔 실행
# runtime 후보의 정확도가 아니므로 공식 판정에 쓰지 않는다

# runtime 비용
python scripts/benchmark_homography_cost.py \
  --calibration configs/camera_calibration/cam01_clip00_orig.json \
  --floor-zones data/zones/floor_cam01.json \
  --image-zones data/zones/image_cam01.json \
  --tracks-per-frame 3 --frames 2000 --baseline-fps 25 \
  --output docs/phase4_homography/cost_benchmark.json
```

## 읽을 때 주의할 것

**`is_official`을 먼저 본다.** `holdout_designated.json`만 `true`다. runtime
config는 `role == "fit"`인 점만 `image_points_px`에 담으므로 실제 배포되는 변환은
그 4점으로 만든 것 하나다. leave-one-out 결과는 다른 조합으로 만든 행렬의
정확도이므로 runtime 후보의 성능이 아니다.

**`contract.meets_contract`가 `false`다.** `phase4_contract_v1`은 holdout
10위치·20관측을 요구하는데 이번 촬영은 fit 4·holdout 6이라 공식 경로로 6위치·
12관측만 나온다. 수치는 진단으로 읽고 공식 acceptance 판정에는 쓰지 않는다.
허용값도 동결하지 못했다. 두 사유로 채택 기준 1번은 판정 불가이고, PoC 전체
판정은 **미채택**이다(`docs/homography_calibration.md` 7.7절).

**좌표 단위가 확정되지 않았다.** `--unit-cm 1`로 실행했으므로 결과의
`*_m` 필드는 meter가 아니라 **촬영 기록 원단위를 100으로 나눈 값**이다. 실측
단위가 확인되면 그 배수만큼 다시 환산해야 한다. 자세한 사정은
`docs/homography_calibration.md` 7.1절에 있다.

**카메라가 클립마다 움직였다.** 클립 간 최대 8.5도 회전이 측정돼 단일
calibration을 전 클립에 적용할 수 없다. 클립 5개에서 기준점을 각각 다시 찍어
평가했다. 클립을 늘려 관측 수는 30회로 계약 요건 20회를 넘겼지만, 기준점이
10개뿐이라 **holdout 위치는 6개로 고정**된다. 위치 수는 클립이 아니라 촬영
현장의 기준점 개수가 정하므로 이 데이터로는 더 늘릴 수 없다.

`_picked.csv`는 picker가 `--output` 옆에 쓰므로 기본 위치는
`configs/camera_calibration/`이다. 평가 입력은 여기 모아 체크섬을 남기므로
찍은 뒤 이 디렉터리로 옮긴다.
