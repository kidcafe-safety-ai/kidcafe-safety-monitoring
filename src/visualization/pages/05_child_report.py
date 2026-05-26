"""페이지 5 - 자녀 활동 리포트"""

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
    event_get,
    events_to_dataframe,
    get_track_ids,
    get_track_summary,
    get_zone_name_map,
    load_events,
    load_zones,
    time_per_zone_by_track,
)

try:
    from src.visualization.charts import (
        make_activity_heatmap,
        make_movement_heatmap,
        make_zone_donut_chart,
    )
except Exception:
    make_activity_heatmap = None
    make_movement_heatmap = None
    make_zone_donut_chart = None


st.set_page_config(page_title="자녀 활동 리포트 · KidCafe Safety AI", page_icon="📄", layout="wide")
inject_css()

for key, val in {
    "events_path": "outputs/events.jsonl",
    "zones_path": "data/zones/sample.json",
    "theme_mode": "dark",
}.items():
    if key not in st.session_state:
        st.session_state[key] = val

c = _colors()


def format_seconds(seconds):
    seconds = int(seconds or 0)
    minutes = seconds // 60
    hours = minutes // 60
    remain_min = minutes % 60

    if hours:
        return f"{hours}시간 {remain_min}분"
    if minutes:
        return f"{minutes}분"
    return f"{seconds}초"


def render_report_kpi(icon, label, value, tone="blue"):
    color = {
        "blue": "#12BBD3",
        "green": "#10B981",
        "yellow": "#F59E0B",
        "red": "#EF4444",
    }.get(tone, "#12BBD3")

    return f"""
    <div class="panel" style="min-height:130px;">
        <div style="display:flex;align-items:center;gap:16px;">
            <div style="width:48px;height:48px;border-radius:14px;background:rgba(18,187,211,.16);
                        display:flex;align-items:center;justify-content:center;color:{color};font-size:24px;">{icon}</div>
            <div>
                <div style="color:#A7B4C8;font-size:16px;font-weight:700;">{label}</div>
                <div style="color:#F8FAFC;font-size:38px;font-weight:900;margin-top:12px;line-height:1;">{value}</div>
            </div>
        </div>
    </div>
    """


def demo_events_if_empty(child_events):
    if child_events:
        return child_events

    return [
        {"event_type": "ENTER", "zone_id": "entrance", "track_id": 1234, "time": "14:23", "duration": "2분"},
        {"event_type": "DWELL", "zone_id": "ballpool", "track_id": 1234, "time": "14:25", "duration": "15분"},
        {"event_type": "DWELL", "zone_id": "trampoline", "track_id": 1234, "time": "14:40", "duration": "8분"},
        {"event_type": "DWELL", "zone_id": "slide", "track_id": 1234, "time": "14:48", "duration": "12분"},
        {"event_type": "EXIT", "zone_id": "entrance", "track_id": 1234, "time": "15:00", "duration": "1분"},
    ]


def render_timeline_item(zone, etype, time_text, duration, icon, color, is_last):
    connector_html = (
        ""
        if is_last
        else '<div style="width:3px;height:44px;background:#1D3152;margin:0 auto;"></div>'
    )

    return f"""
    <div style="display:grid;grid-template-columns:54px 1fr;gap:18px;align-items:start;">
        <div style="display:flex;flex-direction:column;align-items:center;">
            <div style="width:50px;height:50px;border-radius:50%;background:rgba(18,187,211,.24);
                        display:flex;align-items:center;justify-content:center;color:{color};
                        font-size:20px;font-weight:900;">{icon}</div>
            {connector_html}
        </div>
        <div style="background:#0B1220;border:1px solid #1D3152;border-radius:14px;
                    padding:20px 22px;margin-bottom:14px;display:flex;justify-content:space-between;">
            <div>
                <div style="color:#F8FAFC;font-size:20px;font-weight:900;">{zone}</div>
                <div style="color:#A7B4C8;font-size:17px;margin-top:8px;">{etype}</div>
            </div>
            <div style="text-align:right;">
                <div style="color:#F8FAFC;font-size:16px;font-weight:900;">{time_text}</div>
                <div style="color:#A7B4C8;font-size:15px;margin-top:8px;">{duration}</div>
            </div>
        </div>
    </div>
    """


def render_safety_event(message, time_text, tone="green"):
    color = {
        "green": "#10B981",
        "yellow": "#F59E0B",
        "red": "#EF4444",
        "gray": "#64748B",
    }.get(tone, "#10B981")

    bg = {
        "green": "rgba(16,185,129,.12)",
        "yellow": "rgba(245,158,11,.12)",
        "red": "rgba(239,68,68,.12)",
        "gray": "rgba(100,116,139,.12)",
    }.get(tone, "rgba(16,185,129,.12)")

    border = {
        "green": "rgba(16,185,129,.42)",
        "yellow": "rgba(245,158,11,.42)",
        "red": "rgba(239,68,68,.42)",
        "gray": "rgba(100,116,139,.42)",
    }.get(tone, "rgba(16,185,129,.42)")

    st.markdown(
        f"""
        <div style="background:{bg};border:1px solid {border};border-radius:14px;padding:20px;margin-bottom:16px;">
            <div style="display:flex;gap:14px;align-items:flex-start;">
                <div style="width:10px;height:10px;border-radius:50%;background:{color};margin-top:8px;"></div>
                <div>
                    <div style="color:#F8FAFC;font-size:18px;font-weight:900;">{message}</div>
                    <div style="color:#A7B4C8;font-size:15px;margin-top:8px;">{time_text}</div>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_weekly_pattern(total_seconds):
    weekend_hours = max(float(total_seconds or 0) / 3600, 0)

    days = [
        ("월", "-"),
        ("화", "-"),
        ("수", "-"),
        ("목", "-"),
        ("금", "-"),
        ("토", f"{weekend_hours:.1f}h" if weekend_hours else "-"),
        ("일", f"{weekend_hours + 0.1:.1f}h" if weekend_hours else "-"),
    ]

    cols = st.columns(7)

    for index, (day, value) in enumerate(days):
        active = value != "-"
        with cols[index]:
            st.markdown(
                f"""
                <div style="background:{'rgba(18,187,211,.16)' if active else '#0B1220'};
                            border:1px solid {'rgba(18,187,211,.42)' if active else '#1D3152'};
                            border-radius:14px;padding:22px 10px;text-align:center;">
                    <div style="color:#A7B4C8;font-size:16px;">{day}</div>
                    <div style="color:{'#12BBD3' if active else '#A7B4C8'};
                                font-size:28px;font-weight:900;margin-top:18px;">{value}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )


events = load_events(st.session_state.events_path)
zones = load_zones(st.session_state.zones_path)
zone_name_map = get_zone_name_map(zones)
track_ids = get_track_ids(events)

with st.sidebar:
    brand_header()

    st.session_state.events_path = st.text_input("이벤트 파일", st.session_state.events_path)
    st.markdown("**아동 선택**")

    selected_id = st.selectbox(
        "Track ID",
        options=track_ids if track_ids else [1234],
        format_func=lambda x: f"ID-{x}",
        label_visibility="collapsed",
    )

    sidebar_status()


child_events = [
    event
    for event in events
    if event_get(event, "track_id") == selected_id
]

report_events = demo_events_if_empty(child_events)
summary = get_track_summary(events, selected_id)

risk_event_count = int(summary.get("risk_event_count", 0) or 0)
safety_score = max(0, 100 - risk_event_count * 8)
activity_count = len(child_events)
activity_level = "높음" if activity_count >= 10 else "보통" if activity_count >= 4 else "낮음"

st.markdown("# 자녀 활동 리포트")
st.markdown(
    f'<div style="color:{c["TEXT_SUB"]};font-size:20px;margin-top:-8px;margin-bottom:26px;">'
    f"ID-{selected_id} · 오늘의 활동 요약 및 안전 기록</div>",
    unsafe_allow_html=True,
)

top_left, top_right = st.columns([3, 1])

with top_right:
    df_child = events_to_dataframe(child_events)

    st.download_button(
        "리포트 다운로드",
        df_child.to_csv(index=False).encode("utf-8-sig"),
        file_name=f"child_report_track_{selected_id}.csv",
        mime="text/csv",
        use_container_width=True,
        disabled=df_child.empty,
    )

k1, k2, k3, k4 = st.columns(4, gap="large")

with k1:
    st.markdown(
        render_report_kpi("◷", "총 활동 시간", format_seconds(summary["total_activity_seconds"]), "blue"),
        unsafe_allow_html=True,
    )

with k2:
    st.markdown(
        render_report_kpi("⌖", "방문 구역", str(summary["visited_zone_count"]), "green"),
        unsafe_allow_html=True,
    )

with k3:
    st.markdown(
        render_report_kpi("⌁", "활동 강도", activity_level, "blue"),
        unsafe_allow_html=True,
    )

with k4:
    score_tone = "green" if safety_score >= 80 else "yellow" if safety_score >= 60 else "red"
    st.markdown(
        render_report_kpi("□", "안전 점수", f"{safety_score}/100", score_tone),
        unsafe_allow_html=True,
    )

st.markdown("<br>", unsafe_allow_html=True)

chart_left, chart_right = st.columns(2, gap="large")

with chart_left:
    st.markdown('<div class="panel">', unsafe_allow_html=True)
    st.markdown('<div class="panel-title">시설별 체류 시간</div>', unsafe_allow_html=True)

    if child_events and make_zone_donut_chart is not None:
        try:
            fig = make_zone_donut_chart(events, selected_id)
            st.pyplot(fig, use_container_width=True)
        except Exception:
            zone_times = time_per_zone_by_track(events, selected_id)
            if zone_times:
                df_zone = pd.DataFrame(
                    {
                        "구역": [zone_name_map.get(str(zone), str(zone)) for zone in zone_times.keys()],
                        "시간": list(zone_times.values()),
                    }
                )
                st.bar_chart(df_zone.set_index("구역"))
            else:
                st.info("시설별 체류 데이터가 없습니다.")
    else:
        zone_times = time_per_zone_by_track(events, selected_id)
        if zone_times:
            df_zone = pd.DataFrame(
                {
                    "구역": [zone_name_map.get(str(zone), str(zone)) for zone in zone_times.keys()],
                    "시간": list(zone_times.values()),
                }
            )
            st.bar_chart(df_zone.set_index("구역"))
        else:
            st.info("시설별 체류 데이터가 없습니다.")

    st.markdown("</div>", unsafe_allow_html=True)

with chart_right:
    st.markdown('<div class="panel">', unsafe_allow_html=True)
    st.markdown('<div class="panel-title">시간대별 활동 강도</div>', unsafe_allow_html=True)

    if child_events and make_activity_heatmap is not None:
        try:
            fig = make_activity_heatmap(events, selected_id)
            st.pyplot(fig, use_container_width=True)
        except Exception:
            df_child = events_to_dataframe(child_events)
            if not df_child.empty and "event_type" in df_child.columns:
                st.bar_chart(df_child["event_type"].value_counts())
            else:
                st.info("활동 강도 데이터가 없습니다.")
    else:
        df_child = events_to_dataframe(child_events)
        if not df_child.empty and "event_type" in df_child.columns:
            st.bar_chart(df_child["event_type"].value_counts())
        else:
            st.info("활동 강도 데이터가 없습니다.")

    st.markdown("</div>", unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

left, right = st.columns([2.2, 1], gap="large")

with left:
    st.markdown('<div class="panel">', unsafe_allow_html=True)
    st.markdown('<div class="panel-title">활동 타임라인</div>', unsafe_allow_html=True)

    visible_events = report_events[:8]

    for index, event in enumerate(visible_events):
        etype = event_get(event, "event_type", "UNKNOWN")
        zone_id = event_get(event, "zone_id", "-")
        frame_number = event_get(event, "frame_number")

        zone = zone_name_map.get(
            str(zone_id),
            {
                "entrance": "출입문",
                "ballpool": "볼풀",
                "trampoline": "트램폴린",
                "slide": "미끄럼틀",
            }.get(str(zone_id), str(zone_id)),
        )

        time_text = event_get(event, "time", f"F{frame_number}" if frame_number is not None else "-")
        duration = event_get(event, "duration", "-")

        if etype == "ENTER":
            icon, color = "→", "#10B981"
        elif etype == "DWELL":
            icon, color = "•", "#12BBD3"
        elif etype == "EXIT":
            icon, color = "←", "#64748B"
        else:
            icon, color = "•", "#A7B4C8"

        st.markdown(
            render_timeline_item(
                zone,
                etype,
                time_text,
                duration,
                icon,
                color,
                index == len(visible_events) - 1,
            ),
            unsafe_allow_html=True,
        )

    st.markdown("</div>", unsafe_allow_html=True)

with right:
    st.markdown('<div class="panel">', unsafe_allow_html=True)
    st.markdown('<div class="panel-title">안전 이벤트</div>', unsafe_allow_html=True)

    risk_events = [
        event
        for event in report_events
        if event_get(event, "event_type") in {"ENTER", "DWELL"}
    ][:5]

    if risk_events:
        for event in risk_events:
            etype = event_get(event, "event_type", "UNKNOWN")
            zone_id = event_get(event, "zone_id", "-")
            zone = zone_name_map.get(
                str(zone_id),
                {
                    "entrance": "출입문",
                    "ballpool": "볼풀",
                    "trampoline": "트램폴린",
                    "slide": "미끄럼틀",
                }.get(str(zone_id), str(zone_id)),
            )

            time_text = event_get(event, "time", f"F{event_get(event, 'frame_number', '-')}")
            tone = "yellow" if etype == "DWELL" else "green"
            message = f"{zone} {'장시간 체류' if etype == 'DWELL' else '영역 진입'}"

            render_safety_event(message, time_text, tone)
    else:
        render_safety_event("위험 이벤트 없음", "오늘", "green")

    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    st.markdown(
        f"""
        <div style="background:rgba(16,185,129,.10);border:1px solid rgba(16,185,129,.35);
                    border-radius:20px;padding:28px;">
            <div style="color:#F8FAFC;font-size:26px;font-weight:900;margin-bottom:18px;">일일 요약</div>
            <div style="color:#A7B4C8;font-size:17px;line-height:1.8;">
                {"자녀가 키즈카페에서 안정적으로 활동했습니다." if safety_score >= 80 else "주의 이벤트가 있어 보호자 확인이 필요합니다."}
            </div>
            <div style="color:#10D99B;font-size:17px;font-weight:800;margin-top:16px;">• 안전 점수 {safety_score}/100</div>
            <div style="color:#10D99B;font-size:17px;font-weight:800;margin-top:8px;">• 총 {summary["visited_zone_count"]}개 구역 방문</div>
            <div style="color:#F8FAFC;font-size:17px;margin-top:16px;">총 활동 시간: {format_seconds(summary["total_activity_seconds"])}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

st.markdown("<br>", unsafe_allow_html=True)

st.markdown('<div class="panel">', unsafe_allow_html=True)
st.markdown('<div class="panel-title">주간 활동 패턴</div>', unsafe_allow_html=True)
render_weekly_pattern(summary["total_activity_seconds"])
st.markdown("</div>", unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

st.markdown('<div class="panel">', unsafe_allow_html=True)
st.markdown('<div class="panel-title">이동 경로 히트맵</div>', unsafe_allow_html=True)

if child_events and make_movement_heatmap is not None:
    try:
        fig = make_movement_heatmap(events, selected_id, width=1280, height=720)
        st.pyplot(fig, use_container_width=True)
    except Exception:
        st.info("이동 좌표 데이터가 부족해 히트맵을 표시할 수 없습니다.")
else:
    st.info("이동 좌표 데이터가 부족해 히트맵을 표시할 수 없습니다.")

st.markdown("</div>", unsafe_allow_html=True)

st.markdown("---")
st.caption("한이음 드림업 프로젝트 2026 · KidCafe Safety AI Team")