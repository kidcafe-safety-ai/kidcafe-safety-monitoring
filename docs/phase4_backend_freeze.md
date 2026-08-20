# Phase 4 Backend·DB·RTSP 설정 동결

계획서 10절 B 역할 8월 17~20일 항목이다. 8월 20일 기능 개발 종료를 앞두고
Backend·DB·RTSP의 설정값과 실행 절차를 여기에 고정한다. 제출물의 "실행·재현
안내"와 최종 E2E가 이 문서를 기준으로 삼는다.

**동결 기준 커밋**: `a3b693c` (PR #49 머지 시점)
**동결일**: 2026-08-19
**대상**: Backend API, SQLite, Zone runtime, RTSP 입력, Event 판정 상수, 의존성

동결 이후 이 값들을 바꾸려면 11절 절차를 따른다.

---

## 1. 동결하지 않는 것

먼저 범위를 좁힌다. 아래는 이 문서의 동결 대상이 아니다.

| 항목 | 이유 |
|---|---|
| 낙상 모델·임계값 | A 역할이 별도 동결 (`docs/fall_evaluation.md`) |
| Frontend 상태·UI | C 역할이 별도 동결 |
| Homography calibration | 미채택 PoC, `calibration.enabled=false`로 비활성 |
| 촬영 데이터·annotation | 이미 `reviewed`로 동결, checksum 보존 |

---

## 2. Backend API

| 항목 | 값 | 정의 위치 |
|---|---|---|
| 프레임워크 | FastAPI 0.111.0 | `requirements-api.txt` |
| ASGI 서버 | uvicorn 0.30.1 (`[standard]`) | `requirements-api.txt` |
| 컨테이너 포트 | `8000` | `docker-compose.yml` |
| health endpoint | `GET /health` | `src/api/routers/health.py` |
| healthcheck | `urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)` | `docker-compose.yml` |

라우터 구성은 `src/api/main.py`의 `include_router` 순서를 그대로 둔다.

```text
health, events, status, live, summary, zones
```

---

## 3. SQLite

| 항목 | 값 |
|---|---|
| DB 경로 환경변수 | `KIDCAFE_DB_PATH` |
| 컨테이너 기본값 | `/app/outputs/kidcafe_events.db` |
| 호스트 볼륨 | `./outputs` → `/app/outputs` |

테이블 두 개를 유지한다.

**`events`** — `id`, `event_id`(UNIQUE), `event_type`, `track_id`, `zone_id`,
`zone_name`, `frame_number`, `video_time_sec`, `timestamp`, `bbox_json`,
`foot_point_json`, `confidence`, `video_source`, `created_at`

**`current_status`** — `source`(PK), `frame_number`, `active_track_count`,
`zone_occupancy_json`, `updated_at`

컬럼 추가는 `CREATE TABLE IF NOT EXISTS`가 처리하지 못하므로
`PRAGMA table_info`로 확인한 뒤 `ALTER TABLE`로 붙인다
(`src/api/database.py`). **동결 이후 컬럼 추가·삭제는 하지 않는다.**

`timestamp`는 영상 상대 시각이고 집계용 실제 시각은 `created_at`이다
(ADR-005). 두 값을 섞어 쓰지 않는다.

---

## 4. Zone runtime

| 항목 | 값 |
|---|---|
| 경로 환경변수 | `KIDCAFE_ZONES_PATH` |
| 컨테이너 기본값 | `/app/outputs/zones_runtime.json` |
| 로컬 기본값 | `outputs/zones_runtime.json` |
| seed (읽기 전용) | `data/zones/sample.json` |
| version token | `sha256:` + runtime 파일 bytes의 SHA-256 |

**Vision AI의 `--zones`와 API의 `KIDCAFE_ZONES_PATH`는 같은 파일을 가리켜야
한다.** 다르면 Dashboard에서 저장한 Zone이 추론에 반영되지 않는데, 화면상
저장은 성공한 것처럼 보여서 알아채기 어렵다. Docker 구성에서는 두 컨테이너가
같은 `./outputs` 볼륨을 공유해 이 조건을 만족한다.

`--zones` 기본값은 `data/zones/sample.json`이므로 **실제 운영·시연에서는
반드시 runtime 파일을 명시**한다.

---

## 5. RTSP 입력

값은 전부 `src/input/rtsp_source.py`의 모듈 상수다.

| 상수 | 값 | 뜻 |
|---|---|---|
| `_RTSP_FPS_FALLBACK` | `25.0` | 스트림이 fps를 보고하지 않을 때 |
| `_RTSP_READ_WAIT_SEC` | `0.05` | 최신 프레임 대기 간격 |
| `_RTSP_STALE_TIMEOUT_SEC` | `3.0` | 이 시간 새 프레임이 없으면 stale |
| `_RTSP_MAX_CONSECUTIVE_READ_FAILURES` | `30` | 연속 실패가 이 수를 넘으면 종료 |
| `_RTSP_RELEASE_JOIN_TIMEOUT_SEC` | `2.0` | release 시 thread join 대기 |

FFmpeg 옵션도 고정한다.

```text
OPENCV_FFMPEG_CAPTURE_OPTIONS = rtsp_transport;tcp|stimeout;5000000
```

UDP가 아니라 **TCP**를 쓴다. 무선 구간에서 UDP는 프레임 손실이 크고, 손실이
곧 Event 시간축 왜곡으로 이어진다. `stimeout`은 마이크로초 단위로 5초다.

### 인증정보

| 항목 | 값 |
|---|---|
| 사용자명 환경변수 | `KIDCAFE_RTSP_USERNAME` |
| 비밀번호 환경변수 | `KIDCAFE_RTSP_PASSWORD` |
| CLI 옵션 | `--rtsp-username-env`, `--rtsp-password-env` |

**URL에 계정·비밀번호를 직접 넣지 않는다.** `--rtsp-alias`로 별칭을 주면
Event와 로그의 `source_id`에 URL 대신 별칭이 기록된다. 시연·제출 자료에
카메라 주소가 남지 않도록 별칭 사용을 기본으로 한다.

### 시간축 계약

latest-frame 방식은 처리하지 못한 프레임을 버린다. 버린 프레임만큼 Event
시각이 밀리지 않도록 다음을 분리해 유지한다.

| 값 | 의미 |
|---|---|
| `capture_sequence` | 카메라가 만든 프레임 순번 (1부터) |
| `captured_monotonic` | 캡처 시각 (monotonic) |
| `processed_frame_number` | Vision AI가 실제로 처리한 프레임 수 |

ENTER·EXIT 확정, dwell, Event timestamp, 낙상 window, Cause lookback은 전부
**source 기준**으로 계산한다. `src/main.py`의 `_resolve_source_frame_number()`가
`capture_sequence`를 0-based `frame_number`로 바꿔 `EventManager`에 넘긴다.

---

## 6. Event 판정 상수

`src/events/event_manager.py`의 기본값을 유지한다.

| 상수 | 값 |
|---|---|
| `DEFAULT_ENTER_CONFIRM_SEC` | `0.3` |
| `DEFAULT_EXIT_CONFIRM_SEC` | `0.5` |
| `DEFAULT_TRACK_LOST_GRACE_SEC` | `0.5` |

Zone 측정에서 이 값들이 만든 확정 지연을 실측했다. ENTER는 평균 0.663초 늦게
확정되고 오판정 552건이 전부 한 방향(`false_outside`)이었다
(`docs/homography_calibration.md` 7.4절). **조정 근거는 있지만 8월 20일 이후
새로 시작하지 않는 작업(계획서 3절)이므로 Phase 4에서는 바꾸지 않는다.**
다음 Phase 검토 항목으로 넘긴다.

---

## 7. 낙상 기능 상태

| 항목 | 값 |
|---|---|
| 기본 활성 여부 | **비활성** (`parser.set_defaults(fall_detection_enabled=False)`) |
| 활성 옵션 | `--fall-detection-enabled` |
| config 기본 경로 | `configs/fall_detection.json` |

계획서 4절 "낙상 기능은 운영 목표 충족 전까지 opt-in·기본 비활성으로
유지한다"를 그대로 따른다. 시연에서 켤 때는 명시적으로 옵션을 준다.

---

## 8. 의존성

`requirements.txt`와 `requirements-api.txt`의 핀을 그대로 둔다. 동결에서
특히 중요한 것만 적는다.

| 패키지 | 버전 | 고정 이유 |
|---|---|---|
| `torch` | `2.5.1` | 2.6+에서 YOLO 로딩 시 `UnpicklingError` (ADR-002) |
| `ultralytics` | `8.4.56` | tracker 설정·API 호환 |
| `opencv-python` | `4.8.1.78` | RTSP FFmpeg 옵션 동작 확인 버전 |
| `shapely` | `2.0.1` | Zone polygon 판정 |
| `numpy` | `1.26.4` | shapely 2.0.1 휠이 numpy 1.x 빌드. 2.x면 API가 import 단계에서 죽는다 |
| `fastapi` | `0.111.0` | API 계약 |
| `pydantic` | `2.7.1` | 응답 schema |

`requirements-api.txt`의 `numpy` 핀을 지우면 pip이 numpy 2.x를 끌어와
컨테이너가 기동되지 않는다. 이 핀은 반드시 유지한다.

---

## 9. 실행 명령

### Backend + Frontend (Docker)

```bash
cp .env.example .env      # 최초 1회, 비밀번호는 비워둔다
docker compose up --build
```

- API: `http://localhost:8000`
- Dashboard: `http://localhost:3000`

### Vision AI — 파일 영상

```bash
python src/main.py \
  --source-type file \
  --source data/videos/<파일>.mp4 \
  --zones outputs/zones_runtime.json \
  --api-url http://localhost:8000
```

### Vision AI — RTSP 카메라

비밀번호는 현재 셸에만 넣고 파일에 남기지 않는다.

```bash
export KIDCAFE_RTSP_USERNAME=<계정>
export KIDCAFE_RTSP_PASSWORD=<비밀번호>

python src/main.py \
  --source-type rtsp \
  --source "rtsp://<호스트>:554/<경로>" \
  --rtsp-alias camera_01 \
  --zones outputs/zones_runtime.json \
  --api-url http://localhost:8000
```

연결만 먼저 확인하려면 `scripts/rtsp_camera_test.py`를 쓴다. 자세한 절차는
`docs/rtsp_camera.md`에 있다.

---

## 10. 장애 대응

실행 중 나올 수 있는 상태와 조치다. 증상만 보고 원인을 찾기 어려운 것들을
모았다.

| 증상 | 원인 | 조치 |
|---|---|---|
| API 컨테이너가 기동 직후 죽음, `numpy.core.multiarray failed to import` | `requirements-api.txt`의 numpy 핀이 빠져 2.x가 설치됨 | 핀을 `1.26.4`로 되돌리고 이미지 재빌드 |
| Dashboard에서 Zone 저장은 성공했는데 추론에 반영되지 않음 | `--zones`와 `KIDCAFE_ZONES_PATH`가 다른 파일 | 두 경로를 같은 파일로 맞추고 Vision AI 재시작 |
| Zone 저장이 `409` | 다른 클라이언트가 먼저 저장해 version이 바뀜 | 재조회 후 편집 내용을 다시 적용 |
| Zone 저장이 `422` | polygon·schema 오류 | 좌표 범위와 필수 필드 확인 |
| `GET /zones`가 `500` | runtime 파일 누락·파싱 실패 | 파일 존재와 JSON 유효성 확인. **빈 배열로 대체하지 않는다** |
| RTSP 연결은 되는데 프레임이 안 옴 | UDP 차단·방화벽 | TCP 강제 옵션이 적용됐는지 확인 (5절) |
| RTSP가 3초 뒤 stale로 표시됨 | 네트워크 지연 또는 스트림 중단 | 카메라·네트워크 확인. 상수는 바꾸지 않는다 |
| RTSP가 연속 읽기 실패로 종료 | 30회 연속 실패 | 카메라 재부팅 또는 URL·인증정보 확인 |
| Event 시각이 실제보다 느림 | source 기준이 아니라 처리 기준으로 계산 | `capture_sequence` 전달 경로 확인 (5절) |
| API가 죽어도 추론은 계속됨 | 설계된 동작 | 실패 Event는 `outputs/api_failed_events.jsonl`에 보존된다 |

API 장애 시 Mock 데이터로 자동 전환하지 않는다(계획서 4절). Dashboard는
연결 끊김·복구·stale을 그대로 표시한다.

---

## 11. 동결 이후 변경 절차

8월 20일 이후에는 P0 결함 수정만 허용한다(계획서 3절).

1. 무엇이 깨졌는지와 왜 P0인지 먼저 적는다.
2. 이 문서의 해당 값을 고치고 `tests/test_phase4_backend_freeze.py`를 함께
   갱신한다. 테스트가 문서와 코드를 대조하므로 한쪽만 고치면 CI가 걸린다.
3. 변경 사유를 이 절 아래에 한 줄로 남긴다.

### 변경 이력

- 2026-08-19: 최초 동결 (`a3b693c` 기준)
