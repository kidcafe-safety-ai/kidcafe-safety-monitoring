# Backend 최종 기술 문서 (Final Phase)

> **담당 영역**: B — Backend·Database·Docker
>
> **기준**: `main` @ `9869277e` (애플리케이션 `v0.3.0`)
>
> **최종 수정**: 2026-10-15
>
> **관련 문서**: [`api_contract.md`](api_contract.md) (요청·응답 상세 계약),
> [`interfaces.md`](interfaces.md), [`phase4_backend_freeze.md`](phase4_backend_freeze.md),
> [`docker_phase_2_5.md`](docker_phase_2_5.md), [`final_validation.md`](final_validation.md)

이 문서는 Backend를 처음 받는 사람이 실행·점검·운영할 수 있도록 최종 상태를
한곳에 모은 것이다. 필드별 schema와 응답 예시는 `api_contract.md`가 기준이며 여기서는
반복하지 않는다.

---

## 1. 구성

```text
Vision AI (host, python -m src.main)
  ├─ POST /events          ─┐
  ├─ PUT  /status/current   ├─▶ FastAPI (src/api, Docker kidcafe-api:8000) ─▶ SQLite (outputs/kidcafe_events.db)
  └─ PUT  /live/frame      ─┘                    │                         └▶ Zone runtime (outputs/zones_runtime.json)
                                                 ▼
                              React Dashboard (frontend, Docker :3000) — polling
```

| 파일 | 역할 |
|---|---|
| `src/api/main.py` | FastAPI app, CORS, 오류 handler, router 등록 |
| `src/api/routers/` | `health`, `events`, `status`, `live`, `summary`, `zones` |
| `src/api/schemas.py` | Pydantic 요청·응답 schema와 입력 검증 |
| `src/api/database.py` | SQLite 경로, connection, schema·migration |
| `src/api/repositories.py` | Event·CurrentStatus·Summary SQL |
| `src/api/live_frame_store.py` | 최신 JPEG 1장 in-memory 저장 |
| `src/api/zone_store.py` | Zone runtime 파일 읽기·저장 (version = SHA-256) |
| `scripts/init_zone_runtime.py` | Zone runtime 파일 최초 생성 |
| `scripts/api_smoke_test.py` | 실행 중 API 점검 |
| `scripts/sqlite_db.py` | DB 백업·복원·초기화 |

저장소 구분은 별도 `src/storage/` 없이 `src/api/database.py`·`repositories.py`가 맡는다.

---

## 2. API Endpoint 목록

| Method | Path | 호출 주체 | 설명 | 주요 오류 |
|---|---|---|---|---|
| GET | `/health` | Docker healthcheck, smoke test | 서비스 상태 | — |
| POST | `/events` | Vision AI | Event 저장 | `409` 중복 `event_id`, `422` 검증 |
| GET | `/events` | Dashboard Event History·Report | 목록, `limit`·`offset`·`event_type`·`zone_id`·`created_from`·`created_to` | `422` |
| GET | `/events/recent` | Dashboard Monitoring | 최근 Event, `limit`·`minutes` | `422` |
| GET | `/summary` | Dashboard KPI | 전체·오늘(Asia/Seoul)·최근 10분 집계 | — |
| PUT | `/status/current` | Vision AI | source별 현재 상태 덮어쓰기 | `422` |
| GET | `/status/current` | Dashboard | 가장 최근 source 상태 | — |
| PUT | `/live/frame` | Vision AI | 최신 JPEG 업로드 | `413`, `415`, `422` |
| GET | `/live/frame` | Dashboard Live View | 최신 JPEG, 없거나 3초 이상 미갱신이면 `204` | — |
| GET | `/zones` | Dashboard Zone Settings | Zone 설정 + version | `500` 파일 누락·손상 |
| PUT | `/zones` | Dashboard Zone Settings | 전체 Zone 교체 저장 | `409` version 충돌, `422`, `500` |

응답 형식:

- 성공: `{"status": "success", "data": ..., "message": null}`
- 명시적 오류(`409`, `500`): `{"status": "error", "data": null, "message": "..."}`
- 검증 오류(`422`): FastAPI 기본 `{"detail": [...]}`
- `GET /live/frame`: `200 image/jpeg` 또는 `204` (JSON wrapper 예외)

Report는 별도 API 없이 `GET /events?created_from=...&created_to=...`로 기간을 조회한다.
두 값 모두 timezone 포함 RFC 3339이고 `created_from` 이상, `created_to` 미만이다.
기준 시각은 서버 저장 시각 `created_at`(UTC)이며 영상 상대 시각 `timestamp`가 아니다.

---

## 3. 데이터 계약 요약

### Event

- `events` 테이블에 누적 저장, `event_id` UNIQUE.
- 같은 `event_id` 재전송은 `409`이며 Vision AI client는 이를 성공으로 처리한다
  (재시작·retry로 중복 저장되지 않음).
- `event_confidence`(REAL)와 `cause`(`cause_json` TEXT)는 nullable이다. `cause`는
  모든 필드가 있어야 하며 근거가 없으면 `null`로 저장·조회된다.
- Final Phase 입력 검증: `event_id`·`zone_id`·`video_source` 빈 문자열 불가,
  `frame_number >= 0`, 모든 number에 `NaN`·`Infinity` 불가 → `422`.

### CurrentStatus

- `current_status` 테이블에 `source`별 1 row, `PUT`마다 덮어쓴다.
- `updated_at`은 `YYYY-MM-DD(T| )HH:MM[:SS[.fff|.ffffff]](Z|±HH:MM)` 형식이어야
  하고(아니면 `422`), 받은 문자열 그대로 저장한다. SQLite `julianday()`가 해석할 수
  있는 형식만 받으므로 정렬에서 NULL이 되는 값은 저장되지 않는다.
  생략하면 서버 시각을 넣는다.
- `GET`은 `julianday(updated_at)`가 가장 늦은 row를 반환한다. 영상 전환으로 source가
  바뀌어도 새 source가 반환되고, 실행 종료 시 0명 상태를 보내면 그 상태가 반환된다.
- 저장된 상태가 없으면 `source="unknown"`, 0명, `updated_at=null`.
- `risk_level`은 Vision AI가 정한다(사람이 있는 `danger`·`restricted` Zone만 `HIGH`).
  Backend는 다시 계산하지 않는다. 상세: `api_contract.md` Current Status Schema.

### LiveFrame

- DB·파일에 저장하지 않는 process 메모리 1장. API 재시작 시 사라진다(`204`).
- 서버 수신 후 3초가 지나면 `204`. Vision AI가 멈추면 3초 뒤 Live View가 비워진다.
- `image/jpeg`, 1 MiB 이하, JPEG 시작·끝 marker 검사, `captured_at`은 timezone 포함.
- 해상도는 Vision AI가 최대 640×480·원본 비율로 맞춘다. Backend는 해상도를 검사하지 않는다.

### Zone Settings

- runtime 파일(`outputs/zones_runtime.json`)이 기준이며 seed(`data/zones/sample.json`)는
  읽기 전용이다. API는 runtime 파일을 자동 생성하지 않는다.
- `version`은 파일 bytes의 SHA-256. `PUT`은 `expected_version`이 다르면 `409`.
- 같은 파일을 Vision AI가 `--zones`로 읽는다.

---

## 4. SQLite 저장 구조

| 테이블 | 키 | 비고 |
|---|---|---|
| `events` | `id` AUTOINCREMENT, `event_id` UNIQUE | index: `event_type`, `zone_id`, `id` |
| `current_status` | `source` PRIMARY KEY | index: `updated_at` |

- 경로: `KIDCAFE_DB_PATH`, 없으면 `outputs/kidcafe_events.db`.
- API 기동 시 `init_db()`가 테이블·index를 만들고 Phase 3 컬럼(`event_confidence`,
  `cause_json`)을 idempotent하게 추가한다. 기존 DB를 그대로 둔 채 재실행해도 된다.
- connection을 열 때 DB 파일이 없으면 schema를 다시 만든다. 실행 중 파일을 지워도
  다음 요청부터 빈 DB로 동작한다.
- 요청마다 connection을 새로 열며 SQLite 기본 잠금(5초 busy timeout)을 쓴다.

---

## 5. 환경변수

| 이름 | 사용처 | 기본값 | Docker Compose 값 |
|---|---|---|---|
| `KIDCAFE_DB_PATH` | API, `scripts/sqlite_db.py` | `outputs/kidcafe_events.db` | `/app/outputs/kidcafe_events.db` |
| `KIDCAFE_ZONES_PATH` | API, `scripts/init_zone_runtime.py` | `outputs/zones_runtime.json` | `/app/outputs/zones_runtime.json` |
| `VITE_API_MODE` | Frontend | — | `api` |
| `VITE_API_BASE_URL` | Frontend | — | `http://localhost:8000` |
| `KIDCAFE_RTSP_USERNAME`, `KIDCAFE_RTSP_PASSWORD` | Vision AI RTSP | 빈 값 | 사용 안 함 |

`.env.example`을 `.env`로 복사해 쓴다. `.env`는 Git에 넣지 않는다. host에서 스크립트를
실행할 때는 `KIDCAFE_*`를 지정하지 않으면 `./outputs/`를 쓰며, Compose volume
(`./outputs:/app/outputs`) 덕분에 컨테이너와 같은 파일이 된다.

---

## 6. Docker Compose 실행

```bash
cp .env.example .env                    # 최초 1회
python scripts/init_zone_runtime.py     # 최초 1회, 이미 있으면 덮어쓰지 않음
docker compose up --build -d
python scripts/api_smoke_test.py        # 10초 안팎 후 실행
```

| 서비스 | 주소 | 비고 |
|---|---|---|
| `kidcafe-api` | http://localhost:8000 | healthcheck `GET /health` 10초 간격, `restart: unless-stopped` |
| `frontend` | http://localhost:3000 | API가 healthy가 된 뒤 시작, `restart: unless-stopped` |

- `docker compose down` 후 다시 `up` 해도 `./outputs`의 DB·Zone 파일이 유지된다.
- API 프로세스가 비정상 종료되면 Docker가 자동 재시작한다. `docker compose stop`처럼
  사용자가 멈춘 경우는 재시작하지 않는다.
- Frontend 컨테이너는 Vite dev server다. 시연·통합 검증용이며 운영 배포 구성이 아니다.

---

## 7. API Smoke Test

```bash
python scripts/api_smoke_test.py                              # 읽기 전용
python scripts/api_smoke_test.py --base-url http://host:8000
python scripts/api_smoke_test.py --write                      # POST 경로까지
```

| 항목 | 통과 기준 |
|---|---|
| `GET /health`, `/events`, `/events/recent`, `/summary`, `/status/current`, `/zones` | `200`, success envelope, 필수 필드 |
| `GET /live/frame` | `204` 또는 `200 image/jpeg` |
| `--write`: `POST /events` → 같은 요청 재전송 → 빈 body | `201` → `409` → `422` |

표준 라이브러리만 쓰므로 Vision AI 의존성이 필요 없다. 모두 통과하면 종료 코드 `0`,
하나라도 실패하면 `1`이다. `--write`는 `video_source="api-smoke-test"` Event를 실제
DB에 1건 남기므로 시연·제출용 DB에서는 쓰지 않는다. `GET /zones`가 실패하면 대부분
`init_zone_runtime.py`를 건너뛴 경우다.

---

## 8. DB 초기화·백업

```bash
python scripts/sqlite_db.py backup                    # outputs/backups/kidcafe_events_YYYYmmdd_HHMMSS.db
python scripts/sqlite_db.py restore <백업 파일> --yes  # 현재 DB를 백업한 뒤 덮어쓰기
python scripts/sqlite_db.py reset --yes               # 현재 DB를 백업한 뒤 비우기
```

- `backup`은 SQLite online backup API를 쓴다. API가 실행 중이어도 된다.
- `restore`·`reset`은 항상 현재 DB를 먼저 백업하고, `--yes`가 없으면 실행하지 않는다.
- `reset`은 `events`·`current_status`를 비우고 Event `id`를 1부터 다시 시작한다.
- API를 재시작할 필요는 없다. 다만 Vision AI 전송은 멈춘 상태에서 실행한다.
- `outputs/backups/`는 Git에서 제외된다. 제출용 백업은 저장소와 별도로 보관한다.
- Zone 설정 초기화는 `outputs/zones_runtime.json`을 다른 이름으로 옮긴 뒤
  `python scripts/init_zone_runtime.py`를 다시 실행한다.

---

## 9. API 장애·복구 동작

| 상황 | Backend 동작 | Vision AI·Dashboard 영향 |
|---|---|---|
| API 중단 | — | Vision AI 추론은 계속된다. Event는 retry 1회 후 `outputs/api_failed_events.jsonl`에 기록, CurrentStatus·LiveFrame은 버린다. Dashboard는 오류·stale 상태 표시 |
| API 재시작 | Event·CurrentStatus·Zone 유지, LiveFrame 비움 | 다음 전송부터 자동 재개. 재시작 직후 Live View는 새 frame 전까지 `204` |
| 같은 Event 재전송 | `409` | client가 성공으로 처리, 중복 저장 없음 |
| 잘못된 Event(`NaN` 등) | `422`, 저장하지 않음 | Vision AI가 실패 JSONL에 기록. 다른 Event 조회에 영향 없음 |
| DB 파일 삭제·`outputs/` 삭제 | 다음 요청에서 빈 schema 재생성 | 이전 데이터는 사라진다. 필요하면 `restore` |
| Zone runtime 파일 누락·손상 | `GET /zones`·`PUT /zones` `500` | Zone Settings 편집 비활성화. Mock·빈 Zone으로 대체하지 않음 |
| 컨테이너 프로세스 비정상 종료 | Docker 자동 재시작 | 위 "API 재시작"과 같음 |

`api_failed_events.jsonl`의 Event는 자동 재전송하지 않는다. 필요한 경우 수동으로
확인한다.

---

## 10. 검증 결과 (2026-10-12)

| 항목 | 결과 |
|---|---|
| `flake8 src tests` | 통과 |
| `pytest -q` | 전체 통과 (Backend 신규: `test_api_final_stability.py` 47개, `test_backend_ops_scripts.py` 13개) |
| 깨끗한 디렉터리에서 `init_zone_runtime` → `docker compose up --build -d` | API healthy, Frontend `200` |
| `api_smoke_test.py --write` | 10/10 |
| `docker compose restart kidcafe-api`, `down` → `up` | Event 유지 |
| API 실행 중 `sqlite_db.py backup` → `reset --yes` | 백업 생성, API 즉시 빈 DB 반영 |
| API 실행 중 DB 파일 삭제 | smoke test 10/10 |
| `NaN` bbox `POST /events` | `422`, `GET /events` `200` |
| API 프로세스 강제 종료 | Docker 자동 재시작, `/health` `200` |

---

## 11. Backend 운영 한계

- 인증·인가가 없다. 로컬·시연 네트워크에서만 쓴다.
- CORS는 `localhost`·`127.0.0.1`의 `3000`·`5173`만 허용한다.
- 단일 API process 기준이다. Zone 저장 lock과 LiveFrame은 process 내부에만 있어
  worker를 여러 개 띄우면 맞지 않는다.
- SQLite 단일 파일이다. 동시 쓰기가 많아지면 잠금 대기가 생긴다. 장시간 운영·다중
  카메라는 검증하지 않았다 (P2).
- `current_status`는 source row를 지우지 않는다. 오래된 source row는 남지만 응답에는
  최신 source만 나온다.
- `GET /summary`의 `avg_dwell_seconds`는 항상 `0.0`이다.
- 실시간 전송은 polling 기반이며 WebSocket·WebRTC는 없다 (P2).
- 실패 Event JSONL의 자동 재전송은 없다.
