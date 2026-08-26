# Zone 정확도(채택 기준 2~5번) 측정 준비 상태

채택 기준 2~5번(Zone inside/outside 정확도, Zone 오판정, ENTER·EXIT Event 오류,
빠른 반전)은 Zone 진입·이탈 ground truth가 있어야 측정할 수 있다. 이 문서는
영상별 입력과 완료된 ground truth를 한 장에 모은다.

판정 자체는 미채택으로 확정됐다(`docs/homography_calibration.md` 7.7절). 2~5번
측정은 채택을 되돌리기 위한 것이 아니라 다음 촬영의 사전 근거를 남기기 위한
것이다.

## 왜 영상마다 따로 필요한가

촬영 중 카메라가 움직였다. 클립 간 최대 8.5도 회전·104px 이동이 측정됐다
(7.1절). 그래서 **하나의 calibration을 전 클립에 쓸 수 없다.** 클립마다

1. 기준점을 다시 찍어 calibration JSON을 만들고,
2. 같은 클립에서 Zone 꼭짓점을 다시 찍어 image Zone을 만들어야

두 경로가 같은 물리적 Zone을 보고 비교된다. 다른 클립의 calibration을 쓰면
측정된 차이가 변환 성능인지 카메라 이동인지 구분되지 않는다.

## 현재 준비된 것

| 클립 | 원본 | `calibration_version` | calibration JSON | image Zone | floor Zone |
|---|---|---|---|---|---|
| clip00 (calibration 촬영) | `IMG_7325.MOV` | `2026-08-07-clip00-orig` | `cam01_clip00_orig.json` | `image_cam01.json` | `floor_cam01.json` |
| clip01 | `IMG_7326.MOV` | `2026-08-07-clip01` | `cam01_clip01.json` | `image_cam01_clip01.json` | `floor_cam01_clip01.json` |
| img7327 | `IMG_7327.MOV` | `2026-08-07-img7327` | `cam01_img7327.json` | `image_cam01_img7327.json` | `floor_cam01_img7327.json` |
| img7328 | `IMG_7328.MOV` | `2026-08-07-img7328` | `cam01_img7328.json` | `image_cam01_img7328.json` | `floor_cam01_img7328.json` |
| img7329 | `IMG_7329.MOV` | `2026-08-07-img7329` | `cam01_img7329.json` | `image_cam01_img7329.json` | `floor_cam01_img7329.json` |
| img7330 | `IMG_7330.MOV` | `2026-08-07-img7330` | `cam01_img7330.json` | `image_cam01_img7330.json` | `floor_cam01_img7330.json` |
| img7331 | `IMG_7331.MOV` | `2026-08-07-img7331` | `cam01_img7331.json` | `image_cam01_img7331.json` | `floor_cam01_img7331.json` |
| img7332 | `IMG_7332.MOV` | `2026-08-07-img7332` | `cam01_img7332.json` | `image_cam01_img7332.json` | `floor_cam01_img7332.json` |
| img7333 | `IMG_7333.MOV` | `2026-08-07-img7333` | `cam01_img7333.json` | `image_cam01_img7333.json` | `floor_cam01_img7333.json` |
| img7334 | `IMG_7334.MOV` | `2026-08-07-img7334` | `cam01_img7334.json` | `image_cam01_img7334.json` | `floor_cam01_img7334.json` |
| img7385 | `IMG_7385.MOV` | `2026-08-07-img7385` | `cam01_img7385.json` | `image_cam01_img7385.json` | `floor_cam01_img7385.json` |
| img7387 | `IMG_7387.MOV` | `2026-08-07-img7387` | `cam01_img7387.json` | `image_cam01_img7387.json` | `floor_cam01_img7387.json` |
| img7388 | `IMG_7388.MOV` | `2026-08-07-img7388` | `cam01_img7388.json` | `image_cam01_img7388.json` | `floor_cam01_img7388.json` |

calibration JSON은 `configs/camera_calibration/`, Zone은 `data/zones/` 아래다.
clip00은 기준점만 촬영한 clip이라 Zone 라벨링 대상이 아니다. **Zone 클립은 12개**이고
12개 모두 ground truth 검수를 마쳤다. `IMG_7386`은 촬영 상태가 나빠 제외했다.

원본 대응은 `scripts/verify_clip_match.py`로 확인했다. 기록된 기준점 픽셀을
프레임에 겹쳐 그려 테이프 위에 얹히는지 눈으로 대조하는 방식이다. 클립을 더
추가할 때도 같은 방법으로 확인한다.

`data/zones/*_cam01.json`(접미사 없는 것)은 **clip00 프레임에서 찍은 것**이고,
`*_cam01_clip01.json`은 clip01에서 다시 찍은 것이다. 클립을 섞어 쓰면 카메라
이동만큼 Zone이 어긋난다.

`camera_id`는 전 클립 `cam01`이다. 카메라는 1대였고 위치만 흔들렸다.

### 클립별 재클릭이 실제로 카메라 이동을 상쇄했다

같은 회색 테이프를 13개 클립에서 각각 찍어 78개 쌍을 비교했다.

| 좌표계 | 평균 | 최대 |
|---|---:|---:|
| image (픽셀) | 59.6 px | **131.0 px** |
| floor (원단위) | 0.43 | **1.60** |

픽셀로는 최대 131px 어긋난 쌍이 있는데, 클립별 calibration을 적용하면 동일한
물리적 Zone의 floor 좌표 편차가 최대 1.60 원단위 안에서 유지된다. 두 값은 단위가
달라 직접 비교하지 않는다.
클립마다 calibration을 다시 만들면 고정되지 않은 카메라로도 같은 물리적 Zone을
가리킬 수 있다는 뜻이다. 7.3절의 오차 수치와 별개로 얻은 독립적인 근거다.

이 값 자체는 채택 기준 2~5번이 아니다. 두 좌표 경로가 같은 Zone을 얼마나 같게
표현하는지를 볼 뿐이고, 판정 정확도는 A의 ground truth가 있어야 나온다.

## Ground truth 완료 상태 (2026-08-18)

라벨링 대상 12개 클립의 `video_id`, 촬영 manifest, ENTER·EXIT·DWELL ground
truth를 확정했다. 원본과 calibration 대응은 `verify_clip_match.py`로 다시
확인했고, manifest의 영상 SHA-256도 실제 파일과 대조했다.

최종 artifact:

- `data/annotations/phase4/zone_eval/recordings_manifest.csv`
- `data/annotations/phase4/zone_intervals.csv`
- `data/annotations/phase4/zone_eval/recording_review_plan.csv`

12개 interval은 모두 `reviewed`다. 기존 image polygon과 Homography 판정 결과를
표시하지 않은 blind 검수 화면에서 원본의 회색 테이프와 두 발 사이 바닥 중심을
보고 ENTER·EXIT를 지정했다. `dwell_start_frame`은 5초 threshold와 영상 FPS로
자동 계산했다. 각 행의 `notes`에는 `review_mode=blind`,
`zone_reference=hidden`, `dwell_threshold_sec=5`를 기록해 검수 provenance를
보존한다.

## 확장 클립 검수 결과

`IMG_7330`~`7334`, `7385`, `7387`, `7388` 여덟 개는 calibration과 floor·image
Zone 대응을 유지한 상태로 추가 검수를 마쳤다. 측정 표본은 ENTER·EXIT 8건에서
24건으로 늘어났다.

`IMG_7385`는 두 actor가 동시에 Zone을 통과하므로 manifest에 `actor_ids=A01|A02`,
`primary_actor_id=A01`을 기록한다. 이 클립의 ENTER·EXIT ground truth는 파란 상의
`A01`의 두 발 사이 바닥 중심만을 대상으로 한다.

클립별 holdout 오차는 13개 전부 1.03~1.17에 모여 있다. 기준점 순서를 잘못 찍은
클립이 있었다면 그 클립만 값이 튀었을 것이므로 입력 검증 역할도 한다.

## 원본 파일명 ↔ `video_id` 대응표

`video_id`는 `docs/data_sources.md`의 명명 규칙을 따른다.

```text
P4_S<2자리>_A<2자리>_<소문자 scenario>_<2자리 take>_cam<2자리>
```

| 원본 파일명 | `video_id` | 용도 |
|---|---|---|
| `IMG_7325.MOV` | — | calibration 전용, 시나리오 아님 |
| `IMG_7326.MOV` | `P4_S01_A01_zone_enter_exit_01_cam01` | Zone 라벨링 대상 |
| `IMG_7327.MOV` | `P4_S01_A02_zone_enter_exit_01_cam01` | Zone 라벨링 대상 |
| `IMG_7328.MOV` | `P4_S01_A01_zone_enter_exit_02_cam01` | Zone 라벨링 대상 |
| `IMG_7329.MOV` | `P4_S01_A02_zone_enter_exit_02_cam01` | Zone 라벨링 대상 |
| `IMG_7330.MOV` | `P4_S01_A02_zone_enter_exit_03_cam01` | Zone 라벨링 완료 |
| `IMG_7331.MOV` | `P4_S01_A02_zone_enter_exit_04_cam01` | Zone 라벨링 완료 |
| `IMG_7332.MOV` | `P4_S01_A01_zone_enter_exit_03_cam01` | Zone 라벨링 완료 |
| `IMG_7333.MOV` | `P4_S01_A02_zone_enter_exit_05_cam01` | Zone 라벨링 완료 |
| `IMG_7334.MOV` | `P4_S01_A01_zone_enter_exit_04_cam01` | Zone 라벨링 완료 |
| `IMG_7385.MOV` | `P4_S01_A01_zone_enter_exit_06_cam01` | A01 대상 Zone 라벨링 완료 |
| `IMG_7387.MOV` | `P4_S01_A01_zone_enter_exit_05_cam01` | Zone 라벨링 완료 |
| `IMG_7388.MOV` | `P4_S01_A02_zone_enter_exit_06_cam01` | Zone 라벨링 완료 |

원본은 개인정보가 있어 Git에 넣지 않으므로(`.gitignore`의 `data/videos/*`)
파일명만 여기 기록하고 실물은 별도 저장소에 둔다.

### 측정용 영상 경로 생성

선별한 원본 12개를 `data/videos/phase4_zone/`에 둔 뒤 저장소 루트에서 다음 명령을
실행한다. 원본을 복사하거나 재인코딩하지 않고 상대 symlink만 만든다.

```bash
mkdir -p data/videos/phase4_zone/contracts
ln -s ../IMG_7326.MOV data/videos/phase4_zone/contracts/P4_S01_A01_zone_enter_exit_01_cam01.mp4
ln -s ../IMG_7328.MOV data/videos/phase4_zone/contracts/P4_S01_A01_zone_enter_exit_02_cam01.mp4
ln -s ../IMG_7327.MOV data/videos/phase4_zone/contracts/P4_S01_A02_zone_enter_exit_01_cam01.mp4
ln -s ../IMG_7329.MOV data/videos/phase4_zone/contracts/P4_S01_A02_zone_enter_exit_02_cam01.mp4
ln -s ../IMG_7332.MOV data/videos/phase4_zone/contracts/P4_S01_A01_zone_enter_exit_03_cam01.mp4
ln -s ../IMG_7334.MOV data/videos/phase4_zone/contracts/P4_S01_A01_zone_enter_exit_04_cam01.mp4
ln -s ../IMG_7387.MOV data/videos/phase4_zone/contracts/P4_S01_A01_zone_enter_exit_05_cam01.mp4
ln -s ../IMG_7385.MOV data/videos/phase4_zone/contracts/P4_S01_A01_zone_enter_exit_06_cam01.mp4
ln -s ../IMG_7330.MOV data/videos/phase4_zone/contracts/P4_S01_A02_zone_enter_exit_03_cam01.mp4
ln -s ../IMG_7331.MOV data/videos/phase4_zone/contracts/P4_S01_A02_zone_enter_exit_04_cam01.mp4
ln -s ../IMG_7333.MOV data/videos/phase4_zone/contracts/P4_S01_A02_zone_enter_exit_05_cam01.mp4
ln -s ../IMG_7388.MOV data/videos/phase4_zone/contracts/P4_S01_A02_zone_enter_exit_06_cam01.mp4
```

`.mp4`는 촬영 파일명 계약을 따르는 로컬 별칭이다. symlink 대상은 원본 `.MOV`로
유지되며 파일 내용과 SHA-256은 바뀌지 않는다. OpenCV·FFmpeg는 확장자가 아니라
컨테이너 내용을 읽으므로 이 경로를 그대로 사용할 수 있다. 링크가 이미 있으면
명령이 실패하게 두어 기존 경로를 조용히 덮어쓰지 않는다.

생성 후 다음 명령으로 원본 연결과 SHA-256을 확인한다.

```bash
python scripts/validate_phase4_zone_intervals.py \
  --manifest data/annotations/phase4/zone_eval/recordings_manifest.csv \
  --intervals data/annotations/phase4/zone_intervals.csv \
  --repo-root . --verify-files --verify-checksums --require-reviewed
```

선별한 12개 영상은 primary actor가 Zone 밖에서 들어와 내부를 지난 뒤 다시 나가는
완전한 왕복 구간이다. 기존 직접 촬영 annotation과 복장을 대조해 파란 상의는
`A01`, 회색 상의는 `A02`로 연결하고 `zone_enter_exit`로 기록했다. 두 actor가 함께
등장하는 `IMG_7385`는 A01만 ground truth 대상으로 사용한다.

clip00은 기준점만 촬영한 clip이라 시나리오가 없다. `video_id`를 부여하지 않고
calibration 출처로만 기록한다.

## `zone_intervals.csv`

계약 위치인 `data/annotations/phase4/zone_intervals.csv`에 최종 ground truth를
기록했다. 검수 규칙은 `docs/data_sources.md`에 있고 핵심은 다음과 같다.

- `video_id`는 `recordings_manifest.csv`와 정확히 같아야 한다.
- `interval_index`는 같은 영상·Zone에서 1부터, 중복 없이.
- `enter_frame`은 두 발 사이 바닥 중심이 Zone 안으로 들어온 **첫** frame,
  `exit_frame`은 밖으로 나온 **첫** frame이다. `enter_frame < exit_frame`.
- dwell 기준 미충족이면 `dwell_start_frame`은 비워둔다.
- 가림 등으로 경계 frame이 불명확하면 `review_status`를 `needs_review`로 둔다.
- frame 번호는 0부터 시작한다.

`zone_id`는 현재 `play_floor` 하나다.

최종 값:

| `video_id` | ENTER | EXIT | DWELL start |
|---|---:|---:|---:|
| `P4_S01_A01_zone_enter_exit_01_cam01` | 126 | 372 | — |
| `P4_S01_A01_zone_enter_exit_02_cam01` | 110 | 402 | — |
| `P4_S01_A01_zone_enter_exit_03_cam01` | 127 | 707 | 427 |
| `P4_S01_A01_zone_enter_exit_04_cam01` | 111 | 580 | 411 |
| `P4_S01_A01_zone_enter_exit_05_cam01` | 160 | 724 | 460 |
| `P4_S01_A01_zone_enter_exit_06_cam01` | 197 | 565 | 497 |
| `P4_S01_A02_zone_enter_exit_01_cam01` | 125 | 415 | — |
| `P4_S01_A02_zone_enter_exit_02_cam01` | 133 | 444 | 433 |
| `P4_S01_A02_zone_enter_exit_03_cam01` | 86 | 372 | — |
| `P4_S01_A02_zone_enter_exit_04_cam01` | 114 | 798 | 414 |
| `P4_S01_A02_zone_enter_exit_05_cam01` | 133 | 721 | 433 |
| `P4_S01_A02_zone_enter_exit_06_cam01` | 141 | 536 | 441 |

한 영상에서 진입·이탈이 여러 번이면 행을 복제하고 `interval_index`를 1부터
매긴다.

## 측정 실행 조건

12개 클립의 측정 입력이 모두 준비됐다. 두 경로는 같은 frame·같은 Track·같은
foot point와 ground truth를 입력으로 받고 Zone 정의만 다르므로, 차이가 좌표 경로
차이로 귀속된다. 최종 표본은 ENTER 12건·EXIT 12건이며, 그중 8개 interval이
5초 dwell 기준을 충족한다.

## 측정 완료 (2026-08-18)

이 handoff는 끝났다. 위 입력으로 채택 기준 2~5번을 측정했고 결과는
`zone_path_comparison.json`과 `docs/homography_calibration.md` 7.4절에 있다.

두 좌표 경로는 정확도 91.695%, 오판정 552건, ENTER·EXIT Event 오류 0건, 빠른
반전 0건으로 **완전히 같았다.** 영상별 Event frame 번호까지 동일하다. image
Zone과 floor Zone을 같은 클릭에서 만들어 두 경로가 정의상 같은 판정을 내기
때문이며, 기준 2·3번 미달·4번 판정 불가·5번 통과로 기록했다.

`IMG_7385`는 두 사람이 T2·T3으로 잡혀 Track 선택 규칙에 따라 다른 사람이
평가된다. `scripts/verify_track_identity.py`로 확인한 결과 공식 규칙이 고른
T2가 `primary_actor_id`인 A01이다.
