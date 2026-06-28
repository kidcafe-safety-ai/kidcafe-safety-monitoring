# Phase 2.5 Docker 실행 가이드

> **작성일**: 2026-06-27
> **범위**: FastAPI + SQLite volume + React Dashboard Docker 구성

이 문서는 Phase 2.5 기준 FastAPI와 React Dashboard Docker 실행 방법을 정리한다.

이번 Docker 작업의 목적은 운영 배포가 아니라, 중간평가와 시연 전에 FastAPI API 서버와 React Dashboard 실행 환경을 재현 가능하게 만드는 것이다.

> **주의**: 현재 `frontend` 컨테이너는 Vite dev server(`npm run dev`)로 실행한다. 따라서 이 구성은 Phase 2.5 시연·통합 검증용이며 운영 배포용 Docker 구성은 아니다. 운영 배포에 필요한 정적 파일 서버, reverse proxy, TLS, production 최적화는 이번 범위에 포함하지 않는다.

## 포함 범위

- FastAPI API 서버 컨테이너 실행
- SQLite DB 파일을 `outputs/` bind mount로 유지
- React Dashboard 컨테이너 실행
- React Dashboard API mode 연결
- `/health`, `/status/current`, `/events/recent` API smoke 확인

## 제외 범위

- Vision AI pipeline Docker 실행
- YOLO / torch / ultralytics / opencv 추론 환경 포함
- USB 웹캠 passthrough
- RTSP 운영 안정화
- React production 정적 파일 배포 및 reverse proxy 구성
- TLS, 운영 도메인, production 성능 최적화
- Event Schema / CurrentStatus / API contract 변경
- DB schema 변경

Vision AI 웹캠 pipeline은 Phase 2.5 기준 로컬 실행을 유지한다.

## 파일 구조

```text
Dockerfile.api
docker-compose.yml
requirements-api.txt
.dockerignore
.env.example
frontend/Dockerfile
frontend/.dockerignore
frontend/.env.example
docs/docker_phase_2_5.md
```

`requirements-api.txt`는 FastAPI 서버 실행에 필요한 최소 의존성만 포함한다. Vision AI 추론용 `torch`, `ultralytics`, `opencv-python`은 API 컨테이너에 포함하지 않는다.

`Dockerfile.api`는 `/zones` API가 기본 zone 정의를 읽을 수 있도록 `data/zones/` 디렉터리를 컨테이너에 포함한다.

`frontend/Dockerfile`은 React Dashboard 의존성을 설치하고 build 검증 후 Vite dev server를 `0.0.0.0:3000`으로 실행한다. Docker image 생성 중 `npm run build`를 수행하지만 이는 TypeScript/Vite build 통과 여부를 확인하기 위한 단계이며, 컨테이너의 실제 runtime은 `npm run dev`이다.

## 환경변수

API 서버는 SQLite DB 경로로 `KIDCAFE_DB_PATH`를 사용한다.
React Dashboard는 Vite 환경변수로 API mode와 API base URL을 설정한다.

```env
KIDCAFE_DB_PATH=/app/outputs/kidcafe_events.db
VITE_API_MODE=api
VITE_API_BASE_URL=http://localhost:8000
```

React 코드는 브라우저에서 실행되므로 `VITE_API_BASE_URL`은 Docker service name이 아니라 호스트에서 접근 가능한 `http://localhost:8000`을 사용한다.

Docker Compose는 기본적으로 `.env` 파일을 자동으로 읽는다. 로컬 실행 시 아래처럼 예시 파일을 복사해서 사용할 수 있다.

PowerShell:

```powershell
Copy-Item .env.example .env
```

Bash:

```bash
cp .env.example .env
```

`.env`는 로컬 실행 파일이므로 Git에 포함하지 않는다.

## 실행

```bash
docker compose up --build
```

백그라운드 실행이 필요하면 아래 명령을 사용한다.

```bash
docker compose up --build -d
```

API 서버는 호스트 기준 `http://localhost:8000`에서 접근한다.
React Dashboard는 호스트 기준 `http://localhost:3000`에서 접근한다.

## Smoke Test

컨테이너 실행 후 아래 API를 확인한다.

PowerShell:

```powershell
curl.exe http://localhost:8000/health
curl.exe http://localhost:8000/status/current
curl.exe "http://localhost:8000/events/recent?limit=10"
```

Bash:

```bash
curl http://localhost:8000/health
curl http://localhost:8000/status/current
curl "http://localhost:8000/events/recent?limit=10"
```

기대 결과:

- `/health`: `status: "success"`, `healthy: true`
- `/status/current`: current status가 없으면 `source: "unknown"` 기본값 반환
- `/events/recent?limit=10`: 이벤트가 없으면 빈 배열 반환
- `http://localhost:3000`: React Dashboard 접속 가능
- React Network 요청 기준 `/status/current`, `/events/recent`, `/summary`가 `http://localhost:8000`으로 호출됨

## SQLite 저장 경로

Compose는 로컬 `./outputs` 디렉터리를 컨테이너의 `/app/outputs`에 bind mount한다.

```yaml
volumes:
  - ./outputs:/app/outputs
```

따라서 컨테이너 내부 DB 경로는 아래와 같다.

```text
/app/outputs/kidcafe_events.db
```

로컬에서는 아래 파일로 유지된다.

```text
outputs/kidcafe_events.db
```

`outputs/`와 DB 파일은 실행 산출물이므로 Git에 포함하지 않는다.

## Vision AI 연동 기준

로컬 Vision AI pipeline에서 Docker API 서버로 이벤트를 전송할 때는 아래 API URL을 사용한다.

```bash
--api-url http://localhost:8000
```

Vision AI는 로컬에서 실행하고 Docker API 연동만 검증한다.

## 종료

백그라운드로 실행했다면 확인 후 컨테이너를 종료한다.

```bash
docker compose down
```

SQLite DB 파일을 포함한 `outputs/`는 bind mount로 유지된다. DB 파일을 삭제하려면 로컬 `outputs/kidcafe_events.db`를 직접 정리한다.

## macOS 검증 완료

- 날짜: 2026-06-28
- 환경: macOS, Docker Desktop 4.79.0, Docker Engine 29.5.3, Docker Compose v5.1.4
- `docker compose up --build -d` 정상 실행 확인
- kidcafe-api healthy, frontend Up 확인
- `/health`, `/status/current`, `/events/recent`, `/summary` smoke test 통과
- 로컬 Vision AI(mac 내장 웹캠) → Docker FastAPI → SQLite E2E 흐름 확인
- `docker compose down` → `docker compose up -d` 후 DB 유지 확인
