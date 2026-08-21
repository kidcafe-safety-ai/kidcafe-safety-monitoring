# Architecture Decision Records

## ADR-001: Tracking 라이브러리로 Ultralytics built-in 채택

**Date**: 2026-05-15
**Status**: Accepted

### Context
다중 객체 추적을 위해 ByteTrack 사용 결정.

### Options Considered

**Option 1: boxmot (별도 라이브러리)**
-  19.x / 10.x 버전 API 구조 변경
-  `create_tracker()` 필수 인자 요구
-  ByteTrack 직접 import 불가
-  버전별 API 불일치

**Option 2: Ultralytics built-in tracking**  채택
-  `model.track()` 한 줄로 detection + tracking 통합
-  별도 라이브러리 없이 안정 동작
-  ByteTrack/BotSort 둘 다 지원

### Decision
MVP 단계에서 Ultralytics built-in tracking 사용.

### Consequences
- 환경 설정 부담 감소
- `src/detection/yolo_detector.py`는 제거 (ByteTracker가 detection까지 통합)
- 트래커 세부 튜닝 어려울 경우 ADR-004로 재검토

### References
- 검증 영상: 초기 검증 영상 (파일 영상 기반 MVP 검증용)
- 검증 결과: bbox + track_id 정상 출력, 간헐적 ID 변경은 MVP 범위 허용

---

## ADR-002: PyTorch 2.5.1 버전 고정

**Date**: 2026-05-15
**Status**: Accepted

### Context
YOLO 모델 로딩 시 PyTorch 2.6+에서 `weights_only` 관련 `UnpicklingError` 발생.

### Decision
- `torch==2.5.1`
- `torchvision==0.20.1`
- `torchaudio==2.5.1`

### Consequences
-  YOLO 모델 안정 로딩
-  추후 PyTorch 2.6+ 호환성 재검토 시 ADR-005로 기록

---

## ADR-003: shapely covers() 사용 (contains 대신)

**Date**: 2026-05-15
**Status**: Accepted

### Context
Track의 발 위치가 Zone polygon 안에 있는지 판정.

### Decision
`polygon.covers(point)` 사용.

### Reason
- `contains()`는 경계선 위 점을 False로 처리
- 픽셀 → 정규화 변환의 부동소수점 오차로 경계에 걸리는 경우 흔함
- `covers()`는 경계 위도 True

### Consequences
-  Zone 경계에서 누락 방지

---

## ADR-004: EventManager 시그니처 변경 (Breaking Change)

**Date**: 2026-05-17
**Status**: Accepted

### Context
DWELL 이벤트 구현 시 zone별 dwell_threshold_sec와 FPS 정보가 필요해졌다.

기존 EventManager() 구조에서는:

* zone별 체류 임계시간 접근 불가
* 영상 시간 기준 timestamp 계산 불가

### Decision

EventManager.__init__(zones, fps) 형태로 시그니처 변경.

### Migration

# Before
event_manager = EventManager()
# After
event_manager = EventManager(zones=zones, fps=fps)

### Consequences
* DWELL 이벤트 구현 가능
* zone별 체류 규칙 적용 가능
* 영상 시간 기반 timestamp 계산 가능
* 기존 코드와 호환되지 않는 Breaking Change 발생

---

## ADR-005: timestamp를 영상 시간 기준으로 통일

**Date**: 2026-05-17
**Status**: Accepted

### Context
기존 datetime.now() 기반 시스템 시간은 영상 시점과 동기화되지 않았다.

예:
* 영상 시작 후 8초 시점 이벤트라도
* 실제 저장 시간은 현재 PC 시간으로 기록됨

이 경우:
* 영상 ↔ 이벤트 동기화 어려움
* 타임라인 차트 구성 어려움
* Streamlit 모니터링 페이지에서 특정 이벤트 시점 탐색 어려움

### Decision
timestamp를 frame_number / fps 기반의 영상 상대 시간으로 통일.
형식:
HH:MM:SS.mmm

예:
00:00:08.500

### Consequences
* 영상 시점 ↔ 이벤트 완전 동기화 가능
* B의 통계 차트 X축 시간 데이터 활용 가능
* C의 모니터링 페이지에서 이벤트 탐색 가능
* 실제 처리 시각이 필요하면 processed_at 별도 필드 필요 (Phase 2)

### Update

2026-06-29: 이벤트의 `timestamp`는 영상 상대 시각으로 유지한다. Dashboard의 오늘/최근 집계는 실제 저장 시각인 `events.created_at`을 사용한다. 오늘 집계는 Asia/Seoul 기준이며 최근 집계는 Backend UTC 현재 시각 기준 10분 범위다.

---

## ADR-006: 결과 영상 코덱으로 mp4v 채택
**Date**: 2026-05-17
**Status**: Accepted

### Context
OpenCV VideoWriter를 사용해 결과 영상(result.mp4)을 저장할 때 코덱 선택 필요.

후보:
* mp4v
* avc1 / h264
* MJPG

### Decision
MVP 단계에서는 mp4v 코덱 사용.

### Reason
* macOS / Linux 환경 호환성 우수
* OpenCV 기본 설치만으로 동작
* FFmpeg 별도 설치 불필요
* 팀원 로컬 환경에서 바로 실행 가능
* 시연용 품질로 충분

### Consequences
* 환경 의존성 최소화
* 결과 영상 즉시 생성 가능
* h264 대비 압축률 낮음
* 장기 저장/배포용은 추후 재검토 필요

---

## ADR-007: 1차 MVP 탐지 모델은 YOLOv8n + ByteTrack 조합 사용
**Date**: 2026-05-17
**Status**: Accepted

### Context
현재 프로젝트의 1차 목표는:
* 사람 탐지
* 위험구역 판정
* ENTER/DWELL/EXIT 이벤트 생성
* 결과 영상 시각화

실제 테스트 결과:
* CCTV처럼 멀리 촬영된 영상에서는 사람 bbox가 일부 프레임에서 끊김
* 작은 객체 탐지 성능 제한 존재
* track_id가 자주 변경되는 현상 발생

### Decision
1차 MVP에서는:
* YOLOv8n
* Ultralytics built-in ByteTrack

### Reason
* 구현 속도가 빠름
* 로컬 환경에서도 충분히 실행 가능
* Ultralytics track() API 활용 가능
* MVP 수준의 파이프라인 검증에는 충분한 성능
* 팀 개발 속도와 안정성을 우선 고려

### Limitations
* 원거리 CCTV 영상에서 작은 사람 탐지 약함
* bbox 깜빡임 존재
* 가려짐/재등장 시 ID 변경 발생
* ByteTrack만으로 장기 ID 유지 어려움
* ReID 기능 부재

### Future Work
* YOLOv8s / YOLOv8m 이상 모델 검토
* ReID(OSNet / StrongSORT) 적용
* 작은 객체 탐지 개선
* 장기 track_id 유지 안정화
* 실제 키즈카페 CCTV 데이터 기반

### Update
* 2026-05-30: Phase 1.5 모델 benchmark에서 YOLO26n을 Phase 2 실시간 입력 1차 기준 모델 후보로 선정.
* 상세 근거: `docs/model_benchmark.md`

---

## ADR-008: Dashboard API 모듈 분리 및 요약 출력 추가

**Date**: 2026-05-18  
**Status**: Accepted

### Context

대시보드에서 이벤트 데이터를 활용하려면 `outputs/events.jsonl`을 그대로 읽는 것만으로는 부족하다.

필요한 기능은 다음과 같다.

* 이벤트 로그 CSV 변환
* KPI 요약 JSON 생성
* 구역별 / 타입별 / 시간대별 이벤트 집계
* 체류 시간 분석
* 개별 track_id 기준 활동 리포트
* Streamlit에서 바로 사용할 수 있는 차트 생성

처음에는 `event_aggregator.py`와 `charts.py`에 모든 기능을 모을 수 있지만, 파일이 길어지고 책임이 많아져 유지보수가 어려워질 수 있다.

### Decision

대시보드 분석 기능을 역할별 모듈로 분리한다.

```text
src/common/event_io.py              # 이벤트 파일 입출력
src/common/event_time.py            # 영상 시간 처리
src/common/event_counter.py         # 이벤트 집계
src/common/dwell_analyzer.py        # 체류 시간 분석
src/common/track_report.py          # track_id 기준 리포트
src/common/insight_generator.py     # 룰 기반 인사이트 생성
src/common/event_aggregator.py      # 대시보드용 통합 API
src/visualization/event_charts.py   # 이벤트/통계 차트
src/visualization/track_charts.py   # track_id 기준 차트
src/visualization/charts.py         # 차트 통합 API
```

---

## ADR-009: 파일 영상 기반 MVP 1차 종료 및 Phase 2 분리

**Date**: 2026-05-27
**Status**: Accepted

### Context

MVP 1차 목표인 파일 영상 기반 end-to-end 검증이 완료되었다.

파이프라인 전체가 동작하고 Streamlit 검증 대시보드까지 구현되었으나, 실시간 입력·운영형 UI·서버 인프라는 검증 범위 밖이었다.

### Decision

- MVP 1차는 파일 영상 기반 end-to-end 검증 버전으로 종료한다.
- Streamlit은 운영 UI가 아니라 검증용 임시 대시보드로 둔다.
- React, FastAPI, IP 카메라, ReID, 낙상 감지는 Phase 2 이후로 분리한다.
- MVP baseline을 `v0.1.0-mvp` 태그로 고정한다.

### Consequences

- Phase 2 개발 범위와 MVP 완료 범위가 명확하게 분리된다.
- Streamlit 코드는 Phase 2에서 React로 전환 시 삭제 또는 별도 브랜치로 이동한다.
- `v0.1.0-mvp` 태그로 재현 가능한 기준선을 유지한다.

### Update

- 2026-06-01: Phase 1.5에서 Streamlit app/pages는 삭제되고 React Dashboard로 전환됨. 자세한 내용은 ADR-010 참고.

---

## ADR-010: Streamlit 검증 대시보드 종료 및 React Dashboard 전환

**Date**: 2026-06-01
**Status**: Accepted

### Context

Phase 1.5에서 React mock Dashboard 2페이지가 완성되었다.

### Decision

Streamlit은 MVP 검증용으로 종료한다. Phase 1.5 기준 운영 UI는 `frontend/` React Dashboard다.

### Consequences

- Streamlit app/pages (`app.py`, `pages/`)는 Phase 1.5에서 삭제되었다.
- `src/visualization/` 내 결과 영상/차트 유틸(`video_overlay.py`, `charts.py` 등)은 legacy 모듈로 유지한다.
- 새로운 UI 기능은 React (`frontend/`)에 추가한다.

---

## ADR-011: Phase 2 실시간 갱신 방식은 WebSocket이 아닌 polling 우선

**Date**: 2026-06-01
**Status**: Accepted

### Context

Phase 2에서 React Dashboard가 실시간 이벤트를 표시해야 한다. WebSocket과 polling 중 선택이 필요했다.

### Decision

Phase 2에서는 polling으로 실시간성을 확보한다. WebSocket은 Phase 2.5 이후 검토한다.

### Reason

- WebSocket 구현보다 실시간 입력 연결 자체가 Phase 2의 핵심이다.
- polling 기반으로도 2-3초 주기로 충분한 실시간성 확보가 가능하다.
- 개발 복잡도를 낮추고 Phase 2 일정 리스크를 줄인다.

### Update

2026-06-29: Phase 2.5에서도 REST polling을 유지했다. `/status/current` 2초, `/events/recent` 3초, `/summary` 10초 주기로 안정적으로 동작함을 확인했다. WebSocket은 실시간 push 필요성이 명확해진 이후 재검토한다.

---

## ADR-012: Event 로그와 Current Status 데이터 분리

**Date**: 2026-06-01
**Status**: Accepted

### Context

React Dashboard에서 "현재 감지 인원"과 "위험구역 현재 점유"를 표시해야 한다. Event 누적 로그만으로는 이를 정확히 계산하기 어렵다.

### Decision

Event는 발생 기록으로 누적 저장(`POST /events`)하고, Current Status는 현재 상태로 최신 값만 갱신(`PUT /status/current`)하는 구조로 분리한다.

### Consequences

- A는 `PUT /status/current`로 현재 상태를 전송한다.
- B는 최신 상태를 저장/조회한다.
- C는 현재 KPI를 `/status/current` 기준으로 표시한다.
- 상세 계약: `interfaces.md` Section 7-A

---

## ADR-013: Phase 2는 웹캠 기반 end-to-end를 우선하고 RTSP는 fallback 가능

**Date**: 2026-06-01
**Status**: Accepted

### Context

Phase 2에서 웹캠과 RTSP 입력을 모두 연결해야 하나, 시험 기간(6/17-6/23)으로 실질 개발 기간이 제한적이다.

### Decision

웹캠 기반 end-to-end를 먼저 완성한다. RTSP는 테스트 완료 또는 실패 원인 문서화로 대체 가능하다.

### Reason

- 웹캠은 환경 의존성이 낮아 빠르게 검증 가능하다.
- RTSP는 네트워크, 코덱, 지연 문제 등 예측 불가한 오류가 발생할 수 있다.

---

## ADR-014: Phase 2.5 제한적 Docker 도입

**Date**: 2026-06-27
**Status**: Accepted

### Context

Phase 2.5에서 팀원 간 실행 환경 차이(macOS / Windows)로 FastAPI·React 실행 방법이 달라졌다. 중간평가 전에 시연 환경을 재현 가능하게 통일할 필요가 있었다.

### Decision

FastAPI, React Dashboard, SQLite volume을 Docker Compose로 묶어 실행 환경을 통일한다. Vision AI 추론 환경은 Docker에 포함하지 않는다.

포함:
- FastAPI (`Dockerfile.api`, port 8000)
- React Dashboard (`frontend/Dockerfile`, port 3000, Vite dev server)
- SQLite bind mount (`./outputs:/app/outputs`)

제외:
- Vision AI 웹캠 파이프라인
- YOLO / torch / ultralytics / opencv 추론 환경
- GPU / MPS 설정
- USB 카메라 passthrough
- RTSP 운영 안정화

### Reason

- 운영 배포가 아닌 개발·시연 환경 통일이 목적이다.
- Vision AI는 GPU/MPS와 카메라 장치 의존성이 있어 Docker 격리 이점보다 복잡도가 높다.
- FastAPI와 React는 의존성이 단순하고 컨테이너화 이점이 명확하다.

### Consequences

- Vision AI는 로컬에서 실행하고 `--api-url http://localhost:8000`으로 Docker FastAPI에 연동한다.
- Docker frontend는 Vite dev server 기반이며 운영 배포 구성(정적 파일 서버, reverse proxy, TLS)은 별도 검토가 필요하다.
- macOS(내장 웹캠)와 Windows(USB C920) 환경에서 Docker Compose E2E 검증 완료.

---

## ADR-015: Live View latest-frame polling

**Date**: 2026-07-06
**Status**: Accepted

### Context

Phase 3에서 Dashboard에 실시간 영상 영역을 추가해야 한다. WebSocket·MJPEG 방식과 latest-frame polling 방식 중 선택이 필요했다.

### Decision

`PUT /live/frame` + `GET /live/frame` 기반 latest-frame polling 방식으로 구현한다. React는 500-1000ms 간격으로 polling한다.

### Alternatives

- **WebSocket**: 연결 유지·재연결 처리 복잡도가 높고 FastAPI 단일 worker 환경에서 추가 설정 필요
- **MJPEG**: 브라우저 호환성 및 FastAPI에서의 스트리밍 처리 복잡도 높음

### Reason

- REST polling 구조를 Phase 3 내에서 유지한다는 핵심 원칙에 부합
- FastAPI 단일 worker 기준에서 구현이 단순
- 1-2 FPS 업로드로 키즈카페 안전 모니터링 용도에 충분
- 3초 미갱신 시 `204 No Content`로 stale 상태를 명확히 처리

### Consequences

- 최신 JPEG 1장만 Process Memory에 보관, DB 영속 저장 없음
- 파이프라인 중단 시 React placeholder 표시
- WebSocket·MJPEG는 Phase 4 이후 필요성 기반 재검토

---

## ADR-016: FALL_SUSPECT.cause 기반 외부 접촉 원인 후보 기록

**Date**: 2026-07-06
**Status**: Accepted

### Context

Phase 3에서 낙상 감지 PoC와 함께 낙상 직전 외부 접촉 원인 후보 추정 기능을 구현한다. 독립 `COLLISION_SUSPECT` 이벤트와 `FALL_SUSPECT.cause` 방식 중 선택이 필요했다.

### Decision

독립 `COLLISION_SUSPECT` 이벤트를 생성하지 않는다. 낙상 확정(`FALL_CONFIRMED`) 시 낙상 시작 직전 0.5-1초의 Track 기록을 소급 조회하여, 근접 근거가 충분한 경우 `FALL_SUSPECT.cause`에 원인 후보 Track 정보를 기록한다. 근거 부족 시 `cause=null`을 유지한다.

### Implementation Status

`FALL_SUSPECT` 감지와 `cause=null` 전송 경로에 이어
`src/safety/fall_cause_attributor.py`(`FallCauseAttributor`)로 non-null
`cause` 생성도 구현했다. `FallDetector._confirm_fall()`이 confirm 시점에
`FALLING_CANDIDATE` 진입 시각(onset proxy)을 기준으로
`FallCauseAttributor.attribute()`를 호출하고, 근거가 충분하면
`EventCause(type="NEARBY_TRACK", ...)`를, 부족하면 `cause=None`을 그대로
반환한다.

`FallCauseAttributor`는 `FallDetector`가 낙상 판정에 쓰는
`MultiTrackHistory`와 완전히 분리된 자체 이력을 갖는다 — 두 컴포넌트를
합치면 attribution에 필요한 더 긴 lookback을 위해 낙상 판정용 이력 window를
늘려야 하는데, 그러면 이미 동결한 속도/변화율 계산과 평가 수치가 조용히
바뀔 위험이 있었다. 이 분리 결정으로
그 위험을 피했다(자세한 근거는 `src/safety/fall_cause_attributor.py` 모듈
docstring 참고).

Candidate Handoff로 ReID 없이 승계된 낙상은 `FALLING_CANDIDATE` 진입
당시의 track_id와 confirm 시점의 track_id가 다를 수 있다 —
`FallCauseAttributor`는 `FallDetector`와 완전히 독립된 자체 이력을 Track별로
관리하므로, confirm 시 최종 track_id만 넘기면 handoff 이전 시각(=lookback
구간이 걸칠 수 있는 구간)의 victim 샘플을 찾지 못해 근거가 있어도 잘못
`cause=None`이 될 수 있다. `FallDetector._confirm_fall()`이 승계 이전
alias track_id 전체(`_TrackState.origin_track_ids`)를 `attribute()`의
`victim_track_id_aliases`로 함께 넘겨, 그 track_id들의 이력도 victim
샘플에 병합하고 후보 목록에서는 제외하도록 확장했다(자세한 근거는
`src/safety/fall_cause_attributor.py`의 `attribute()` docstring 참고).

Attribution은 `FALL_SUSPECT` 감지 임계값·모델·기본 비활성 정책을 바꾸지
않고, 이미 확정된 낙상에 사후적으로 원인 후보만
덧붙이는 순수 추가 기능이다. 정량 정확도 검증은 접촉 원인 정답 라벨이 있는
데이터가 없어 수행하지 않았다. 합성 multi-track 테스트로 생성·제외 계약을
검증했다. 구현 당시 MPFDD 공개 샘플 28개의 파일명·설명을 검토해 다인 근접
hard-negative 후보 가능성도 확인했지만, 원인 Track 라벨과 명확한 라이선스가
없어 실제 실행·학습·평가에는 사용하지 않았다. 이 데이터는 현재 통합 및 후속
평가 계획에서 미채택하며, 실제 접촉 유발 영상 기반 정확도 평가는 Phase 4로
이관한다.

### Alternatives

- **독립 COLLISION_SUSPECT**: 충돌 자체를 실시간 감지하는 별도 알고리즘 필요. 현재 데이터셋(CAUCAFall)이 낙상 데이터이므로 충돌 감지 검증 불가. 오탐률 제어 어려움.

### Reason

- 키즈카페에서는 놀이 과정의 근접과 가벼운 접촉이 빈번할 수 있어, 접촉 후보만으로 알림을 생성하면 운영자에게 과도한 알림이 발생할 수 있음
- 운영상 즉각 대응 가치가 높은 상황은 외부 접촉 직후 낙상이 동반된 경우이므로, 낙상 확정 후 직전 Track을 원인 후보로 기록하는 구조가 실용적
- 낙상 확인 후 직전 Track을 소급 조회하여 시간적 선후 관계를 확인하는 구조가 적절함
- 추가 모델 없이 휴리스틱으로 구현 가능
- 영상만으로 실제 충돌 인과관계를 확정하지 않고 `외부 접촉 의심`으로 제한해 표시

### Consequences

- `FALL_SUSPECT` 없이 충돌만 발생한 경우는 Phase 3에서 감지 불가
- 독립 `COLLISION_SUSPECT`는 Phase 4 이후 데이터 확보 후 재검토
- Dashboard 표기: `외부 접촉 의심 · Track #N`

---

## ADR-017: AsyncEventDispatcher 기반 비차단 전송

**Date**: 2026-07-06
**Status**: Accepted

### Context

Phase 2.5에서 `EventApiClient`의 동기 HTTP 전송이 API 장애 시 Vision AI 추론 루프 FPS를 저하시키는 문제가 확인됐다. API 장애 중에도 파이프라인이 정상 동작해야 한다.

### Decision

기존 `EventApiClient`는 동기 HTTP 전송 계층으로 유지하고, 신규 `AsyncEventDispatcher`가 이를 감싸는 wrapper 구조로 구현한다. `src/main.py`는 `EventApiClient`를 직접 호출하지 않고 Dispatcher에 등록한다.

```text
src/main.py
→ AsyncEventDispatcher.enqueue_event()
→ AsyncEventDispatcher.update_current_status()
→ AsyncEventDispatcher.update_live_frame()
→ Event / Status / Live Frame worker
→ EventApiClient
→ FastAPI
```

### Alternatives

- **EventApiClient 직접 비동기화**: 기존 클라이언트를 asyncio 기반으로 교체. 파이프라인 전체가 async 구조로 변경되어야 하는 복잡도 높음.

### Reason

- 교체보다 감싸는 구조가 기존 코드 변경을 최소화
- EventApiClient는 HTTP 전송 책임, AsyncEventDispatcher는 queue·worker·retry·drop·flush 책임으로 명확히 분리
- worker별 독립 HTTP session으로 Event·Status·Live Frame 전송 격리

### Consequences

- Event: FIFO bounded queue 100, oldest-drop, 실패 JSONL 기록 (`outputs/api_failed_events.jsonl`), 전송 실패 시 retry 1회
- CurrentStatus / Live Frame: latest-only, **retry 없음** — 실패한 데이터를 retry로 붙잡고 있는 대신 다음 최신 값을 보내는 것이 latest-only 목적에 맞고, retry가 worker의 요청 처리 시간을 늘려 FPS 보호 효과를 깎기 때문
- connect timeout 0.5초, read timeout 1.0초 (설정 변경 가능)
- 종료 flush는 최대 3초 내 best-effort로 수행한다.
- deadline 전에 queue에서 꺼내지 못해 전송을 시도하지 못한 Event는 실패 JSONL에 추가 기록하지 않으며, enqueue 전에 저장된 로컬 EventWriter 결과로 보존한다.
- 1차 전송을 시도했으나 deadline 경과로 retry를 생략한 Event는 `request_failed`, `attempts=1`로 실패 JSONL에 기록한다.

**실패 JSONL 기록 형식**

```json
{
  "failed_at": "2026-07-07T12:00:00Z",
  "reason": "queue_overflow",
  "attempts": 0,
  "event": {}
}
```

- `reason`: queue overflow로 drop된 경우 `queue_overflow`, 그 외에는 `request_failed`
- `attempts`: `queue_overflow`는 `0`, `request_failed`는 1차 실패 후 deadline 경과로 retry를 생략한 경우 `1`, retry까지 실패한 경우 `2`
- 파일 기록 자체가 실패해도 추론 루프는 종료하지 않음
- 기존 로컬 EventWriter 저장은 API queue 등록보다 먼저 수행

---

## ADR-018: Phase 3 인증/인가 경계만 정의하고 구현은 Phase 4로 이관

**Date**: 2026-07-06
**Status**: Accepted

### Context

Phase 3에서 Live View·신규 Event API가 추가되며 보호 대상 endpoint가 늘어난다. 인증/인가를 Phase 3에서 구현할지, 경계만 정의하고 미룰지 결정이 필요했다.

### Decision

Phase 3에서는 역할과 보호 대상 endpoint만 정의하고, 실제 인증 구현은 Phase 4로 이관한다.

```text
Operator: Dashboard·이벤트·통계·Live View 조회
Admin: Zone·System Settings 변경
Pipeline Client: Event·CurrentStatus·Live Frame 전송

GET /health: 공개
보호 대상: /events, /summary, /status/current, /zones, Live View 및 설정 화면
```

JWT / Session / API Key 방식과 실제 로그인·권한 구현은 Phase 4에서 확정한다. Phase 3 로컬 시연 환경에는 인증을 적용하지 않는다.

### Alternatives

- **Phase 3에서 최소 인증(API Key) 도입**: 로컬 시연·팀 내부 검증 단계에서 실익이 적고, 계약이 아직 확정 중인 API에 인증까지 얹으면 개발 속도가 떨어짐.

### Reason

- Phase 3은 계약 확정과 기능 구현이 우선이며, 인증은 배포 단계 관심사에 가까움
- 역할·보호 대상 경계를 먼저 정의해두면 Phase 4에서 인증을 추가할 때 API 재설계가 필요 없음

### Consequences

- Phase 3에서는 인증 코드와 사용자 테이블을 추가하지 않음
- Pipeline 인증과 운영자 인증은 Phase 4에서 분리 검토

---

## ADR-019: Zone 경계 이벤트는 비대칭 시간 확인으로 안정화

**Date**: 2026-07-16
**Status**: Accepted

### Context

Phase 2.5 실시간 테스트에서 zone 경계 근처의 foot point와 bbox가 흔들리며,
동일 Track에 ENTER와 EXIT가 짧은 시간에 반복되는 현상이 확인됐다. 대표 사례는
`track_id=28`에서 7프레임 동안 ENTER/EXIT가 3회 발생한 경우다.

### Decision

`EventManager`가 raw polygon 판정과 confirmed zone 상태를 분리한다. 전이는
`frame_number / fps` 기준의 연속 관측 시간으로 확인한다.

```text
진입 확인: 0.3초
이탈 확인: 0.5초
Track 소실 유예: 0.5초
```

- 진입 후보 중 Track이 사라지면 연속 관측이 끊긴 것으로 보고 후보를 초기화한다.
- confirmed zone 점유는 짧은 이탈이나 Track 누락 동안 유지한다.
- `restricted` 진입은 `ENTER_RESTRICTED`가 `ENTER`를 대체한다.
- `danger` 체류는 `DANGER_ZONE_DWELL`이 `DWELL`을 대체한다.
- 이탈은 모든 zone type에서 기존 `EXIT`를 사용한다.
- polygon buffer 기반 공간 hysteresis는 현재 구현에 추가하지 않는다.

### Alternatives

- **즉시 상태 전이 유지**: 구현은 단순하지만 관찰된 ENTER/EXIT 반복을 줄일 수 없다.
- **polygon 안팎 buffer 적용**: 공간적으로 명확하지만 정규화 좌표, zone 크기,
  카메라 원근에 따른 buffer 튜닝 기준이 아직 없다.

### Consequences

- 짧은 경계 진동과 탐지 누락이 즉시 이벤트로 변환되지 않는다.
- 진입은 0.3초 이상, 이탈과 Track 소실은 0.5초 이상 조건이 연속 관측된 뒤 확정된다.
- 실제 확인 프레임 수는 `ceil(confirm_sec * fps)`이며, 매 프레임 처리되는 정상 루프에서는 임계시간 이후 최대 약 1프레임의 추가 지연이 발생할 수 있다.
- DWELL 시간과 CurrentStatus 점유는 confirmed zone 상태를 기준으로 한다.
- 기본 임계값은 생성자 인자로 조정 가능하며 실영상 전후 비교 후 재튜닝한다.

---

## ADR-020: Track ID 안정화 범위와 잔존 오탐 대응 방향

**Date**: 2026-07-20
**Status**: Accepted

### Context

동결한 낙상 판정 로직·cause attribution 자체는 바꾸지 않는다는
전제 아래, ByteTrack/PoseTracker의 ReID 부재로 Track ID가 바뀌는 경우의
견고성을 보강했다(Candidate Handoff, Cooldown Handoff). 상세 설계와 수치는
`docs/fall_evaluation.md`의 Track ID 안정화 절에 기록한다. 안정화 이후
Subject 7-8 진단에 남은 오탐 4건(S7_kneel, S7_pick_up_object, S7_sit_down,
S8_sit_down)은 전부 `confirm_path=model`이라, temporal vote 강화나 약한
motion 게이트로 추가 필터링할지 결정이 필요했다.

### Decision

규칙 기반 게이트(temporal vote 확장, aspect_ratio/속도 하한, 최근
bbox/Pose 보조 근거 요구 등)는 **구현하지 않는다** — 기본 비활성 실험
옵션으로도 추가하지 않는다. 대신 다음을 채택한다.

- 현재 Cooldown Handoff까지의 설정(`configs/fall_detection.json`)을
  기준선으로 동결한다.
- Subject 7-8의 정상 활동 전체 프레임을 추가한 hard-negative 교차 실험은
  한쪽 Fold의 Recall 하락으로 채택하지 않는다. 후속 데이터 개선은 실제
  false Event 주변 구간만 선별하거나, Phase 4의 경량 temporal classifier로
  전환하는 방식으로 제한한다. Subject 9-10 holdout은 재학습에 사용하지 않는다.
- Validation 디렉터리(Subject 7-8)는 이 진단 과정에서 직접 보고 규칙을
  설계·검증하는 데 이미 쓰였으므로, 이 시점부터 "보지 않은 최종 검증
  데이터"가 아니라 tuning/diagnostic 데이터로 취급한다. 이후 최종 성능
  평가는 Subject 9-10(holdout) 또는 별도 외부 데이터로 한다.

### Reason

- 이미 `model_vote_window_sec` 기반 bounded temporal voting을 쓰고
  있다. Event를 유발한 최초 연속 오분류 구간은 5-28프레임이고, 영상 전체의
  최장 연속 오분류 구간은 5-85프레임이다. 짧게 흩어진 패턴이 아니므로
  voting을 더 엄격하게 해도 근본적으로 걸러지지 않는다.
- 캐시 데이터로 직접 검증한 결과, 진짜 model-only TP(S8_fall_forward,
  `aspect_ratio` 0.34-0.4)와 오탐(S7_sit_down, `aspect_ratio`
  0.33-0.41)의 aspect_ratio·속도가 사실상 겹친다. 최근 bbox/Pose 보조
  근거를 추가로 요구하는 규칙은 Subject 7-8 FAR를 0/min까지 낮추지만
  Development의 `S4_fall_sitting` TP(강한 동적 근거 없는 model-only
  케이스)를 함께 잃어 Development Recall이 83.3%→76.7%로 떨어진다 —
  오탐 제거가 아니라 Precision-Recall 교환이다.
- 즉 잔존 문제는 임계값이 부정확한 게 아니라, 보조 모델이 "앉기·무릎
  꿇기·줍기"와 "낙상"을 bbox/Pose 수준의 정적·동적 특징만으로는 의미적으로
  구분하지 못하는 것이다 — 얕은 기하학적 규칙을 더 얹는 방향으로는 원리상
  한계가 있다.

### Alternatives

- **약한 motion/aspect_ratio 게이트 채택**: 구현은 간단하지만 위 근거대로
  실측 TP 손실이 확인됐다. 기각.
- **temporal vote 창/K-of-N 강화**: 오탐이 짧게 흩어진 패턴이 아니므로
  효과가 제한적일 것으로 판단해 기각.
- **model-only candidate 진입 전면 차단**: Recall 손실이 더 크다(model-only
  경로가 복구하는 timely TP를 함께 잃어 기각).

### Consequences

- Cooldown Handoff 이후 설정이 이 시점의 동결 기준선이다 — 오탐 4건은
  알려진 한계로 남는다.
- 다음 정확도 개선은 코드 규칙이 아니라 오탐 구간 중심 데이터 보강 또는
  모델 아키텍처(Phase 4 temporal classifier) 방향이다.
- Subject 9-10 holdout 평가 전, Subject 7-8 기반 수치를 "최종 성능"으로
  보고하지 않도록 문서·리포트에서 주의가 필요하다.
- ReID 기반 Track 재연결과 공간 buffer 튜닝은 별도 후속 작업이다.

---

## ADR-021: Pose NORMAL 기반 보조 모델 추론 스케줄링

**Date**: 2026-07-22
**Status**: Accepted (opt-in)

### Context

Phase 3 통합 측정에서 PoseTracker와 `fall_detector_v1.pt`를 매 frame 함께
실행한 능동 인원 경로가 목표 처리량을 충족하지 못했다. 단순 고정 간격 실행은
비용을 줄이지만, 새 Track이나 낙상 징후가 시작된 시점에도 다음 scheduled
frame까지 기다릴 수 있다. ADR-020에서 기각한 Pose 게이트는 model-only Event에
추가 확정 근거를 요구해 Recall을 낮추는 판정 규칙이었다.

### Decision

Event 확정 임계값은 변경하지 않고 다음 opt-in 추론 스케줄링을 추가한다.

- 모든 active Track이 충분히 관측됐고, Pose가 유효하며, 직립·비하강 상태일
  때만 RGB 보조 detector 실행을 생략하고 해당 Track을 `nofall`로 처리한다.
- Track 하나라도 신규·Pose 미확인·하강·비정상 자세이면 보조 detector 경로로
  즉시 복귀한다. 새 Track과 fallback 진입 frame은 interval을 기다리지 않는다.
- fallback 안에서는 Track별 직전 evidence를 최대 `interval-1` frame만 유지한다.
- 검증 프로파일은 `--fall-pose-normal-gate-enabled`와
  `--fall-model-interval-frames 3` 조합이다. 두 옵션의 기본값은 기존 동작을
  보존하도록 각각 비활성, `1`로 유지한다.
- 여러 사람이 있으면 모든 Track이 안전 조건을 만족해야만 추론을 생략한다.
- 하강 판정은 정규화된 foot point 수직 속도 `0.3` 초과 또는 bbox 높이 변화율
  `-0.3` 미만을 게이트 전용 기준으로 사용한다. center 수직 속도는 기존
  `recovery_velocity_threshold`를 공유한다. 두 게이트 전용 값은 보수적으로
  하강 fallback을 유지하면서 Development와 S7-8 전체 캐시 회귀를 통과한
  채택값이며, `PoseNormalGateConfig` 기본값으로 고정한다.

이 결정은 ADR-020의 Event 확정용 규칙 게이트 기각을 뒤집지 않는다. 다만
안정적인 정상 자세에서 보조 모델 evidence를 `nofall`로 대체하므로 Event 결과에
영향을 줄 수 있으며, 그 영향은 Development와 S7-8 전체 캐시 회귀로 검증한다.

### Evidence

- Development S1-6: Recall 83.3%, timely Recall 66.7%, FAR 0/min, 중복 0건 유지
- S7-8 tuning/diagnostic: Recall 100%, timely Recall 90%, 중복 0건 유지,
  FAR 2.34→1.75/min
- 평균 onset latency 증가는 Development 약 0.092초, S7-8 약 0.100초
- M1/MPS 동일 능동 인원 입력 각 3회 중앙값: 최적화 ON 13.511 FPS,
  낙상 OFF 14.571 FPS 대비 7.3% 감소
- interval 2/3/4가 같은 sample Event를 frame 87에 생성했고, interval 3은
  interval 2보다 빠르며 interval 4와의 차이는 실행 편차 수준이라 보수적으로
  interval 3을 선택했다.

### Consequences

- 보조 모델 호출 비용과 S7-8의 일부 정상 자세 오탐이 함께 줄었다.
- 운영 FAR 목표 0.2/min은 여전히 충족하지 못하므로 낙상 기능은 opt-in이다.
- MPS 수치는 단일 파일의 반복 측정 결과이며 API·Live Frame, 다른 장치,
  장시간 카메라에서는 다시 측정해야 한다.
- 실제 접촉 원인 정확도, Subject 9-10 holdout, 외부 데이터 일반화 정책은
  변경하지 않는다.

---

## ADR-022: Phase 4 계약과 평가 프로토콜을 기능 구현보다 먼저 동결

**Date**: 2026-07-29
**Status**: Accepted

### Context

Phase 4에서는 A의 낙상 평가, B의 Event·Zone API, C의 Report·Zone UI가
병렬로 진행된다. 기간 경계, Zone version, Cause 분모, Track·Actor mapping을
각 역할이 다르게 해석하면 구현 완료 후에도 결과를 비교할 수 없다. Subject
7-8은 이미 tuning에 사용됐고 Subject 9-10은 최종 holdout으로 남아 있어,
평가 규칙을 사후 변경하면 결과 신뢰성도 훼손된다.

### Decision

- `docs/api_contract.md`, `docs/interfaces.md`, `docs/fall_evaluation.md`와
  machine-readable fixture를 기능 PR보다 먼저 병합한다.
- 공식 낙상 평가는 `phase4_fall_eval_v1`을 사용한다.
- timely window, Event matching, duplicate, FAR, Cause, ID switch 판정 규칙을
  동결한다.
- Subject 9-10 열람 전 모델·tracker·config·threshold·evaluator commit을
  동결한다.
- holdout 열람 후 치명적인 평가기 오류를 수정해야 하면 protocol version을
  올리고 기존 결과를 보존한다.
- C는 fixture로 선개발하고 B의 endpoint가 준비되면 연결만 교체한다.

### Consequences

- 계약 PR은 실제 production 동작을 변경하지 않지만 A/B/C의 구현 기준이 된다.
- `GET /zones` envelope 변경은 계획된 breaking contract이며 B/C가 함께
  반영한다.
- 계약 변경은 문서·fixture·테스트와 세 역할 승인이 필요하다.

---

## ADR-023: Homography는 기본 비활성 PoC로 분리하고 정량 기준으로 채택

**Date**: 2026-07-29
**Status**: Accepted

### Context

현재 Zone 판정은 pixel foot point와 image-normalized polygon을 사용한다.
고정 카메라의 원근 오차를 floor-plane 좌표로 줄일 수 있지만 calibration
오차, 카메라 이동, 운영 재설정 비용이 추가된다. 실제 정확도 개선을 확인하지
않고 production 경로를 바꾸면 기존 Zone 안정성을 잃을 수 있다.

### Decision

- Homography는 고정 카메라 1대·단일 평면·기본 비활성 PoC로 구현한다.
- fit point와 holdout point를 분리하고 동일 Track·foot point 입력으로 기존
  방식과 비교한다.
- 위치 평균·p95, Zone 오류, ENTER·EXIT 오류, latency·FPS, calibration 시간을
  측정한다.
- 절대 오차 기준은 8월 7일 공간 실측 후 holdout 결과를 보기 전에 동결한다.
- 모든 `homography_acceptance_v1` 조건을 만족할 때만 production 확장을 별도
  PR로 진행한다.
- Event의 pixel `foot_point`와 기존 image-coordinate 경로는 유지한다.

### Consequences

- PoC 실패나 개선 불안정은 정상적인 미채택 결과로 기록한다.
- calibration·floor-zone 편집 UI와 cross-camera 좌표 통합은 범위에서 제외한다.
- 카메라 ID·해상도 불일치는 fail-fast하며 기존 경로로 조용히 fallback하지
  않는다.

### Outcome (2026-08-11)

**미채택.** 2026-08-07 촬영분으로는 채택 조건을 만족하지 못했다. production
경로는 기존 image-normalized polygon을 유지하고 `calibration.enabled`는 기본값
`false` 그대로다. 이 ADR이 "PoC 실패나 개선 불안정은 정상적인 미채택 결과로
기록한다"고 정한 경로를 그대로 따른다.

통과한 항목: frame당 추가 비용 +0.0237ms(기준 1ms), 빠른 ENTER·EXIT 반전 증가
없음, 해상도 불일치 fail-fast, 기존 경로 회귀 없음.

미채택 사유는 네 가지다.

- **절대 오차 기준(1번) 판정 불가.** 허용값은 holdout 결과를 보기 전에 동결해야
  하는데 그 절차를 수행하지 못했다. 이 ADR은 절대 오차 수치를 정한 적이 없고,
  결과를 본 뒤 어떤 값을 가져와 대입해도 동결이 아니므로 대체 기준도 쓰지
  않는다. 표본도 계약 요건에 미달한다. 클립을 13개로 늘려 관측은 78회로 20회
  요건을 넘겼지만 기준점이 10개뿐이라 fit 4를 뺀 holdout 위치가 6개로 고정되고,
  이는 클립을 더 늘려도 해소되지 않는다. 공식 경로로 산출한 평균 1.09·p95 1.87
  원단위는 진단값이다.
- **calibration 15분 기준(9번) 미달.** 촬영 중 카메라가 고정되지 않아(클립 간
  최대 8.5도 회전) 클립마다 calibration을 다시 해야 했다. 클립별로 다시 찍으면
  변환 자체는 성립한다는 것은 확인했다. 같은 기준점을 13개 클립에서 각각 찍은
  78쌍에서 image 좌표로는 최대 131.0px 어긋났지만 floor 좌표로는 최대 1.60
  원단위 안에서 일치했다. 알고리즘이 아니라 운영 비용이 걸리는 항목이다.
- **Zone 정확도·오판정(2·3번) 미달, Event 오류(4번) 판정 불가.** A 역할의
  ground truth 12영상·경계 24건으로 측정했다. 두 좌표 경로가 정확도 91.695%,
  오판정 552건, ENTER·EXIT Event 오류 0건, 빠른 반전 0건으로 **완전히 같았다.**
  4번은 기존 경로 오류가 0건이라 감소율을 정의할 수 없다. 개선이 나오지 않은
  것은 변환 정확도 때문이 아니라 image Zone과 floor Zone을 같은 클릭에서 만들어
  두 경로가 정의상 같은 판정을 내기 때문이다. Homography 경로의 값어치를
  측정하려면 Zone을 floor 좌표에서 독립적으로 정의해야 한다.
- **FPS 하락률(7번) 미측정.** 계약은 두 경로를 같은 조건으로 실행해 얻은 실측
  FPS를 요구하는데, `FloorZoneChecker`가 production 파이프라인에 연결돼 있지
  않아 실행 자체가 불가능하다. microbenchmark의 추가 비용으로 역산한 추정치만
  있고 공식 판정에 쓰지 않는다. 이 ADR이 production 확장을 채택 이후 별도 PR로
  미뤘으므로 미채택 상태에서 그 연결을 만들지 않는다.

2~5번은 측정을 마쳤고 1·9번은 촬영 현장에서만 해소된다. 2·3번의 미달도 Zone
정의를 분리한 재촬영이 있어야 다시 판정할 수 있다. 따라서 이번 데이터로는 후속
분석으로 채택에 도달할 수 없다. 도구와 절차, 측정된 수치는 다음 촬영의 사전
근거로 보존한다.

측정 수치·판정 근거·다음 촬영 보완 사항은
[docs/homography_calibration.md](homography_calibration.md) 7절에 있다.

---

## ADR-024: 목표 카메라 E1 낙상 모델 채택과 opt-in 운영

**Date**: 2026-08-11
**Status**: Accepted

### Context

Phase 3 낙상 모델은 8월 7일 실제 키즈카페 목표 IP 카메라 구도에서 촬영한
E0의 Recall이 6.25%였다. 주요 원인은 후보 진입이 아니라 카메라 구도 차이로
인한 보조 detector 확정 실패였다.

### Decision

- 실제 키즈카페에서 성인이 통제 재연한 A01 frame으로 fine-tuning한 E1을
  목표 카메라의 낙상 모델로 채택한다.
- 학습에 사용하지 않은 A02 diagnostic과 actor-disjoint A03 test로 목표 환경
  성능을 검증한다.
- 동일 A01·A02 diagnostic에서 Recall이 E0 6.25%에서 E1 93.75%로 개선됐다.
- A03에서 Recall 93.3%, timely Recall 93.3%, FAR 0.0/min, 중복 Event 0건을
  확인한 E1을 목표 환경의 selected profile로 동결한다.
- A03 no_fall은 줍기 3편·27.2초이고 A01·A02 diagnostic에는 다중 인원 가림
  false Event 1건이 있다. 장시간 RTSP와 Cause 평가 전까지 CLI 기본값은
  비활성으로 유지하고 `--fall-detection-enabled`로 명시적으로 켠다.
- Selected profile은 PoseTracker, 보조 모델 interval `3`, Pose NORMAL gate를
  사용한다. profile과 다른 실험은 custom run으로 구분한다.
- 목표 환경 모델의 채택 판단은 실제 키즈카페 카메라의 actor-disjoint 평가를
  따른다.
- 모델 파일은 Git에 포함하지 않고 SHA-256과 동결 manifest로 동일성을 확인한다.
- CLI selected mode는 입력 소스를 열기 전에 tracker 모델·낙상 config·보조 모델
  SHA-256과 confidence·IoU·interval·Pose gate를 검증하고, 불일치하면 실행을
  중단한다. 커스텀 실행은 별도 mode와 모델 SHA-256을 사용한다.
- CAUCAFall은 초기 구현용 공개 데이터의 참고 회귀로 보존한다. E1에서 Development
  Recall 83.3%·timely Recall 70%·FAR 0.0/min을 기록했지만 중복 Event 1건이 있었고,
  S7-8은 Recall 100%·timely Recall 90%와 false Event 5건(FAR 2.9197/min)을
  기록해 기존 참고 회귀 기준을 통과하지 못했다.

### Consequences

- 기본 실행은 낙상 기능을 끈 경량 경로를 사용한다. E1을 명시적으로 활성화한
  selected mode는 동결 artifact와 inference 설정 불일치를 fail-closed로 중단한다.
- A03 no_fall은 주요 오탐 행동인 줍기 3편, 27.2초이며 false Event는 0건이다.
  앉기는 A01·A02 diagnostic 6편에서 false Event 0건을 확인했지만,
  actor-disjoint 앉기와 장시간 정상 행동 검증은 계속한다.
- 장시간 RTSP에서 걷기·앉기·줍기·눕기·가림·정지 동작과 Cause·ID switch를
  검증한 뒤 기본 ON 전환을 별도 PR에서 판단한다.
- 동일 환경 E0·E1 각 3회 측정 FPS 중앙값 비교로 하락률 -0.5%(개선)를 확인해
  FPS 채택 기준을 충족했다(`docs/fall_evaluation.md` §14.15).
