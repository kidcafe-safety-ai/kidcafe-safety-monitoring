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

| 클립 | `calibration_version` | calibration JSON | image Zone | floor Zone |
|---|---|---|---|---|
| clip00 (calibration 촬영) | `2026-08-07-clip00-orig` | `configs/camera_calibration/cam01_clip00_orig.json` | `data/zones/image_cam01.json` | `data/zones/floor_cam01.json` |
| clip01 (시나리오) | `2026-08-07-clip01` | `configs/camera_calibration/cam01_clip01.json` | 없음 | 없음 |

`data/zones/*_cam01.json` 두 파일은 **clip00 프레임에서 찍은 것**이다
(`pick_zone_polygon.py`가 한 번의 클릭에서 두 형식을 함께 생성). clip01에
그대로 쓰면 카메라 이동만큼 Zone이 어긋난다.

`camera_id`는 전 클립 `cam01`이다. 카메라는 1대였고 위치만 흔들렸다.

## 비어 있는 것

측정 대상이 될 시나리오 영상마다 아래가 필요하다. clip00·clip01 외 클립은
전부 미착수다.

- [ ] 원본 파일명 ↔ `video_id` 대응 확정
- [ ] 기준점 픽셀 재클릭 → `<video_id>_picked.csv`
- [ ] calibration JSON (`configs/camera_calibration/<camera>_<clip>.json`)
- [ ] Zone 꼭짓점 재클릭 → image Zone JSON
- [ ] Zone 진입·이탈 interval 검수 (A 역할)

## 원본 파일명 ↔ `video_id` 대응표

`video_id`는 `docs/data_sources.md`의 명명 규칙을 따른다.

```text
P4_S<2자리>_A<2자리>_<소문자 scenario>_<2자리 take>_cam<2자리>
```

| 원본 파일명 | `video_id` | `calibration_version` | 용도 |
|---|---|---|---|
| (clip00 원본) | — | `2026-08-07-clip00-orig` | calibration 전용, 시나리오 아님 |
| (clip01 원본) | 미정 | `2026-08-07-clip01` | Zone 시나리오 후보 |
| … | 미정 | 미생성 | |

**원본 파일명 칸은 B가 채운다.** 원본은 개인정보가 있어 Git에 넣지 않으므로
(`.gitignore`의 `data/videos/*`) 파일명만 여기 기록하고 실물은 별도 저장소에
둔다. 대응표가 없으면 `recordings_manifest.csv`의 `video_id`와 실제 촬영분을
연결할 수 없다.

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

`zone_id`는 현재 `play_floor` 하나다(`data/zones/image_cam01.json`).

## 측정 실행 조건

위 항목이 한 클립에 대해 모두 채워지면 그 클립만으로 2~5번을 측정할 수 있다.
전 클립을 기다릴 필요는 없다. 두 경로는 같은 frame·같은 Track·같은 foot
point를 입력으로 받고 Zone 정의만 다르므로, 차이가 좌표 경로 차이로 귀속된다.
