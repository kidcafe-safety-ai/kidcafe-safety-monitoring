"""
Streamlit 대시보드용 차트 통합 API.

실제 구현은 아래 파일로 분리되어 있다.

- event_charts.py: 이벤트/통계 차트
- track_charts.py: track_id 기준 리포트 차트

C는 이 파일에서 필요한 차트 함수를 import해서 사용하면 된다.
"""

from src.visualization.event_charts import (
    make_dwell_histogram,
    make_event_type_pie_chart,
    make_hourly_line_chart,
    make_time_bucket_chart,
    make_timeline_chart,
    make_zone_bar_chart,
)
from src.visualization.track_charts import (
    make_activity_heatmap,
    make_movement_heatmap,
    make_zone_donut_chart,
)

__all__ = [
    "make_timeline_chart",
    "make_zone_bar_chart",
    "make_event_type_pie_chart",
    "make_hourly_line_chart",
    "make_time_bucket_chart",
    "make_dwell_histogram",
    "make_zone_donut_chart",
    "make_activity_heatmap",
    "make_movement_heatmap",
]
