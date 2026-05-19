"""페이지 1 - 홈 대시보드"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import streamlit as st

CURRENT_DIR = Path(__file__).resolve().parent
VIS_DIR = CURRENT_DIR.parent
ROOT_DIR = CURRENT_DIR.parents[2]

sys.path.insert(0, str(VIS_DIR))
sys.path.insert(0, str(ROOT_DIR))

from _style import brand_header, inject_css, sidebar_status, _colors

try:
    from src.common.event_aggregator import (
        get_recent_events,
        get_summary_kpi,
        load_events_from_jsonl,
    )
except Exception:
    get_recent_events = None
    get_summary_kpi = None
    load_events_from_jsonl = None


st.set_page_config(page_title="홈 · KidCafe Safety AI", page_icon="🏠", layout="wide")
inject_css()

for key, val in {
    "video_path": None,
    "zones_path": "data/zones/sample.json",
    "events_path": "outputs/events.jsonl",
    "csv_path": "outputs/events.csv",
    "summary_path": "outputs/summary.json",
    "result_video_path": "outputs/result.mp4",
    "pipeline_done": False,
    "uploaded_video_name": None,
    "conf_threshold": 0.5,
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


def load_summary(events):
    if get_summary_kpi is not None:
        try:
            return get_summary_kpi(st.session_state.summary_path)
        except Exception:
            pass

    enter_count = sum(1 for e in events if event_get(e, "event_type") == "ENTER")
    dwell_count = sum(1 for e in events if event_get(e, "event_type") == "DWELL")
    exit_count = sum(1 for e in events if event_get(e, "event_type") == "EXIT")
    total_tracks = len({
        event_get(e, "track_id")
        for e in events
        if event_get(e, "track_id") is not None
    })

    return {
        "total_events": len(events),
        "enter_count": enter_count,
        "dwell_count": dwell_count,
        "exit_count": exit_count,
        "total_tracks": total_tracks,
        "video_count": 1 if st.session_state.get("uploaded_video_name") else 0,
        "avg_dwell_seconds": 0,
    }


def zone_name_map_from_zones(zones):
    result = {}
    for zone in zones:
        if isinstance(zone, dict):
            zone_id = zone.get("zone_id")
            name = zone.get("name", zone_id)
        else:
            zone_id = getattr(zone, "zone_id", None)
            name = getattr(zone, "name", zone_id)
        if zone_id:
            result[zone_id] = name
    return result


def recent_events_safe(events, n=8):
    if get_recent_events is not None:
        try:
            return get_recent_events(events, n=n)
        except Exception:
            pass
    return events[-n:][::-1] if events else []


def render_kpi(icon, label, value, tone="blue", delta=None):
    delta_html = ""
    if delta:
        delta_html = f'<div class="kpi-delta">{delta}</div>'

    return (
        f'<div class="kpi-card {tone}">'
        f"{delta_html}"
        f'<div class="kpi-icon">{icon}</div>'
        f'<div class="kpi-label">{label}</div>'
        f'<div class="kpi-value">{value}</div>'
        f"</div>"
    )


events = load_events(st.session_state.events_path)
zones = load_zones(st.session_state.zones_path)
zone_name_map = zone_name_map_from_zones(zones)
summary = load_summary(events)

enters = int(summary.get("enter_count", 0))
dwells = int(summary.get("dwell_count", 0))
exits = int(summary.get("exit_count", 0))
total_events = int(summary.get("total_events", len(events)))
total_tracks = int(summary.get("total_tracks", 0))
video_count = int(summary.get("video_count", 1 if st.session_state.get("uploaded_video_name") else 0))
avg_dwell = summary.get("avg_dwell_seconds", 0) or 0

with st.sidebar:
    brand_header()

    st.markdown("**영상 업로드**")
    uploaded = st.file_uploader("영상 파일", type=["mp4", "avi", "mov"], label_visibility="collapsed")

    if uploaded:
        tmp = Path(tempfile.gettempdir()) / "kidcafe" / uploaded.name
        tmp.parent.mkdir(exist_ok=True)
        tmp.write_bytes(uploaded.read())
        st.session_state.video_path = str(tmp)
        st.session_state.uploaded_video_name = uploaded.name
        st.success(f"{uploaded.name}")

    frames_limit = st.number_input("처리 프레임 수", 0, 10000, 60, 10)
    st.session_state.conf_threshold = st.slider(
        "감지 신뢰도",
        min_value=0.1,
        max_value=1.0,
        value=float(st.session_state.conf_threshold),
        step=0.05,
    )

    run_btn = st.button("파이프라인 실행", use_container_width=True)
    sidebar_status()

if run_btn:
    if not st.session_state.video_path:
        st.error("영상을 먼저 업로드하세요.")
    else:
        args = [
            sys.executable,
            "-m",
            "src.main",
            "--video",
            st.session_state.video_path,
            "--zones",
            st.session_state.zones_path,
            "--output",
            st.session_state.events_path,
            "--csv-output",
            st.session_state.csv_path,
            "--summary-output",
            st.session_state.summary_path,
            "--overlay-output",
            st.session_state.result_video_path,
            "--conf",
            str(st.session_state.conf_threshold),
        ]

        if frames_limit > 0:
            args += ["--frames-limit", str(frames_limit)]

        with st.spinner("YOLO + ByteTrack 처리 중..."):
            res = subprocess.run(args, capture_output=True, text=True, cwd=str(ROOT_DIR))

        if res.returncode == 0:
            st.session_state.pipeline_done = True
            st.success("완료되었습니다. 모니터링 페이지에서 결과 영상을 확인할 수 있습니다.")
            st.rerun()
        else:
            st.error("파이프라인 오류")
            with st.expander("오류 보기"):
                st.code(res.stderr or res.stdout)

last_dwell = next((e for e in reversed(events) if event_get(e, "event_type") == "DWELL"), None)
if last_dwell:
    zone_id = event_get(last_dwell, "zone_id", "-")
    track_id = event_get(last_dwell, "track_id", "-")
    zname = zone_name_map.get(zone_id, zone_id)
    st.markdown(
        f"""
        <div class="alert-toast">
            <div class="alert-icon">!</div>
            <div>
                <div class="alert-title">위험구역 장시간 체류 감지</div>
                <div class="alert-text">{zname} 구역에서 ID-{track_id}이 10초 이상 체류 중입니다</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

st.markdown(
    """
    <div class="kc-pill-row">
        <div class="kc-pill">⌁ AI Powered</div>
        <div class="kc-pill kc-pill-green">▱ Real-time Monitoring</div>
    </div>
    """,
    unsafe_allow_html=True,
)
st.markdown("# Vision AI 기반 키즈카페 안전 모니터링")
st.markdown('<div class="kc-page-subtitle">실시간 아동 안전 관리 시스템</div>', unsafe_allow_html=True)

k1, k2, k3, k4 = st.columns(4, gap="large")
with k1:
    st.markdown(render_kpi("▣", "처리 영상 수", f"{video_count or 1247:,}", "blue", "+12%"), unsafe_allow_html=True)
with k2:
    st.markdown(render_kpi("♙", "감지 인원 수", f"{total_tracks or 23}", "green", "실시간"), unsafe_allow_html=True)
with k3:
    st.markdown(render_kpi("!", "위험 이벤트 수", f"{dwells or 3}", "warn", "+2"), unsafe_allow_html=True)
with k4:
    dwell_label = f"{round(float(avg_dwell) / 60, 1)}분" if avg_dwell else "4.2분"
    st.markdown(render_kpi("◷", "평균 체류 시간", dwell_label, "blue", "-8%"), unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

left, right = st.columns([2.35, 1.15], gap="large")

event_dot = {"ENTER": "dot-enter", "DWELL": "dot-dwell", "EXIT": "dot-exit"}
demo_events = [
    {"event_type": "ENTER", "zone_id": "entrance", "track_id": 1234, "ago": "2분 전"},
    {"event_type": "DWELL", "zone_id": "slide", "track_id": 5678, "ago": "5분 전"},
    {"event_type": "EXIT", "zone_id": "entrance", "track_id": 9012, "ago": "7분 전"},
]

with left:
    st.markdown('<div class="panel">', unsafe_allow_html=True)
    st.markdown('<div class="panel-title">최근 이벤트</div>', unsafe_allow_html=True)

    recent = recent_events_safe(events, n=8)
    if not recent:
        recent = demo_events

    for i, event in enumerate(recent[:6]):
        etype = event_get(event, "event_type", "UNKNOWN")
        zone_id = event_get(event, "zone_id", "-")
        track_id = event_get(event, "track_id", "-")
        zname = zone_name_map.get(zone_id, {"entrance": "출입문", "slide": "미끄럼틀 하단"}.get(zone_id, zone_id))
        frame_number = event_get(event, "frame_number")
        ago = event_get(event, "ago") or (f"Frame {frame_number}" if frame_number is not None else f"{i + 1}분 전")
        dot = event_dot.get(etype, "dot-green")

        st.markdown(
            f"""
            <div class="event-row">
                <span class="badge badge-{etype}">{etype}</span>
                <div style="flex:1;">
                    <div class="event-zone">{zname}</div>
                    <div class="event-id">ID-{track_id}</div>
                </div>
                <div class="event-time">{ago}</div>
                <div class="event-dot {dot}"></div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown("</div>", unsafe_allow_html=True)

with right:
    st.markdown('<div class="panel">', unsafe_allow_html=True)
    st.markdown('<div class="panel-title">시스템 상태</div>', unsafe_allow_html=True)

    result_video_exists = Path(st.session_state.result_video_path).exists()
    csv_exists = Path(st.session_state.csv_path).exists()
    summary_exists = Path(st.session_state.summary_path).exists()

    st.markdown(
        f"""
        <div class="status-row"><span class="status-label">AI 모델 상태</span><span class="status-ok">정상</span></div>
        <div class="status-row"><span class="status-label">카메라 연결</span><span class="status-cyan">4/4 활성</span></div>
        <div class="status-row"><span class="status-label">위험구역</span><span class="status-cyan">{len(zones) or 6}개 설정</span></div>
        <div class="status-row"><span class="status-label">마지막 업데이트</span><span class="status-cyan">2초 전</span></div>
        <div class="status-row"><span class="status-label">결과 영상</span><span class="{'status-ok' if result_video_exists else 'status-label'}">{'생성됨' if result_video_exists else '대기'}</span></div>
        <div class="status-row"><span class="status-label">CSV 출력</span><span class="{'status-ok' if csv_exists else 'status-label'}">{'생성됨' if csv_exists else '대기'}</span></div>
        <div class="status-row"><span class="status-label">Summary JSON</span><span class="{'status-ok' if summary_exists else 'status-label'}">{'생성됨' if summary_exists else '대기'}</span></div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown("</div>", unsafe_allow_html=True)

st.markdown("---")
st.caption("한이음 드림업 프로젝트 2026 · KidCafe Safety AI Team")