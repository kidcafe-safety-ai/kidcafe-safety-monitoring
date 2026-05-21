# Dashboard API 사용 가이드

> **작성일**: 2026-05-18  
> **작성자**: 우민 (Dashboard/Data API 담당)  
> **관련 문서**: [`dashboard_analysis.md`](dashboard_analysis.md), [`interfaces.md`](interfaces.md), [`decisions.md`](decisions.md)

이 문서는 이벤트 로그를 대시보드에서 활용하기 위한 주요 API 사용 방법을 정리합니다.

---

## 1. 산출물

파이프라인 실행 후 생성되는 파일은 다음과 같습니다.

```text
outputs/events.jsonl
outputs/events.csv
outputs/summary.json
outputs/result.mp4
```

| 파일 | 용도 |
|---|---|
| `outputs/events.jsonl` | 이벤트 원본 로그 |
| `outputs/events.csv` | 이벤트 테이블 및 다운로드 |
| `outputs/summary.json` | KPI 카드 데이터 |
| `outputs/result.mp4` | 이벤트 시각화 결과 영상 |

---

## 2. 주요 API 파일

```text
src/common/event_aggregator.py
src/visualization/charts.py
```

| 파일 | 설명 |
|---|---|
| `event_aggregator.py` | 이벤트 로드, 집계, 리포트 데이터 생성 |
| `charts.py` | Streamlit에서 사용할 matplotlib Figure 차트 생성 |

---

## 3. 기본 사용 예시

```python
from src.common.event_aggregator import (
    load_events_from_jsonl,
    get_summary_kpi,
    get_recent_events,
    events_to_dataframe,
    generate_insights,
)

events = load_events_from_jsonl("outputs/events.jsonl")
summary = get_summary_kpi("outputs/summary.json")
recent_events = get_recent_events(events, n=10)
recent_df = events_to_dataframe(recent_events)
insights = generate_insights(events)
```

---

## 4. Event 데이터 형식

`load_events_from_jsonl()`은 `List[Event]`를 반환합니다.

주요 필드:

```text
event_id
timestamp
event_type
track_id
zone_id
bbox
foot_point
frame_number
video_source
```

`timestamp`는 영상 내 상대 시간입니다.

```text
HH:MM:SS.mmm
```

예시:

```text
00:00:08.500
```

---

## 5. KPI summary

```python
from src.common.event_aggregator import get_summary_kpi

summary = get_summary_kpi("outputs/summary.json")
```

예상 구조:

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

Streamlit 예시:

```python
import streamlit as st

col1, col2, col3, col4 = st.columns(4)

col1.metric("전체 이벤트", summary["total_events"])
col2.metric("진입", summary["enter_count"])
col3.metric("체류", summary["dwell_count"])
col4.metric("평균 체류", f'{summary["avg_dwell_seconds"]}초')
```

---

## 6. 집계 API

```python
from src.common.event_aggregator import (
    count_events_by_zone,
    count_events_by_type,
    events_per_time_bucket,
    dwell_duration_distribution,
)

zone_counts = count_events_by_zone(events)
type_counts = count_events_by_type(events)
time_df = events_per_time_bucket(events, bucket_sec=10)
dwell_df = dwell_duration_distribution(events)
```

| 함수 | 설명 |
|---|---|
| `count_events_by_zone` | 구역별 이벤트 개수 |
| `count_events_by_type` | 이벤트 타입별 개수 |
| `events_per_time_bucket` | 영상 시간 구간별 이벤트 수 |
| `dwell_duration_distribution` | `track_id + zone_id` 기준 체류 시간 |

---

## 7. 개별 track API

```python
from src.common.event_aggregator import (
    get_track_ids_in_video_time,
    get_track_summary,
    time_per_zone_by_track,
    activity_intensity_by_time_bucket,
)

track_ids = get_track_ids_in_video_time(events, start_sec=0, end_sec=3600)
track_summary = get_track_summary(events, track_id=1)
zone_times = time_per_zone_by_track(events, track_id=1)
activity_df = activity_intensity_by_time_bucket(events, track_id=1, bucket_sec=10)
```

| 함수 | 설명 |
|---|---|
| `get_track_ids_in_video_time` | 특정 시간 구간에 등장한 `track_id` 목록 |
| `get_track_summary` | 특정 `track_id`의 활동 요약 |
| `time_per_zone_by_track` | 특정 `track_id`의 구역별 체류 시간 |
| `activity_intensity_by_time_bucket` | 특정 `track_id`의 시간 구간별 이벤트 수 |

---

## 8. 차트 API

차트 함수는 모두 `matplotlib.figure.Figure` 객체를 반환합니다.

```python
import streamlit as st
from src.visualization.charts import make_timeline_chart

fig = make_timeline_chart(events)
st.pyplot(fig)
```

| 함수 | 설명 |
|---|---|
| `make_timeline_chart` | 영상 시간 기준 이벤트 타임라인 |
| `make_zone_bar_chart` | 구역별 이벤트 수 |
| `make_event_type_pie_chart` | 이벤트 타입 비율 |
| `make_hourly_line_chart` | 시간 구간별 이벤트 추이 |
| `make_time_bucket_chart` | 시간 구간별 이벤트 막대 |
| `make_dwell_histogram` | 체류 시간 분포 |
| `make_zone_donut_chart` | `track_id`별 구역 체류 시간 |
| `make_activity_heatmap` | `track_id`별 활동 강도 |
| `make_movement_heatmap` | `track_id`별 이동 좌표 분포 |

---

## 9. 화면 사용 예시

```python
import streamlit as st
from src.common.event_aggregator import (
    load_events_from_jsonl,
    get_summary_kpi,
    get_recent_events,
    events_to_dataframe,
    generate_insights,
)
from src.visualization.charts import (
    make_timeline_chart,
    make_zone_bar_chart,
    make_hourly_line_chart,
    make_dwell_histogram,
)

events = load_events_from_jsonl("outputs/events.jsonl")
summary = get_summary_kpi("outputs/summary.json")

st.video("outputs/result.mp4")

col1, col2, col3, col4 = st.columns(4)
col1.metric("전체 이벤트", summary["total_events"])
col2.metric("진입", summary["enter_count"])
col3.metric("체류", summary["dwell_count"])
col4.metric("평균 체류", f'{summary["avg_dwell_seconds"]}초')

st.pyplot(make_timeline_chart(events))
st.pyplot(make_zone_bar_chart(events))
st.pyplot(make_hourly_line_chart(events))
st.pyplot(make_dwell_histogram(events))

recent_events = get_recent_events(events, n=10)
st.dataframe(events_to_dataframe(recent_events))

for insight in generate_insights(events):
    st.info(insight)
```

---

## 10. 실행 및 테스트

파이프라인 실행:

```bash
python -m src.main --frames-limit 300 --log-level INFO
```

테스트 실행:

```bash
pytest -v
```

관련 테스트만 실행:

```bash
pytest tests/test_event_counter.py -v
pytest tests/test_dwell_analyzer.py -v
pytest tests/test_event_writer.py -v
pytest tests/test_charts.py -v
```

---

## 11. 참고

계산 기준과 한계는 아래 문서를 참고합니다.

```text
docs/dashboard_analysis.md
```