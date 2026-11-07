# Frontend·Dashboard 운영 가이드

> **담당 영역**: C — Frontend·Dashboard·UX
>
> **기준**: `main` @ `9869277e` (애플리케이션 `v0.3.0`)
>
> **최종 수정**: 2026-10-15

## 화면과 데이터 출처

| 화면 | API 모드 데이터 | 갱신 |
| --- | --- | --- |
| 실시간 모니터링 | `GET /status/current` 인원·점유, `GET /zones` 전체 설정 구역, `GET /summary` 이벤트 KPI, `GET /events/recent?minutes=10&limit=2`, `GET /live/frame` JPEG | 상태 2초, Zone 설정·요약 10초, 최근 이벤트 1초, Live Frame 기본 1초 |
| 알림 기록 | `GET /events`의 실제 Event를 알림으로 표시 | 5초 |
| 이벤트 기록 / 통계 | `GET /events`의 실제 Event | 5초 |
| 안전 리포트 | `GET /events?created_from=...&created_to=...&limit=100&offset=...` | 조회 버튼을 누를 때 |
| 안전구역 / 알림 설정 | `GET /zones`, `PUT /zones` | 진입·수동 재조회·저장 |

`VITE_API_MODE=api`이면 모든 활성 화면은 API 응답만 사용한다. 요청 실패 시
Mock 데이터를 대신 표시하지 않는다. `VITE_API_MODE=mock`(기본값)은 로컬
시연용 Mock Event·상태·Zone 데이터를 사용하며 Live Frame은 비활성 placeholder다.
소스에 남아 있는 System Settings Mock 모달은 어느 화면에서도 호출되지 않는다.

## 환경변수와 polling

| 변수 | 기본값 | 의미 |
| --- | --- | --- |
| `VITE_API_MODE` | `mock` | `api`일 때 실제 Backend 사용 |
| `VITE_API_BASE_URL` | `http://localhost:8000` | Backend 주소 |
| `VITE_LIVE_FRAME_POLL_INTERVAL_MS` | `1000` | Live Frame 완료 후 다음 요청까지의 간격. 250–60000ms 유효, 범위 밖은 기본값 |

Vite 환경변수는 빌드 시 적용된다. Live Frame은 이전 요청이 완료되거나
3초 timeout에 도달한 뒤 다음 요청을 예약한다. 응답이 역순으로 완료돼도
timeout된 응답은 화면을 덮어쓰지 않는다. unmount 시 요청을 abort하고
object URL을 해제한다. 그 밖의 polling은 `usePolling`의 10초 watchdog,
AbortSignal, 활성 요청 검사를 사용한다. 모니터링 첫 로드는 묶음 조회로 시작하며
실패·timeout 후 3초 간격으로 재시도한다.

## 상태 처리

- Monitoring: 처음에는 loading과 `-`를 표시한다. 정상적인 0명 상태는
  `updated_at: null`을 포함해 그대로 0으로 표시한다. 설정된 모든 Zone을
  나열하고 status에 없는 Zone은 종류와 관계없이 0명·NORMAL로 표시한다. API 장애 시 이전 값이
  남을 수 있으므로 오래된 데이터 경고를 띄우며 다음 성공 응답에서 회복한다.
- Live Frame: JPEG 200은 원본 종횡비를 유지해 표시한다. 첫 204는 빈
  placeholder, 이전 프레임 이후 204는 만료 상태다. 서버 재시작이나 3초
  frame 만료 후의 204도 정상적인 빈 응답으로 취급한다. 네트워크·형식 오류는
  오류 상태이며 다음 polling에서 회복한다. 오래된 이미지는 유지하지 않는다.
- 이벤트/알림: 처음 loading, 성공한 빈 목록은 empty, 실패 시 오류와
  오래된 데이터 경고를 표시한다. `GET /events` 페이지를 끝까지 조회해
  Event History의 기본 50건 제한을 피한다. 조회 중 total 변동이나 중복으로
  목록이 어긋나면 부분 결과를 성공으로 표시하지 않는다. 알 수 없는 EventType은
  일반 이벤트 표시와 안전한 severity fallback을 사용한다. `zone_name: null`
  은 `zone_id`로 표시하고 `__global__`은 전체 구역으로 표시한다.
- Report: 서울 날짜 양끝을 포함하는 선택을 timezone 포함
  `created_from` 이상·`created_to` 미만으로 변환한다. 기준은 영상
  `timestamp`가 아니라 서버 저장 시각 `created_at`이다. 최대 31일,
  페이지당 100건·최대 200페이지를 조회하고 Event ID로 중복을 제거한다.
  페이지 누락·중복·조회 중 변경은 오류로 처리하며 미완성 집계는 표시하지
  않는다. 전체 조회가 30초를 넘으면 취소하고 재조회할 수 있다. 비어 있는
  기간은 0건으로 표시한다.
- Zone Settings: 로드 실패와 빈 설정을 구별한다. 로컬에서 ID·이름·좌표·
  polygon·rules를 검증한 뒤 전체 Zone과 `expected_version`을 저장한다.
  409에서는 최신 설정을 재조회하고 미저장 draft 복원 선택지를 남긴다.
  422는 `{"detail":[...]}`의 메시지를, 500은 서버 저장 실패를 따로
  표시한다. 요청 중 unmount·늦은 응답은 화면에 적용하지 않는다.

## 계약 확인과 남은 한계

최종 `main`의 `src/api/main.py`, `src/api/repositories.py`,
`src/api/schemas.py`, `docs/api_contract.md`, `docs/interfaces.md`를
확인했다. 422는 FastAPI detail 배열이며 명시적 409·500은
`status/data/message` envelope다. 최신 status source는 timezone offset을
절대 시각으로 비교한다. status row가 없을 때 0명·`updated_at: null`이다.
Live Frame은 200 JPEG 또는 body 없는 204다. Report는 별도 엔드포인트가
없다. Zone 저장은 version 충돌 409·검증 422·저장 실패 500이다.

자동화 테스트에서 빈 status(0명·null), timezone 포함 기간 조회, 설정 Zone,
Live Frame 204, Zone 409·422 계약을 확인했다. 최종 `main`의 Docker 통합 실행에서는
실제 Event·CurrentStatus·Live Frame과 Dashboard 표시, 종료 직후 0명·NORMAL을
확인했다. 세부 조건과 관찰값은 [`final_validation.md`](final_validation.md)에 있다.

이벤트 목록은 최대 20페이지(최대 9,550건)까지 읽는다. 기간 중 신규 이벤트가 들어와
offset 순서가 변하면 오류를 표시하고 다음 polling에서 재시도한다. Report는
최대 20,000건까지 조회하며 그 이상은 기간 축소가 필요하다. Zone 설정은
저장 후 Vision AI 재시작 시 적용된다.

## 검증

```bash
cd frontend
npm ci
npm run test -- --run
npm run build
cd ..
git diff --check
```

최종 `main` 기준 Vitest는 63 passed, 1 skipped이며 build도 통과했다. 전체 CI 결과는
[`final_validation.md`](final_validation.md)를 기준으로 한다. Backend 계약 통합 테스트는
별도 API 서버에서 `PR67_API_URL=http://127.0.0.1:18080`을 지정해 실행하며,
환경변수가 없으면 해당 테스트만 건너뛴다. 테스트 파일의 PR 번호는 레거시 이름이다.

Windows PowerShell에서 `npm.ps1` 실행이 제한된 경우 `npm.cmd`를 사용한다.
