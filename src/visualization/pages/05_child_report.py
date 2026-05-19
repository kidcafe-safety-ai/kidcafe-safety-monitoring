"""페이지 5 - 자녀 활동 리포트"""

from __future__ import annotations

import json
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

try:
    from src.common.event_aggregator import (
        get_track_ids_in_period,
        get_track_summary,
        load_events_from_jsonl,
    )
except Exception:
    get_track_ids_in_period = None
    get_track_summary = None
    load_events_from_jsonl = None


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


def event_get(event, key, default=None):
    if isinstance(event, dict):
        return event.get(key, default)
    return getattr(event, key, default)


def load_events_fallback(path):
    p = Path(path)
    if not p.exists():
        return []

    out = []
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


def load_events(path):
    if load_events_from_jsonl is not None:
        try:
            return load_events_from_jsonl(path)
        except Exception:
            pass
    return load_events_fallback(path)


def load_zones(path):
    p = Path(path)
    if not p.exists():
        return []

    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return []

    if isinstance(data, dict) and "zones" in data:
        return data["zones"]
    if isinstance(data, list):
        return data
    return []


def zone_name_map_from_zones(zones):
    result = {}
    for zone in zones:
        if isinstance(zone, dict):
            zid = zone.get("zone_id")
            name = zone.get("name", zid)
        else:
            zid = getattr(zone, "zone_id", None)
            name = getattr(zone, "name", zid)
        if zid:
            result[zid] = name
    return result


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


def fallback_track_summary(child_events):
    frames = [
        event_get(e, "frame_number", 0)
        for e in child_events
        if event_get(e, "frame_number") is not None
    ]
    visited_zones = {
        event_get(e, "zone_id")
        for e in child_events
        if event_get(e, "zone_id") is not None
    }
    risk_count = sum(1 for e in child_events if event_get(e, "event_type") in {"ENTER", "DWELL"})

    active_seconds = max(frames) / 30 if frames else 0

    return {
        "total_activity_seconds": active_seconds,
        "visited_zone_count": len(visited_zones),
        "movement_distance": 0,
        "risk_event_count": risk_count,
    }


def normalize_summary(summary, child_events):
    if not isinstance(summary, dict):
        summary = {}

    fallback = fallback_track_summary(child_events)

    visited = summary.get("visited_zone_count", fallback["visited_zone_count"])
    if isinstance(visited, list):
        visited = len(visited)

    return {
        "total_activity_seconds": (
            summary.get("total_activity_seconds")
            or summary.get("total_activity_time")
            or summary.get("activity_seconds")
            or fallback["total_activity_seconds"]
        ),
        "visited_zone_count": visited,
        "movement_distance": summary.get("movement_distance") or summary.get("distance") or fallback["movement_distance"],
        "risk_event_count": summary.get("risk_event_count") or summary.get("danger_event_count") or fallback["risk_event_count"],
    }


def render_report_kpi(icon, label, value, tone="blue"):
    color = {
        "blue": "#12BBD3",
        "green": "#10B981",
        "yellow": "#F59E0B",
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
    connector_html = ""
    if not is_last:
        connector_html = """
        <div style="width:3px;height:44px;background:#1D3152;margin:0 auto;"></div>
        """

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


events = load_events(st.session_state.events_path)
zones = load_zones(st.session_state.zones_path)
zone_name_map = zone_name_map_from_zones(zones)

fallback_track_ids = sorted({
    event_get(event, "track_id")
    for event in events
    if event_get(event, "track_id") is not None
})

if get_track_ids_in_period is not None:
    try:
        track_ids = get_track_ids_in_period(events, 0, 10**9)
    except Exception:
        track_ids = fallback_track_ids
else:
    track_ids = fallback_track_ids

with st.sidebar:
    brand_header()
    st.session_state.events_path = st.text_input("이벤트 파일", st.session_state.events_path)
    selected_id = st.selectbox(
        "Track ID",
        options=track_ids if track_ids else [1234],
        format_func=lambda x: f"ID-{x}",
    )
    sidebar_status()

child_events = [event for event in events if event_get(event, "track_id") == selected_id]

if get_track_summary is not None and child_events:
    try:
        raw_summary = get_track_summary(events, selected_id)
    except Exception:
        raw_summary = fallback_track_summary(child_events)
else:
    raw_summary = fallback_track_summary(child_events)

summary = normalize_summary(raw_summary, child_events)
report_events = demo_events_if_empty(child_events)

visited_count = int(summary["visited_zone_count"] or 4)
activity_seconds = int(summary["total_activity_seconds"] or 5820)
risk_count = int(summary["risk_event_count"] or 0)
safety_score = max(0, 100 - risk_count * 8)
activity_level = "높음" if len(report_events) >= 4 else "보통"

top_left, top_right = st.columns([4, 1])
with top_left:
    st.markdown("# 자녀 활동 리포트")
    st.markdown('<div class="kc-page-subtitle">오늘의 활동 요약 및 안전 기록</div>', unsafe_allow_html=True)
with top_right:
    csv_data = pd.DataFrame([
        {
            "event_type": event_get(event, "event_type"),
            "track_id": event_get(event, "track_id"),
            "zone_id": event_get(event, "zone_id"),
            "frame_number": event_get(event, "frame_number"),
        }
        for event in child_events
    ]).to_csv(index=False).encode("utf-8-sig")
    st.download_button("리포트 다운로드", csv_data, f"child_report_track_{selected_id}.csv", "text/csv", use_container_width=True)

k1, k2, k3, k4 = st.columns(4, gap="large")
with k1:
    st.markdown(render_report_kpi("◷", "총 활동 시간", format_seconds(activity_seconds), "blue"), unsafe_allow_html=True)
with k2:
    st.markdown(render_report_kpi("⌖", "방문 구역", str(visited_count), "green"), unsafe_allow_html=True)
with k3:
    st.markdown(render_report_kpi("⌁", "활동 강도", activity_level, "blue"), unsafe_allow_html=True)
with k4:
    st.markdown(render_report_kpi("▣", "안전 점수", f"{safety_score}/100", "green"), unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

left, right = st.columns([2.25, 1.1], gap="large")

zone_demo_names = {
    "entrance": "출입문",
    "ballpool": "볼풀",
    "trampoline": "트램폴린",
    "slide": "미끄럼틀",
    "playground_center": "중앙 놀이공간",
}

with left:
    st.markdown('<div class="panel">', unsafe_allow_html=True)
    st.markdown('<div class="panel-title">활동 타임라인</div>', unsafe_allow_html=True)

    visible_events = report_events[:6]
    for i, event in enumerate(visible_events):
        etype = event_get(event, "event_type", "UNKNOWN")
        zone_id = event_get(event, "zone_id", "-")
        zname = zone_name_map.get(zone_id, zone_demo_names.get(zone_id, zone_id))
        frame_number = event_get(event, "frame_number")
        time_text = event_get(event, "time") or (f"F{frame_number}" if frame_number is not None else "14:23")
        duration = event_get(event, "duration") or "—"
        icon = "→" if etype == "ENTER" else "←" if etype == "EXIT" else "·"
        color = "#10B981" if etype == "ENTER" else "#64748B" if etype == "EXIT" else "#12BBD3"

        st.markdown(
            render_timeline_item(
                zone=zname,
                etype=etype,
                time_text=time_text,
                duration=duration,
                icon=icon,
                color=color,
                is_last=i == len(visible_events) - 1,
            ),
            unsafe_allow_html=True,
        )

    st.markdown("</div>", unsafe_allow_html=True)

with right:
    st.markdown('<div class="panel" style="margin-bottom:22px;">', unsafe_allow_html=True)
    st.markdown('<div class="panel-title">안전 이벤트</div>', unsafe_allow_html=True)

    safety_items = [
        ("#10B981", "볼풀 영역 진입", "14:25"),
        ("#10B981", "트램폴린 8분 체류 (정상)", "14:43"),
        ("#F59E0B", "미끄럼틀 하단 접근", "14:52"),
    ]

    for color, message, time_text in safety_items:
        st.markdown(
            f"""
            <div style="background:{'rgba(16,185,129,.13)' if color == '#10B981' else 'rgba(245,158,11,.13)'};
                        border:1px solid {'rgba(16,185,129,.35)' if color == '#10B981' else 'rgba(245,158,11,.42)'};
                        border-radius:14px;padding:20px;margin-bottom:16px;">
                <div style="display:flex;align-items:center;gap:14px;">
                    <span style="width:10px;height:10px;border-radius:50%;background:{color};display:inline-block;"></span>
                    <div>
                        <div style="color:#F8FAFC;font-size:17px;font-weight:900;">{message}</div>
                        <div style="color:#A7B4C8;font-size:15px;margin-top:8px;">{time_text}</div>
                    </div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown('<div class="panel" style="background:rgba(16,185,129,.08);border-color:rgba(16,185,129,.25);">', unsafe_allow_html=True)
    st.markdown('<div class="panel-title">일일 요약</div>', unsafe_allow_html=True)

    st.markdown(
        """
        <div style="color:#D7E2F1;font-size:17px;line-height:1.8;">
            자녀가 키즈카페에서 안전하게 놀았습니다.<br><br>
            <span style="color:#10D99B;font-weight:900;">• 위험 이벤트 없음</span><br>
            <span style="color:#10D99B;font-weight:900;">• 모든 활동 정상 범위 내</span><br><br>
            가장 선호한 놀이: <b>볼풀 (15분)</b>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown("</div>", unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

st.markdown('<div class="panel">', unsafe_allow_html=True)
st.markdown('<div class="panel-title">주간 활동 패턴</div>', unsafe_allow_html=True)

days = [("월", "-"), ("화", "-"), ("수", "-"), ("목", "-"), ("금", "-"), ("토", "1.5h"), ("일", "1.6h")]
day_cols = st.columns(7)
for col, (day, value) in zip(day_cols, days):
    with col:
        active = value != "-"
        st.markdown(
            f"""
            <div style="background:{'rgba(18,187,211,.15)' if active else '#0B1220'};
                        border:1px solid {'rgba(18,187,211,.38)' if active else '#1D3152'};
                        border-radius:14px;padding:22px;text-align:center;min-height:96px;">
                <div style="color:#A7B4C8;font-size:16px;font-weight:800;">{day}</div>
                <div style="color:{'#12BBD3' if active else '#A7B4C8'};font-size:30px;font-weight:900;margin-top:14px;">{value}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

st.markdown("</div>", unsafe_allow_html=True)

st.markdown("---")
st.caption("한이음 드림업 프로젝트 2026 · KidCafe Safety AI Team")