"""
대시보드용 이벤트 분석 통합 API.

주의:
실제 구현은 역할별 모듈로 분리되어 있다.

- event_io.py: 파일 입출력
- event_time.py: 시간 처리
- event_counter.py: 이벤트 집계
- dwell_analyzer.py: 체류 분석
- track_report.py: track_id 분석
- insight_generator.py: 인사이트 생성

C는 이 파일에서 필요한 함수를 import해서 사용하면 된다.
"""

from src.common.dwell_analyzer import dwell_duration_distribution
from src.common.event_counter import (
    calculate_summary_kpi,
    count_events_by_type,
    count_events_by_zone,
    events_per_time_bucket,
    get_recent_events,
)
from src.common.event_io import (
    events_to_dataframe,
    get_summary_kpi,
    load_events_from_jsonl,
    save_events_to_csv,
    save_summary_json,
)
from src.common.event_time import filter_events_by_video_time
from src.common.insight_generator import generate_insights
from src.common.track_report import (
    activity_intensity_by_time_bucket,
    get_track_ids_in_video_time,
    get_track_summary,
    time_per_zone_by_track,
)

# 역할 문서에서 언급된 이름과 호환하기 위한 alias
filter_events_by_period = filter_events_by_video_time
activity_intensity_by_hour = activity_intensity_by_time_bucket
get_track_ids_in_period = get_track_ids_in_video_time

__all__ = [
    "load_events_from_jsonl",
    "events_to_dataframe",
    "save_events_to_csv",
    "get_summary_kpi",
    "save_summary_json",
    "calculate_summary_kpi",
    "get_recent_events",
    "count_events_by_zone",
    "count_events_by_type",
    "events_per_time_bucket",
    "dwell_duration_distribution",
    "filter_events_by_video_time",
    "filter_events_by_period",
    "get_track_summary",
    "time_per_zone_by_track",
    "activity_intensity_by_time_bucket",
    "activity_intensity_by_hour",
    "get_track_ids_in_video_time",
    "get_track_ids_in_period",
    "generate_insights",
]