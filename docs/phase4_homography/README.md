# Phase 4 Homography PoC 평가 artifact

`docs/homography_calibration.md` 7절이 인용하는 수치의 원본이다. 영상 원본은
개인정보가 있어 Git에 넣지 않지만, 평가에 실제로 쓰인 비식별 입력과 결과는
여기에 보존해 제3자가 같은 수치를 재현할 수 있게 한다.

## 파일

| 파일 | 내용 |
|---|---|
| `cam01_*_picked.csv` | 클립 13개에서 각각 찍은 기준점 10개 픽셀 좌표 |
| `cam01_*_holdout.csv` | 위 파일 중 holdout 점만 실측 좌표와 함께 뽑은 것 |
| `holdout_designated.json` | **공식** 평가 결과 (role=fit 4점 고정) |
| `holdout_loo-all.json` | 보조 진단 (leave-one-out, 남은 9점 최소자승) |
| `holdout_loo-quad.json` | 보조 진단 (leave-one-out, 최대 면적 4점) |
| `cost_benchmark.json` | frame당 추가 비용 (FPS 하락률은 추정치, `is_official: false`) |
| `zone_eval_handover.md` | 채택 기준 2~5번 측정에 필요한 영상별 준비 상태·대응표 |
| `zone_intervals_draft.csv` | B handover 시점의 Zone interval 빈 뼈대 artifact |
| `zone_path_comparison.json` | **공식** 채택 기준 2~5번 측정 결과 (영상 12개) |
| `_checksums.md` | 위 파일과 calibration config의 SHA-256 |

runtime calibration config는 계약 위치인 `configs/camera_calibration/`에 있다.
최종 촬영 manifest와 reviewed Zone ground truth는 각각
`data/annotations/phase4/zone_eval/recordings_manifest.csv`,
`data/annotations/phase4/zone_intervals.csv`에 있다.

Zone 경로 비교(`zone_path_comparison.json`)가 공식 실행에서 대조하는 동결 입력은
`data/annotations/phase4/zone_eval/`에 있다. `track_identity.csv`는 다중 인원
영상의 대상 Track과 그 사람을 누가 언제 확인했는지, `input_checksums.csv`는
영상별 calibration·image Zone·floor Zone의 SHA-256을 담는다. 경로만 맞고 내용이
바뀐 파일로 공식 결과가 만들어지는 것을 이 두 파일이 막는다.

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
  --picked docs/phase4_homography/cam01_img7330_picked.csv \
  --picked docs/phase4_homography/cam01_img7331_picked.csv \
  --picked docs/phase4_homography/cam01_img7332_picked.csv \
  --picked docs/phase4_homography/cam01_img7333_picked.csv \
  --picked docs/phase4_homography/cam01_img7334_picked.csv \
  --picked docs/phase4_homography/cam01_img7385_picked.csv \
  --picked docs/phase4_homography/cam01_img7387_picked.csv \
  --picked docs/phase4_homography/cam01_img7388_picked.csv \
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

# 채택 기준 2~5번 — 원본 영상이 있어야 한다(zone_eval_handover.md의 경로 생성 절차)
python scripts/cache_zone_foot_points.py \
  --manifest data/annotations/phase4/recordings_manifest.csv \
  --repo-root . \
  --output outputs/phase4_zone_eval/foot_points.json

python scripts/evaluate_zone_paths.py \
  --cache outputs/phase4_zone_eval/foot_points.json \
  --manifest data/annotations/phase4/recordings_manifest.csv \
  --intervals data/annotations/phase4/zone_intervals.csv \
  --review-plan data/annotations/phase4/zone_eval/recording_review_plan.csv \
  --output docs/phase4_homography/zone_path_comparison.json
```

`--track-selection gt-overlap`은 진단용이다. ground truth 구간에 오래 머문
Track을 고르므로 여러 명이 등장하는 영상에서 대상이 아닌 사람을 고를 수 있다
(`IMG_7385`가 실제로 그렇다). 공식 수치는 기본값 `longest`로 만든다.

## 재현의 범위

**수치는 재현되고, 바이트는 플랫폼에 따라 다를 수 있다.** 결과의 실수는 소수점
9자리로 반올림해 저장하지만, OpenCV 빌드가 다르면 같은 입력에서도 부동소수점
연산이 1e-16 수준으로 갈려 마지막 자리가 달라질 수 있다.

- **같은 환경에서 다시 실행하면** 바이트 단위로 같은 파일이 나온다.
- **다른 플랫폼에서 실행하면** 보고 지표(위치·관측 수, 평균, p95, 최대)는 그대로
  나오지만 JSON 바이트는 다를 수 있다. 재현 여부는 이 지표로 판단한다.
- **`_checksums.md`의 SHA-256은 커밋된 파일의 무결성 검증용이다.** 다른 환경에서
  다시 실행한 결과와 대조하는 값이 아니다.
- **줄바꿈은 플랫폼과 무관하게 LF다.** 결과 JSON을 바이너리로 쓴다. 예전에는
  Windows 텍스트 모드가 `\n`을 `\r\n`으로 바꿔 같은 입력에서도 파일이 달라졌다.

## 읽을 때 주의할 것

**`is_official`을 먼저 본다.** `holdout_designated.json`만 `true`다. runtime
config는 `role == "fit"`인 점만 `image_points_px`에 담으므로 실제 배포되는 변환은
그 4점으로 만든 것 하나다. leave-one-out 결과는 다른 조합으로 만든 행렬의
정확도이므로 runtime 후보의 성능이 아니다.

**`contract.meets_contract`가 `false`다.** `phase4_contract_v1`은 holdout
10위치·20관측을 요구한다. 클립 13개로 관측은 78회가 됐지만 기준점이 10개뿐이라
fit 4를 뺀 **위치가 6개로 고정**돼 요건을 채우지 못한다. 수치는 진단으로 읽고
공식 acceptance 판정에는 쓰지 않는다. 허용값도 동결하지 못했다. 두 사유로 채택
기준 1번은 판정 불가이고, PoC 전체 판정은 **미채택**이다
(`docs/homography_calibration.md` 7.7절).

**좌표 단위가 확정되지 않았다.** `--unit-cm 1`로 실행했으므로 결과의
`*_m` 필드는 meter가 아니라 **촬영 기록 원단위를 100으로 나눈 값**이다. 실측
단위가 확인되면 그 배수만큼 다시 환산해야 한다. 자세한 사정은
`docs/homography_calibration.md` 7.1절에 있다.

**카메라가 클립마다 움직였다.** 클립 간 최대 8.5도 회전이 측정돼 단일
calibration을 전 클립에 적용할 수 없다. 클립 13개에서 기준점을 각각 다시 찍어
평가했다. 클립을 늘려 관측 수는 78회로 계약 요건 20회를 넘겼지만, 기준점이
10개뿐이라 **holdout 위치는 6개로 고정**된다. 위치 수는 클립이 아니라 촬영
현장의 기준점 개수가 정하므로 이 데이터로는 더 늘릴 수 없다.

`_picked.csv`는 picker가 `--output` 옆에 쓰므로 기본 위치는
`configs/camera_calibration/`이다. 평가 입력은 여기 모아 체크섬을 남기므로
찍은 뒤 이 디렉터리로 옮긴다.
