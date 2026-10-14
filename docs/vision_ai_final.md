# Vision AI 런타임 최종 운영 가이드

> 담당: A — Vision AI·입력 처리·시스템 통합
>
> 기준: Final Phase 기능 동결 후보
>
> 정책: 신규 모델·알고리즘을 추가하지 않고 기존 실행 경로를 안정화한다.

## 목적

최종 시연과 공개 릴리스에서 여러 원본 영상을 연속 처리하고, 영상 경계의 추적
상태를 안전하게 초기화하며, API와 대시보드에 종료 상태를 일관되게 전달한다.
모델·추적기·API 스키마를 새로 확장하지 않고 기존 파이프라인의 재현성과 운영
안정성을 보완하는 범위다.

## 전체 처리 흐름

```text
File / Webcam / RTSP
→ YOLO 사람 탐지
→ ByteTrack 또는 PoseTracker
→ Zone 판정과 ENTER·EXIT·DWELL 계열 Event
→ 선택적 FallPipeline과 FALL_SUSPECT·Cause
→ EventWriter 로컬 저장
→ AsyncEventDispatcher 비차단 전송
→ FastAPI → SQLite
→ CurrentStatus·LiveFrame → React Dashboard
```

- 기본 실행은 `yolo26n.pt`와 ByteTrack을 사용하며 낙상 감지는 비활성이다.
- 낙상 감지를 명시적으로 활성화하면 동결된 E1 profile에 따라
  `yolo26n-pose.pt`, PoseTracker, 보조 낙상 모델을 사용한다.
- API 전송은 worker thread에서 처리한다. 전송 장애가 frame 추론 loop로
  전파되지 않으며 최종 실패 Event는 로컬 JSONL에 보존한다.
- 자세한 Event·CurrentStatus 계약은
  [`interfaces.md`](interfaces.md)와 [`api_contract.md`](api_contract.md)를 따른다.

## 입력·상태 관리 구조

- `FileVideoSource`: 단일 파일과 동일 파일 반복을 담당한다.
- `FilePlaylistSource`: 여러 파일과 playlist 전체 반복을 담당한다.
- `WebcamSource`: 로컬 카메라 입력을 담당한다.
- `RTSPSource`: 최신 frame 우선 방식으로 지연 누적을 제한하며 인증정보가
  `source_id`와 오류 로그에 노출되지 않도록 처리한다.
- 파일 반복·전환은 모델 수명주기와 분리한다. 모델은 한 번만 로드하고,
  Tracker·EventManager·FallPipeline의 영상별 상태만 초기화한다.
- playlist의 모든 영상은 출력 writer 계약상 첫 영상과 같은 해상도와 FPS를
  사용해야 하며, 처리 시작 전에 전체 파일의 접근성과 형식을 검사한다.

## Detection·Tracking·Event 구조

- 사람 탐지와 일반 Zone Event는 YOLO26n·ByteTrack 경로를 기준으로 한다.
- Zone polygon 포함 여부와 시간 기반 상태를 조합해 ENTER·EXIT·DWELL 및
  안전정책 Event를 생성한다.
- 낙상 경로는 PoseTracker 결과와 E1 보조 모델을 `FallPipeline`에서 결합한다.
  낙상 직전 주변 Track의 근거가 충분한 경우에만 Cause를 추가하고, 근거가
  부족하면 `cause=null`을 유지한다.
- Event는 먼저 로컬에 저장한 뒤 비차단 dispatcher에 등록한다. API 장애가
  발생해도 추론과 로컬 저장은 계속된다.

## 채택 모델과 동결 설정

최종 낙상 profile은 [`fall_e1_selected.json`](../configs/fall_e1_selected.json)에
동결돼 있다.

| 항목 | 최종 값 |
| --- | --- |
| 사용 범위 | 목표 키즈카페 카메라 구도의 명시적 opt-in |
| 낙상 모델 | `fall_detector_phase4_e1.pt` |
| 모델 SHA-256 | `41701c4686212447271f4dd81b71a14704b76cb9f38fe1c727d446477fbdd28b` |
| Tracker | `yolo26n-pose.pt` + PoseTracker |
| Tracker 모델 SHA-256 | `eb3bb8268828aeaf515cec23a4bfafd793944a86fe9af94ba7823609c14522a9` |
| Fall config SHA-256 | `50ebecd28772d9ee81a2d79afd75f3ebbb8dfe4f19a7365ed03cf1039bdef8a6` |
| 보조 모델 interval | 3 frames |
| Pose NORMAL gate | 활성 |
| 기본 활성화 | 비활성, `--fall-detection-enabled`로만 활성화 |

모델 파일은 Git에 포함하지 않는다. 실행 전 다음 값이 동결 profile과 일치하는지
확인한다.

```bash
shasum -a 256 outputs/fall_training/models/fall_detector_phase4_e1.pt
```

## 최종 성능과 채택 판단

목표 환경 A03 actor-disjoint test의 최종 결과는 다음과 같다.

| 지표 | 결과 |
| --- | ---: |
| Recall | 14/15 (93.3%) |
| timely Recall | 14/15 (93.3%) |
| FAR | 0.0/min |
| 평균 onset latency | 0.441초 |
| late detection | 0 |
| duplicate Event | 0 |
| early false alarm | 0 |

Cause·Tracking 평가에서는 Cause top-1 `3/8`, `cause=null` specificity `24/24`를
기록했다. ByteTrack, BoT-SORT ReID OFF, BoT-SORT ReID ON을 비교했지만 사전에
정한 Cause 채택 기준을 충족하지 못해 production association tracker는
ByteTrack을 유지했다. 상세 낙상 평가와 최종 운영 제약은
[`fall_evaluation.md`](fall_evaluation.md)와
[`README.md`](../README.md#검증-범위와-알려진-제약)를 기준으로 한다.

이 수치는 통제된 성인 재연과 한 목표 카메라 구도에 한정된다. 장시간 정상 행동
RTSP 검증과 Cause 정확도 기준이 완료되지 않았으므로 낙상 감지는 기본 비활성으로
유지한다.

## 최종 동작

- 단일 파일은 `--file-repeat-count`로 모델 재로딩 없이 반복할 수 있다.
- 여러 파일은 `--file-playlist`에 지정한 순서대로 처리한다.
- 파일 전환 또는 반복 경계에서 Tracker, EventManager, FallPipeline 상태를
  초기화한다. 이미 로드한 모델 인스턴스는 재사용한다.
- 각 원본 영상과 반복 회차의 frame 번호는 0부터 다시 시작한다. Event timestamp와
  Live Frame frame 번호는 현재 `video_source`의 영상 내 상대 시각을 나타낸다.
- 플레이리스트의 해상도와 FPS는 첫 파일과 같아야 한다. 처리 시작 전에 전체
  파일을 검사하고, 형식이 다르거나 파일을 열 수 없으면 원인이 포함된 오류로
  중단한다.
- CurrentStatus는 실제 처리 속도가 아닌 입력 영상의 frame/FPS 시간축으로
  갱신한다. 전송 간격은 playlist 전체의 연속 시간축으로 계산한다.
- 파이프라인 종료 시 모든 구역을 `current_count=0`, `risk_level=NORMAL`로 만든
  최종 상태를 전송한 뒤 dispatcher를 닫는다.
- Live Frame은 원본 종횡비를 유지해 최대 640×480 안으로 축소하고 작은 영상은
  확대하지 않는다.

## 실행 예시

일반 실행 기본값은 기존과 동일하다.

```bash
python -m src.main \
  --source-type file \
  --source data/videos/test.mp4 \
  --zones data/zones/sample.json
```

최종 시연용 플레이리스트 예시:

```bash
python -m src.main \
  --source-type file \
  --file-playlist data/videos/demo_01.mp4 data/videos/demo_02.mp4 \
  --file-repeat-count 2 \
  --zones data/zones/sample.json \
  --api-url http://localhost:8000 \
  --live-frame-enabled \
  --live-frame-fps 6 \
  --live-frame-quality 70 \
  --status-update-interval-sec 0.5
```

시연용 전송값은 명령행에서 명시한다. 운영 기본값을 시연 환경에 맞춰 변경하지
않는다.

## 전체 E2E 실행 순서

1. Python 3.10 가상환경에서 `requirements.txt`를 설치한다.
2. `.env.example`을 로컬 `.env`로 복사하고 실제 비밀 값은 Git에 추가하지 않는다.
3. `python scripts/init_zone_runtime.py`로 runtime Zone 파일을 준비한다.
4. `docker compose up --build -d`로 FastAPI·SQLite·Frontend를 실행한다.
5. `/health`와 Dashboard 접근을 확인한다.
6. 모델 SHA-256을 동결 profile과 대조한다.
7. 고정 영상으로 Vision AI를 실행하고 Event·Status·LiveFrame을 전송한다.
8. Event의 API 응답과 SQLite 저장값, Dashboard 표시를 대조한다.
9. API를 중단한 동안에도 추론과 로컬 Event 저장이 계속되는지 확인한다.
10. API 복구 후 Event·Status 전송과 Dashboard 갱신을 확인한다.
11. playlist 경계에서 이전 Track·Event·Fall 상태가 제거되는지 확인한다.
12. 종료 후 모든 Zone이 `0명/NORMAL`인지 확인한다.

최종 E2E는 A/B/C PR이 모두 병합된 `main`과 고정된 모델·영상·설정으로 한 번 더
수행한다. 역할별 브랜치 결과를 최종 통합 결과로 대신하지 않는다.

## 검증 항목

- 파일 반복 순서와 전체 frame 수
- 되감기 실패 시 명확한 오류 처리
- 플레이리스트 순서, 반복, 파일 열기 실패, FPS·해상도 불일치
- 영상별 Event·Live Frame frame 번호 및 timestamp 시간축 초기화
- 영상 경계의 Tracker·EventManager·FallPipeline 초기화와 모델 재사용
- 구성된 모든 구역의 CurrentStatus 포함 및 위험 구역 risk 정책
- 종료 시 0명/NORMAL 상태 전송
- 가로·세로 영상의 종횡비 보존 및 작은 frame 비확대

관련 테스트:

- `tests/test_input_sources.py`
- `tests/test_live_frame_client.py`
- `tests/test_main_dispatcher_integration.py`

기존 API 장애·비차단 회귀:

- `tests/test_async_event_dispatcher.py`
- `tests/test_event_api_client.py`

현재 A 변경에서 확인한 결과:

- 입력·Live Frame 변경 관련 테스트: 14 passed
- 입력·Live Frame 전체 회귀: 60 passed, 2 skipped
- Main dispatcher 통합 테스트: 12 passed
- 실제 영상 playlist 경계 전환: 통과
- 실제 영상 2회 반복: 40/40 frame 통과
- Ruff 및 Python 3.10 문법 검사: 통과

전체 `flake8 src tests`, `pytest -q`, Frontend test·build, Docker E2E와 깨끗한
clone 재현 결과는 세 역할 PR 병합 후 최종 릴리스 기록에 남긴다.

## Final Phase A 변경 요약

- 파일 반복과 다중 영상 playlist를 모델 재로딩 없이 지원한다.
- 입력 경계에서 Tracker·EventManager·FallPipeline 상태를 초기화한다.
- Event·Tracking·Live Frame의 frame 번호를 각 원본 영상 기준으로 초기화한다.
- playlist 전체 파일의 접근성과 형식을 처리 전에 검증한다.
- Live Frame의 종횡비를 보존하고 작은 frame을 확대하지 않는다.
- CurrentStatus 갱신 주기를 입력 영상 시간축에 맞춘다.
- 종료 시 구성된 모든 Zone의 상태를 `0명/NORMAL`로 초기화한다.
- 일반 기본값과 시연용 전송 설정을 분리한다.
- 입력 오류·형식 불일치·되감기 실패를 명시적인 오류로 처리한다.

## 공개 범위와 제한 사항

- 원본 영상, 학습 데이터, 모델 weight, 환경변수, 카메라 인증정보는 저장소에
  포함하지 않는다.
- 플레이리스트는 출력 영상 writer 계약 때문에 동일 해상도와 FPS만 지원한다.
- Event의 `zone_name` 확장은 이번 종료 범위에 포함하지 않는다. 현재 계약의
  `zone_id`를 사용하고 화면 표시명은 구역 설정에서 보완한다.
- 시연 스크립트나 로컬 절대 경로는 핵심 런타임 변경과 분리한다.
- selected 낙상 모델은 Git에 포함하지 않으며 profile의 SHA-256으로 무결성을
  확인한다.
- 장시간 RTSP, 인증·인가, RTSP 자동 재연결, production Web serving은 이번
  종료 범위가 아니다.
