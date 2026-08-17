# Zone 정확도(채택 기준 2~5번) 측정 준비 상태

채택 기준 2~5번(Zone inside/outside 정확도, Zone 오판정, ENTER·EXIT Event 오류,
빠른 반전)은 A 역할의 Zone 진입·이탈 ground truth가 있어야 측정할 수 있다. 이
문서는 그 측정을 시작하기 위해 **영상별로 무엇이 준비돼 있고 무엇이 비어
있는지**를 한 장에 모은다.

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
이 중 네 개(`IMG_7326`~`7329`)는 ground truth 검수가 끝났다. `IMG_7386`은 촬영
상태가 나빠 제외했다.

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

픽셀로는 최대 131px 어긋난 쌍이 있는데 floor 좌표로 옮기면 1.60 안에서
일치한다. 픽셀 차이가 floor 차이의 80배가 넘는다.
클립마다 calibration을 다시 만들면 고정되지 않은 카메라로도 같은 물리적 Zone을
가리킬 수 있다는 뜻이다. 7.3절의 오차 수치와 별개로 얻은 독립적인 근거다.

이 값 자체는 채택 기준 2~5번이 아니다. 두 좌표 경로가 같은 Zone을 얼마나 같게
표현하는지를 볼 뿐이고, 판정 정확도는 A의 ground truth가 있어야 나온다.

## 검수 대기 중인 클립 8개

`IMG_7330`~`7334`, `IMG_7385`, `7387`, `7388` 여덟 개는 calibration과 floor·image
Zone을 모두 만들어 뒀고 Zone 진입·이탈 ground truth만 없다. 검수가 되면 측정
표본이 ENTER·EXIT 8건에서 24건으로 늘어난다.

클립별 holdout 오차는 13개 전부 1.03~1.17에 모여 있다. 기준점 순서를 잘못 찍은
클립이 있었다면 그 클립만 값이 튀었을 것이므로 입력 검증 역할도 한다.

## 원본 파일명 ↔ `video_id` 대응표

`video_id`는 `docs/data_sources.md`의 명명 규칙을 따른다.

```text
P4_S<2자리>_A<2자리>_<소문자 scenario>_<2자리 take>_cam<2자리>
```

`IMG_7326`~`7329`의 `video_id`는 `recordings_manifest.csv`에서 확정됐다. 나머지
8개는 검수와 함께 부여된다. `IMG_7325`는 기준점만 촬영한 clip이라 `video_id`를
부여하지 않고 calibration 출처로만 기록한다.

원본은 개인정보가 있어 Git에 넣지 않으므로(`.gitignore`의 `data/videos/*`)
파일명만 여기 기록하고 실물은 별도 저장소에 둔다.

## `zone_intervals.csv` 초안

계약 위치는 `data/annotations/phase4/zone_intervals.csv`다. 헤더만 만든 초안을
`zone_intervals_draft.csv`로 함께 둔다. 검수 규칙은 `docs/data_sources.md`에
있고, 채우는 사람이 지켜야 할 핵심은 다음과 같다.

- `video_id`는 `recordings_manifest.csv`와 정확히 같아야 한다.
- `interval_index`는 같은 영상·Zone에서 1부터, 중복 없이.
- `enter_frame`은 foot point가 Zone 안으로 들어온 **첫** frame,
  `exit_frame`은 밖으로 나온 **첫** frame이다. `enter_frame < exit_frame`.
- dwell 기준 미충족이면 `dwell_start_frame`은 비워둔다.
- 가림 등으로 경계 frame이 불명확하면 `review_status`를 `needs_review`로 둔다.
- frame 번호는 0부터 시작한다.

`zone_id`는 현재 `play_floor` 하나다.

초안에는 **라벨링 대상 클립 4개의 뼈대 행**을 넣어뒀다. `zone_id`는 채웠고,
`notes`에 원본 파일명·`calibration_version`·해당 클립의 image Zone 경로를 적어
어느 영상을 보고 채우는 행인지 바로 알 수 있게 했다.

`video_id` 칸은 비어 있다. 계약이 `recordings_manifest.csv`와 정확히 같을 것을
요구하는데 그 manifest가 아직 없어서, 임의로 값을 넣으면 나중에 어긋난다.
manifest가 만들어지면 `notes`의 파일명으로 대응시켜 채우면 된다.

한 영상에서 진입·이탈이 여러 번이면 행을 복제하고 `interval_index`를 1부터
매긴다.

## 측정 실행 조건

위 항목이 한 클립에 대해 모두 채워지면 그 클립만으로 2~5번을 측정할 수 있다.
전 클립을 기다릴 필요는 없다. 두 경로는 같은 frame·같은 Track·같은 foot
point를 입력으로 받고 Zone 정의만 다르므로, 차이가 좌표 경로 차이로 귀속된다.
