# Dashboard MVP 작업 정리

> **작성일:** 2026-05-24  
> **작성자:** 정현수 (Dashboard 담당)
> **관련 문서:**  
> - `dashboard_api.md`  
> - `dashboard_analysis.md`  
> - `interfaces.md`  
> - `decisions.md`

이 문서는 **Streamlit 기반 KidCafe Safety AI 대시보드 MVP**에서 구현한 기능, 현재 제한 사항, 충돌 해결 내용을 정리합니다.

---

# 1. 작업 개요

이번 작업에서는 영상 분석 파이프라인 결과를 **Streamlit 대시보드에서 확인할 수 있도록 MVP 화면을 구성**했습니다.

대시보드는 아래 산출물을 기반으로 동작합니다.

## 사용 산출물

```text
outputs/events.jsonl
outputs/events.csv
outputs/summary.json
outputs/result.mp4
data/zones/sample.json
```

---

# 2. 주요 구현 범위

| 영역 | 구현 내용 |
|---|---|
| 홈 대시보드 | 영상 업로드, 파이프라인 실행, KPI 카드, 최근 이벤트, 산출물 상태 표시 |
| Zone 편집 | Zone JSON 로드, 좌표 입력, 검증, 영상 첫 프레임 미리보기, JSON 다운로드 |
| 모니터링 | 결과 영상 확인, 최근 이벤트 표시, 이벤트 타임라인 차트 |
| 통계 대시보드 | 이벤트 KPI, Zone별 이벤트, 시간대별 이벤트, 이벤트 타입 비율, 체류 시간 분포 |
| 개별 리포트 | Track ID 기준 활동 요약, 체류 시간, 활동 강도, 이동 Heatmap |
| 설정 | 데이터 경로 관리, 산출물 상태 확인, 백업 다운로드, 텍스트 산출물 초기화 |
| 차트 API | 이벤트 차트와 Track ID 차트 함수 분리 |
| 데이터 API | 대시보드에서 사용할 이벤트 / summary / zone 로더 및 helper 추가 |

---

# 3. 실제 동작하는 기능

| 기능 | 설명 | 연결 데이터 / 코드 |
|---|---|---|
| 영상 업로드 | 사용자가 영상을 업로드하면 임시 경로에 저장 | Streamlit file uploader |
| 파이프라인 실행 | 업로드 영상을 YOLO + ByteTrack + Zone 판정으로 처리 | `src.main` |
| 이벤트 로그 로드 | JSONL 이벤트 파일을 읽어 대시보드에 표시 | `outputs/events.jsonl` |
| Summary 로드 | KPI 계산 결과를 읽어 표시 | `outputs/summary.json` |
| CSV 다운로드 | 이벤트 데이터를 CSV로 다운로드 | `outputs/events.csv` |
| 결과 영상 확인 | 분석 결과 mp4를 화면에 표시 | `outputs/result.mp4` |
| Zone 로드 | 위험구역 JSON을 읽어 사용 | `data/zones/sample.json` |
| Zone 검증 | polygon 좌표, 필수 필드, 좌표 범위 검증 | Zone 편집 페이지 |
| 이벤트 차트 | 타임라인, Zone별 이벤트, 타입 비율, 시간 bucket 차트 | `event_charts.py` |
| Track 차트 | 구역별 체류 시간, 활동 강도, 이동 Heatmap | `track_charts.py` |
| 룰 기반 인사이트 | 이벤트 패턴 기반 문장 생성 | `generate_insights()` |

---

# 4. 기능 외 또는 후속 작업 대상

아래 항목은 현재 UI에 존재하지만 **실제 운영 기능으로 완성된 상태는 아닙니다.**

| 항목 | 현재 상태 | 후속 작업 |
|---|---|---|
| LIVE / STANDBY 표시 | 파일 존재 여부 기반 | RTSP/Webcam 입력 연동 |
| Camera 01 표시 | 하드코딩된 문구 | 실제 `camera_id` 도입 |
| 일부 필터 UI | 데이터 필터 완전 미연결 | 기간 / Zone 필터 구현 |
| 알림 설정 | 토글 UI만 존재 | 카카오 / 문자 / 이메일 / webhook 연동 |
| 자동 재학습 | UI만 존재 | 학습 파이프라인 구현 |
| 설정 저장 | 세션 상태 중심 | `config.json` 영구 저장 |
| Track ID 안정성 | ByteTrack 기반 | ReID 또는 후처리 |
| 주간 리포트 | 일부 데모성 표시 | 날짜별 데이터 저장 구조 |

---

# 5. 차트 API 정리

차트 함수는 Streamlit 화면에서 바로 사용할 수 있도록 `matplotlib.figure.Figure` 객체를 반환합니다.

## 이벤트 차트

**파일 위치**

```text
src/visualization/event_charts.py
```

| 함수 | 설명 |
|---|---|
| `make_timeline_chart()` | 영상 시간 기준 이벤트 타임라인 |
| `make_zone_bar_chart()` | Zone별 이벤트 수 |
| `make_event_type_pie_chart()` | 이벤트 타입 비율 |
| `make_hourly_line_chart()` | 시간 bucket별 이벤트 추이 |
| `make_time_bucket_chart()` | 시간 bucket별 이벤트 막대 |
| `make_dwell_histogram()` | 체류 시간 분포 |

---

## Track 차트

**파일 위치**

```text
src/visualization/track_charts.py
```

| 함수 | 설명 |
|---|---|
| `make_zone_donut_chart()` | 특정 Track ID의 구역별 체류 시간 |
| `make_activity_heatmap()` | 특정 Track ID의 시간대별 활동 강도 |
| `make_movement_heatmap()` | 특정 Track ID의 이동 좌표 분포 |

---

# 6. 충돌 해결 내용

`main` 브랜치 최신 변경사항을 현재 브랜치에 반영하는 과정에서 아래 파일에 충돌이 발생했습니다.

## 충돌 파일

```text
docs/dashboard_analysis.md
docs/dashboard_api.md
src/visualization/event_charts.py
src/visualization/track_charts.py
```

## 해결 기준

| 파일 | 해결 방향 |
|---|---|
| `docs/dashboard_analysis.md` | main의 문서 메타데이터 보강 내용 반영 |
| `docs/dashboard_api.md` | main의 문서 메타데이터 보강 내용 반영 |
| `src/visualization/event_charts.py` | 현재 대시보드 브랜치 구현 기준으로 정리 |
| `src/visualization/track_charts.py` | 현재 대시보드 브랜치 구현 기준으로 정리 |

차트 파일은 현재 대시보드에서 **Event 객체뿐 아니라 dict 형태 이벤트도 안정적으로 처리할 수 있도록** 기존 브랜치 쪽 구현을 기준으로 정리했습니다.

---

# 7. 테스트 확인

## 충돌 마커 제거 확인

```powershell
Get-ChildItem docs,src -Recurse -File |
Select-String -Pattern "<<<<<<<|>>>>>>>"
```

출력이 없으면 충돌 마커가 제거된 상태입니다.

---

## 차트 테스트

```powershell
.\venv\Scripts\python.exe -m pytest tests\test_charts.py -q
```

---

## 시각화 테스트

```powershell
.\venv\Scripts\python.exe -m pytest tests\test_visualization.py -q
```

---

# 8. 후속 작업 제안

| 우선순위 | 작업 |
|---|---|
| 높음 | 데모 / 하드코딩 UI 제거 |
| 높음 | 기간 필터와 Zone 필터 실제 적용 |
| 높음 | 모니터 페이지 평균 체류 시간을 실제 summary 값으로 연결 |
| 높음 | 데이터 없음 상태에서 empty state 표시 |
| 중간 | 설정값 `config.json` 저장 |
| 중간 | 이벤트 debounce / hysteresis 적용 |
| 중간 | 날짜별 output 저장 구조 추가 |
| 중간 | 이벤트 상세 보기 및 관리자 확인 처리 |
| 낮음 | 실제 알림 발송 연동 |
| 낮음 | RTSP/Webcam 실시간 입력 지원 |
| 낮음 | ReID 기반 Track ID 안정화 |

---

# 9. 정리

이번 대시보드는 **운영 완성형 시스템이 아닌, 파일 기반 MVP 분석 대시보드**입니다.

현재 목적은 다음과 같습니다.

```text
영상 업로드
→ AI 파이프라인 실행
→ 이벤트 / summary / result 산출
→ 대시보드 결과 확인
→ Zone 및 Track ID 단위 분석
```

향후 운영 버전에서는 아래 기능이 추가되어야 합니다.

- 실시간 입력
- 알림 기능
- 설정 영구 저장
- 이벤트 중복 방지
- 날짜별 데이터 관리
- ReID 기반 ID 안정화
