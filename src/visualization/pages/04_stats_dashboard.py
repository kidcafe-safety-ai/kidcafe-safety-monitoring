"""페이지 4 - 통계 대시보드"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

CURRENT_DIR = Path(__file__).resolve().parent
VIS_DIR = CURRENT_DIR.parent
ROOT_DIR = CURRENT_DIR.parents[2]

sys.path.insert(0, str(VIS_DIR))
sys.path.insert(0, str(ROOT_DIR))

from _style import brand_header, inject_css, sidebar_status, _colors
from dashboard_data import (
    count_events_by_type,
    count_events_by_zone,
    event_get,
    events_to_dataframe,
    generate_insights,
    get_output_status,
    get_summary,
    get_zone_name_map,
    load_events,
    load_zones,
)

try:
    from src.visualization.charts import (
        make_dwell_histogram,
        make_event_type_pie_chart,
        make_hourly_line_chart,
        make_zone_bar_chart,
    )
except Exception:
    make_dwell_histogram = None
    make_event_type_pie_chart = None
    make_hourly_line_chart = None
    make_zone_bar_chart = None


st.set_page_config(page_title="통계 대시보드 · KidCafe Safety AI", page_icon="📊", layout="wide")
inject_css()

for key, val in {
    "events_path": "outputs/events.jsonl",
    "summary_path": "outputs/summary.json",
    "csv_path": "outputs/events.csv",
    "zones_path": "data/zones/sample.json",
    "result_video_path": "outputs/result.mp4",
    "theme_mode": "dark",
}.items():
    if key not in st.session_state:
        st.session_state[key] = val

c = _colors()


def render_kpi(label, value, tone, delta, icon):
    tone_map = {
        "green": ("#10B981", "rgba(16,185,129,0.14)", "rgba(16,185,129,0.35)"),
        "yellow": ("#F59E0B", "rgba(245,158,11,0.14)", "rgba(245,158,11,0.35)"),
        "cyan": ("#12BBD3", "rgba(18,187,211,0.14)", "rgba(18,187,211,0.35)"),
        "blue": ("#0EA5E9", "rgba(14,165,233,0.14)", "rgba(14,165,233,0.35)"),
        "red": ("#EF4444", "rgba(239,68,68,0.14)", "rgba(239,68,68,0.35)"),
    }
    color, bg, border = tone_map.get(tone, tone_map["blue"])

    st.markdown(
        f"""
        <div style="background:linear-gradient(135deg,{bg},#111827);border:1px solid {border};
                    border-radius:20px;padding:30px;min-height:190px;position:relative;">
            <div style="width:60px;height:60px;border-radius:16px;background:#0B1220;
                        display:flex;align-items:center;justify-content:center;
                        color:{color};font-size:28px;font-weight:800;">{icon}</div>
            <div style="position:absolute;right:30px;top:45px;color:#10D99B;font-weight:800;">{delta}</div>
            <div style="margin-top:22px;color:#A7B4C8;font-size:18px;">{label}</div>
            <div style="margin-top:8px;color:{color};font-size:42px;font-weight:900;line-height:1;">{value}</div>
            <div style="margin-top:8px;color:#A7B4C8;font-size:15px;">데이터 기준</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_zone_progress(zone_counts, zone_name_map):
    if not zone_counts:
        st.info("Zone 이벤트 데이터가 없습니다.")
        return

    max_count = max(zone_counts.values()) if zone_counts else 1
    palette = ["#EF4444", "#F59E0B", "#12BBD3", "#10B981", "#64748B"]

    for index, (zone_id, count) in enumerate(sorted(zone_counts.items(), key=lambda item: item[1], reverse=True)):
        name = zone_name_map.get(str(zone_id), str(zone_id))
        width = int((count / max_count) * 100) if max_count else 0
        color = palette[index % len(palette)]

        st.markdown(
            f"""
            <div style="margin-bottom:24px;">
                <div style="display:flex;justify-content:space-between;margin-bottom:8px;">
                    <span style="color:#F8FAFC;font-size:16px;font-weight:800;">{name}</span>
                    <span style="color:#F8FAFC;font-size:16px;font-weight:900;">{count}</span>
                </div>
                <div style="height:10px;background:#223047;border-radius:999px;overflow:hidden;">
                    <div style="height:10px;width:{width}%;background:{color};border-radius:999px;"></div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def render_event_table(df, zone_name_map):
    if df.empty:
        st.info("표시할 이벤트가 없습니다.")
        return

    df_view = df.copy()

    if "zone_id" in df_view.columns:
        df_view["zone_name"] = df_view["zone_id"].astype(str).map(zone_name_map).fillna(df_view["zone_id"])

    if "timestamp" in df_view.columns:
        df_view["timestamp"] = df_view["timestamp"].astype(str).str[:19].str.replace("T", " ", regex=False)

    if "duration_seconds" not in df_view.columns:
        df_view["duration_seconds"] = "-"

    columns = [
        column
        for column in ["timestamp", "track_id", "zone_name", "event_type", "frame_number", "duration_seconds"]
        if column in df_view.columns
    ]

    display = df_view[columns].tail(12).iloc[::-1]

    st.dataframe(
        display,
        hide_index=True,
        use_container_width=True,
        height=320,
    )

    st.download_button(
        "CSV 다운로드",
        df_view.to_csv(index=False).encode("utf-8-sig"),
        file_name="kidcafe_events.csv",
        mime="text/csv",
        use_container_width=True,
    )


with st.sidebar:
    brand_header()

    st.session_state.events_path = st.text_input("Events JSONL", st.session_state.events_path)
    st.session_state.summary_path = st.text_input("Summary JSON", st.session_state.summary_path)
    st.session_state.csv_path = st.text_input("Events CSV", st.session_state.csv_path)

    sidebar_status()


events = load_events(st.session_state.events_path)
zones = load_zones(st.session_state.zones_path)
summary = get_summary(events, st.session_state.summary_path)
df = events_to_dataframe(events)
zone_names = get_zone_name_map(zones)

type_counts = count_events_by_type(events)
zone_counts = count_events_by_zone(events)
insights = generate_insights(events)
output_status = get_output_status(
    st.session_state.events_path,
    st.session_state.csv_path,
    st.session_state.summary_path,
    st.session_state.result_video_path,
)

top_left, top_right = st.columns([2.4, 1.2])

with top_left:
    st.markdown("# 통계 대시보드")
    st.markdown(
        f'<div style="color:{c["TEXT_SUB"]};font-size:20px;margin-top:-8px;margin-bottom:26px;">'
        f"A/B 산출물 기반 이벤트 분석 리포트</div>",
        unsafe_allow_html=True,
    )

with top_right:
    f1, f2, f3 = st.columns([1, 1, 1])

    with f1:
        st.selectbox("기간", ["오늘", "이번 주", "이번 달"], label_visibility="collapsed")

    with f2:
        zone_options = ["전체"] + [zone.get("name", zone.get("zone_id", "-")) for zone in zones]
        st.selectbox("Zone", zone_options, label_visibility="collapsed")

    with f3:
        csv_data = df.to_csv(index=False).encode("utf-8-sig") if not df.empty else b""
        st.download_button("내보내기", csv_data, "kidcafe_events.csv", "text/csv", use_container_width=True)


k1, k2, k3, k4 = st.columns(4)

with k1:
    render_kpi("ENTER", f"{summary['enter_count']:,}", "green", "↗", "⌁")

with k2:
    render_kpi("DWELL", f"{summary['dwell_count']:,}", "yellow", "↗", "!")

with k3:
    render_kpi("EXIT", f"{summary['exit_count']:,}", "cyan", "↗", "✓")

with k4:
    render_kpi("Total Events", f"{summary['total_events']:,}", "blue", "이번 주", "↗")

st.markdown("<br>", unsafe_allow_html=True)

chart_left, chart_right = st.columns(2, gap="large")

with chart_left:
    st.markdown('<div class="panel">', unsafe_allow_html=True)
    st.markdown('<div class="panel-title">Zone별 이벤트 차트</div>', unsafe_allow_html=True)

    if events and make_zone_bar_chart is not None:
        try:
            fig = make_zone_bar_chart(events)
            st.pyplot(fig, use_container_width=True)
        except Exception:
            render_zone_progress(zone_counts, zone_names)
    else:
        render_zone_progress(zone_counts, zone_names)

    st.markdown("</div>", unsafe_allow_html=True)

with chart_right:
    st.markdown('<div class="panel">', unsafe_allow_html=True)
    st.markdown('<div class="panel-title">시간대별 이벤트 분포</div>', unsafe_allow_html=True)

    if events and make_hourly_line_chart is not None:
        try:
            fig = make_hourly_line_chart(events)
            st.pyplot(fig, use_container_width=True)
        except Exception:
            st.info("시간대별 차트를 표시할 수 없습니다.")
    else:
        st.info("시간대별 이벤트 데이터가 없습니다.")

    st.markdown("</div>", unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

mid_left, mid_right = st.columns([1.1, 2.3], gap="large")

with mid_left:
    st.markdown('<div class="panel">', unsafe_allow_html=True)
    st.markdown('<div class="panel-title">Zone별 이벤트 수</div>', unsafe_allow_html=True)
    render_zone_progress(zone_counts, zone_names)
    st.markdown("</div>", unsafe_allow_html=True)

with mid_right:
    st.markdown('<div class="panel">', unsafe_allow_html=True)
    st.markdown('<div class="panel-title">이벤트 상세 내역</div>', unsafe_allow_html=True)
    render_event_table(df, zone_names)
    st.markdown("</div>", unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

bottom_left, bottom_right = st.columns(2, gap="large")

with bottom_left:
    st.markdown('<div class="panel">', unsafe_allow_html=True)
    st.markdown('<div class="panel-title">이벤트 타입 비율</div>', unsafe_allow_html=True)

    if events and make_event_type_pie_chart is not None:
        try:
            fig = make_event_type_pie_chart(events)
            st.pyplot(fig, use_container_width=True)
        except Exception:
            st.bar_chart(pd.Series(type_counts))
    elif type_counts:
        st.bar_chart(pd.Series(type_counts))
    else:
        st.info("이벤트 타입 데이터가 없습니다.")

    st.markdown("</div>", unsafe_allow_html=True)

with bottom_right:
    st.markdown('<div class="panel">', unsafe_allow_html=True)
    st.markdown('<div class="panel-title">체류 시간 분포</div>', unsafe_allow_html=True)

    if events and make_dwell_histogram is not None:
        try:
            fig = make_dwell_histogram(events)
            st.pyplot(fig, use_container_width=True)
        except Exception:
            st.info("체류 시간 차트를 표시할 수 없습니다.")
    else:
        st.info("체류 시간 데이터가 없습니다.")

    st.markdown("</div>", unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

st.markdown(
    f"""
    <div style="background:linear-gradient(135deg,rgba(18,187,211,.14),rgba(8,47,73,.56));
                border:1px solid rgba(18,187,211,.36);border-radius:20px;padding:30px;">
        <div style="display:flex;gap:20px;align-items:flex-start;">
            <div style="width:60px;height:60px;border-radius:16px;background:rgba(18,187,211,.16);
                        display:flex;align-items:center;justify-content:center;color:#12BBD3;
                        font-size:30px;font-weight:900;">↗</div>
            <div>
                <div style="font-size:26px;color:#F8FAFC;font-weight:900;margin-bottom:10px;">AI 인사이트</div>
                <div style="color:#A7B4C8;font-size:17px;line-height:1.8;">
                    {"<br>".join(f"• {insight}" for insight in insights)}
                </div>
            </div>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

with st.expander("A/B 산출물 상태"):
    st.write(
        {
            key: {
                "path": str(value["path"]) if value["path"] else None,
                "exists": value["exists"],
                "size": value["size"],
                "message": value["message"],
            }
            for key, value in output_status.items()
        }
    )

st.markdown("---")
st.caption("한이음 드림업 프로젝트 2026 · KidCafe Safety AI Team")