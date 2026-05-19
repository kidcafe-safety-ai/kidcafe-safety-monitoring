# Dashboard Analysis 기준 문서

이 문서는 이벤트 로그 기반 대시보드 통계와 차트 생성 기준을 정리합니다.

---

## 1. 입력 데이터

기본 입력 파일은 다음과 같습니다.

```text
outputs/events.jsonl
```

각 줄은 하나의 Event JSON입니다.

주요 필드:

| 필드 | 설명 |
|---|---|
| `timestamp` | 영상 내 상대 시간 |
| `event_type` | `ENTER`, `DWELL`, `EXIT` |
| `track_id` | 추적 대상 ID |
| `zone_id` | 위험구역 ID |
| `bbox` | 사람 bounding box |
| `foot_point` | 사람의 발 위치 기준 좌표 |
| `frame_number` | 이벤트 발생 프레임 번호 |
| `video_source` | 입력 영상 경로 |

---

## 2. 시간 계산 기준

`timestamp`는 시스템 시간이 아니라 영상 내 상대 시간입니다.

```text
HH:MM:SS.mmm
```

예시:

```text
00:01:05.500 → 65.5초
```

timestamp 변환에 실패하면 다음 기준을 사용합니다.

```text
event_seconds = frame_number / fps
```

---

## 3. KPI 계산 기준

`summary.json`은 전체 이벤트를 요약한 파일입니다.

| KPI | 계산 기준 |
|---|---|
| `total_events` | 전체 Event 개수 |
| `enter_count` | `event_type == "ENTER"` 개수 |
| `dwell_count` | `event_type == "DWELL"` 개수 |
| `exit_count` | `event_type == "EXIT"` 개수 |
| `total_tracks` | 고유 `track_id` 개수 |
| `video_count` | 고유 `video_source` 개수 |
| `avg_dwell_seconds` | 체류 구간 평균 시간 |

예시:

```json
{
  "total_events": 127,
  "enter_count": 85,
  "dwell_count": 32,
  "exit_count": 10,
  "total_tracks": 42,
  "video_count": 3,
  "avg_dwell_seconds": 12.4
}
```

---

## 4. 체류 시간 계산 기준

체류 시간은 같은 `track_id + zone_id` 조합을 기준으로 계산합니다.

```text
ENTER 발생 시점 = 체류 시작
EXIT 발생 시점 = 체류 종료
duration_seconds = EXIT 시간 - ENTER 시간
```

예시:

```text
ENTER 00:00:01.000
EXIT  00:00:06.000

duration_seconds = 5.0
```

EXIT가 없는 경우에는 해당 `track_id + zone_id`의 마지막 이벤트까지를 체류 시간으로 계산합니다.

```text
ENTER 00:00:01.000
DWELL 00:00:04.000
EXIT 없음

duration_seconds = 3.0
```

---

## 5. 이벤트 집계 기준

| 함수 | 기준 |
|---|---|
| `count_events_by_type` | `event_type`별 이벤트 개수 |
| `count_events_by_zone` | `zone_id`별 이벤트 개수 |
| `events_per_time_bucket` | 영상 시간을 `bucket_sec` 단위로 나누어 이벤트 수 계산 |
| `get_recent_events` | 영상 시간 기준 최신 이벤트 n개 반환 |

기본 시간 버킷은 10초입니다.

```text
bucket_sec = 10
```

---

## 6. 개별 track 리포트 기준

개별 리포트는 `track_id` 기준으로 계산합니다.

| 항목 | 계산 기준 |
|---|---|
| `total_activity_seconds` | 첫 이벤트와 마지막 이벤트의 시간 차이 |
| `visited_zone_count` | 고유 `zone_id` 개수 |
| `visited_zones` | 방문한 구역 목록 |
| `movement_distance` | `foot_point` 간 유클리드 거리 합 |
| `risk_event_count` | `ENTER + DWELL` 개수 |
| `total_events` | 해당 `track_id`의 전체 이벤트 개수 |

`movement_distance`는 실제 미터 단위가 아니라 이미지 좌표 기준 이동량입니다.

---

## 7. 차트 기준

| 차트 함수 | 데이터 기준 |
|---|---|
| `make_timeline_chart` | 영상 시간별 ENTER/DWELL/EXIT 이벤트 |
| `make_zone_bar_chart` | zone_id별 이벤트 수 |
| `make_event_type_pie_chart` | event_type별 비율 |
| `make_hourly_line_chart` | 시간 버킷별 이벤트 수 |
| `make_dwell_histogram` | 체류 시간 분포 |
| `make_zone_donut_chart` | track_id별 구역 체류 시간 |
| `make_activity_heatmap` | track_id별 시간 구간 이벤트 수 |
| `make_movement_heatmap` | track_id별 foot_point 위치 분포 |

---

## 8. 인사이트 생성 기준

`generate_insights()`는 룰 기반으로 문장을 생성합니다.

현재 반영된 기준:

```text
1. 이벤트가 가장 많이 발생한 구역
2. DWELL 이벤트 비율
3. ENTER가 EXIT보다 많은 경우
4. 평균 체류 시간이 10초 이상인 경우
5. 추적 ID가 5개 이상인 경우
```

---

## 9. 출력 파일

```text
outputs/events.csv
outputs/summary.json
```

| 파일 | 용도 |
|---|---|
| `outputs/events.csv` | 이벤트 테이블 표시 및 다운로드 |
| `outputs/summary.json` | KPI 카드 표시 |

---

## 10. 한계

현재 분석 기준에는 다음 한계가 있습니다.

```text
1. track_id가 바뀌면 같은 대상이어도 다른 ID로 계산될 수 있음
2. 이동 거리는 실제 거리(m)가 아니라 이미지 좌표 기준 거리임
3. 이벤트 품질은 Detection / Tracking / EventManager 성능에 의존함
4. 카메라 시점이 바뀌면 foot_point 기반 비교가 어려움
```

---

## 11. 관련 문서

```text
docs/dashboard_api.md
docs/interfaces.md
docs/decisions.md
```