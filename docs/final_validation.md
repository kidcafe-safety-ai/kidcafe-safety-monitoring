# 최종 통합 검증 기록

> 기준일: 2026-10-15
>
> 기준 브랜치: `main`
>
> 기준 커밋: `9869277e3239d5173935a5d88dfbc966bd10d5ae`
>
> 범위: Vision AI·Backend·Database·Dashboard 최종 통합

## 1. 자동화 검증

| 구분 | 검증 내용 | 결과 |
| --- | --- | --- |
| Backend CI | `flake8 src tests`, 전체 `pytest -q` | 통과 |
| Frontend CI | `npm ci`, `npm run test -- --run`, `npm run build` | 통과 |
| Frontend local | Vitest 63 passed, 1 skipped | 통과 |
| Production-class dependency audit | `npm audit --omit=dev` | 취약점 0건 |
| Docker | `docker compose config`, Backend health, Frontend 접근 | 통과 |
| 정적 확인 | `git diff --check` | 통과 |

[GitHub Actions 최종 실행 결과](https://github.com/kidcafe-safety-ai/kidcafe-safety-monitoring/actions/runs/38714530551)

## 2. 통합 실행 조건

| 항목 | 조건 |
| --- | --- |
| 실행 환경 | macOS, Docker Desktop |
| Vision AI 장치 | CPU |
| 입력 | 동일 규격의 영상 2개, playlist |
| 처리 범위 | 총 600 frame |
| 낙상 감지 | 비활성화 |
| 연동 | Event API, CurrentStatus, Live Frame, React Dashboard |

## 3. 통합 검증 결과

| 검증 항목 | 결과 |
| --- | --- |
| playlist 전환 | 2개 파일 순서 전환 및 600 frame 처리 확인 |
| 영상별 시간축 | 파일 전환 후 source frame·timestamp 초기화 확인 |
| 위험구역 Event | `danger_zone` ENTER 1건, EXIT 1건 생성 |
| 저장 일치 | API 조회와 SQLite 저장 Event 일치 |
| Dashboard | 현재 상태, Event 2건, Event 표와 Zone 설정 표시 확인 |
| Live Frame | JPEG 640×360, 원본 종횡비 유지 |
| 최종 입력 상태 | 두 번째 영상 source frame 93 확인 |
| 종료 처리 | 전체 Zone 0명·NORMAL 전송 확인 |
| API 전송 | 통합 실행 중 전송 실패 없음 |

관찰된 Event 기준값:

| Event | Source frame | 영상 timestamp |
| --- | ---: | ---: |
| ENTER | 160 | 2.669초 |
| EXIT | 373 | 6.223초 |

## 4. 재현 순서

```bash
python scripts/init_zone_runtime.py
docker compose up --build -d
python scripts/api_smoke_test.py --base-url http://localhost:8000

python -m src.main \
  --source-type file \
  --file-playlist data/videos/demo_01.mp4 data/videos/demo_02.mp4 \
  --zones outputs/zones_runtime.json \
  --api-url http://localhost:8000 \
  --live-frame-enabled \
  --fall-detection-disabled \
  --frames-limit 600
```

영상은 저장소에 포함되지 않으며, playlist 파일은 동일 FPS·해상도를 사용해야 합니다.

## 5. 남은 운영 범위

- 장시간 RTSP와 네트워크 단절 후 자동 재연결은 별도 운영 환경 검증이 필요합니다.
- 낙상 의심 감지는 동결된 모델 weight를 별도로 준비한 환경에서 활성화해야 합니다.
- 인증·인가, production Web server, 외부 모니터링은 현재 프로토타입 범위가 아닙니다.
- 전체 `npm audit`에는 Vite·Vitest 계열 개발 도구 advisory 9건이 남아 있습니다.
  해소에는 major version 변경과 회귀 검증이 필요하며, 현재 Vite 서버는 로컬 시연
  환경에서만 사용하고 공용 네트워크에 노출하지 않습니다.
- macOS iCloud 동기화 폴더는 가상환경·DB 파일을 오프로드해 실행을 지연시킬 수 있으므로, 장기 실행은 동기화되지 않는 로컬 경로를 권장합니다.
