"""페이지 1 - 홈 대시보드"""

from __future__ import annotations

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
from dashboard_data import (
    event_get,
    get_output_status,
    get_recent_events,
    get_summary,
    get_zone_name_map,
    load_events,
    load_zones,
    resolve_path,
)

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


def render_alert(events, zone_name_map):
    last_dwell = next(
        (
            event
            for event in reversed(events)
            if event_get(event, "event_type") == "DWELL"
        ),
        None,
    )

    if not last_dwell:
        return

    zone_id = event_get(last_dwell, "zone_id", "-")
    track_id = event_get(last_dwell, "track_id", "-")
    zone_name = zone_name_map.get(str(zone_id), str(zone_id))

    st.markdown(
        f"""
        <div class="alert-toast">
            <div class="alert-icon">!</div>
            <div>
                <div class="alert-title">위험구역 장시간 체류 감지</div>
                <div class="alert-text">{zone_name} 구역에서 ID-{track_id}이 체류 중입니다.</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def run_pipeline(frames_limit):
    if not st.session_state.video_path:
        st.error("영상을 먼저 업로드하세요.")
        return

    args = [
        sys.executable,
        "-m",
        "src.main",
        "--video",
        st.session_state.video_path,
        "--zones",
        str(resolve_path(st.session_state.zones_path)),
        "--output",
        str(resolve_path(st.session_state.events_path)),
        "--csv-output",
        str(resolve_path(st.session_state.csv_path)),
        "--summary-output",
        str(resolve_path(st.session_state.summary_path)),
        "--overlay-output",
        str(resolve_path(st.session_state.result_video_path)),
        "--conf",
        str(st.session_state.conf_threshold),
    ]

    if frames_limit > 0:
        args += ["--frames-limit", str(frames_limit)]

    with st.spinner("YOLO + ByteTrack 파이프라인 처리 중..."):
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            cwd=str(ROOT_DIR),
        )

    if result.returncode == 0:
        st.session_state.pipeline_done = True
        st.success("파이프라인 완료. A/B 산출물을 다시 불러옵니다.")
        st.rerun()

    st.error("파이프라인 오류")
    with st.expander("오류 보기", expanded=True):
        st.code(" ".join(args), language="bash")
        st.code(result.stderr or result.stdout or "출력 없음")


with st.sidebar:
    brand_header()

    st.markdown("**영상 업로드**")
    uploaded = st.file_uploader(
        "영상 파일",
        type=["mp4", "avi", "mov"],
        label_visibility="collapsed",
    )

    if uploaded:
        tmp = Path(tempfile.gettempdir()) / "kidcafe" / uploaded.name
        tmp.parent.mkdir(exist_ok=True)
        tmp.write_bytes(uploaded.read())

        st.session_state.video_path = str(tmp)
        st.session_state.uploaded_video_name = uploaded.name
        st.success(uploaded.name)

    frames_limit = st.number_input("처리 프레임 수", 0, 10000, 60, 10)

    st.session_state.conf_threshold = st.slider(
        "감지 신뢰도",
        min_value=0.1,
        max_value=1.0,
        value=float(st.session_state.conf_threshold),
        step=0.05,
    )

    if st.button("파이프라인 실행", use_container_width=True):
        run_pipeline(frames_limit)

    sidebar_status()


events = load_events(st.session_state.events_path)
zones = load_zones(st.session_state.zones_path)
zone_name_map = get_zone_name_map(zones)
summary = get_summary(events, st.session_state.summary_path)
recent = get_recent_events(events, n=8)
output_status = get_output_status(
    st.session_state.events_path,
    st.session_state.csv_path,
    st.session_state.summary_path,
    st.session_state.result_video_path,
)

render_alert(events, zone_name_map)

st.markdown(
    """
    <div class="kc-pill-row">
        <div class="kc-pill">⌁ AI Powered</div>
        <div class="kc-pill kc-pill-green">⌂ Real-time Monitoring</div>
    </div>
    """,
    unsafe_allow_html=True,
)

st.markdown("# Vision AI 기반 키즈카페 안전 모니터링")
st.markdown(
    '<div class="kc-page-subtitle">A의 결과 영상과 B의 이벤트 통계를 연결한 Streamlit 대시보드</div>',
    unsafe_allow_html=True,
)

k1, k2, k3, k4 = st.columns(4, gap="large")

with k1:
    st.markdown(
        render_kpi("▣", "처리 영상 수", f"{summary['video_count']:,}", "blue", "+"),
        unsafe_allow_html=True,
    )

with k2:
    st.markdown(
        render_kpi("♙", "감지 인원 수", f"{summary['total_tracks']:,}", "green", "실시간"),
        unsafe_allow_html=True,
    )

with k3:
    st.markdown(
        render_kpi("!", "위험 이벤트 수", f"{summary['dwell_count']:,}", "warn", "+"),
        unsafe_allow_html=True,
    )

with k4:
    avg_dwell_min = summary["avg_dwell_seconds"] / 60 if summary["avg_dwell_seconds"] else 0
    avg_dwell_text = f"{avg_dwell_min:.1f}분" if avg_dwell_min else "0분"

    st.markdown(
        render_kpi("◷", "평균 체류 시간", avg_dwell_text, "blue", "-"),
        unsafe_allow_html=True,
    )

st.markdown("<br>", unsafe_allow_html=True)

left, right = st.columns([2.2, 1], gap="large")

with left:
    st.markdown('<div class="panel">', unsafe_allow_html=True)
    st.markdown('<div class="panel-title">최근 이벤트</div>', unsafe_allow_html=True)

    if recent:
        dot_map = {
            "ENTER": "dot-enter",
            "DWELL": "dot-dwell",
            "EXIT": "dot-exit",
        }

        for index, event in enumerate(recent):
            event_type = event_get(event, "event_type", "UNKNOWN")
            track_id = event_get(event, "track_id", "-")
            zone_id = event_get(event, "zone_id", "-")
            frame_number = event_get(event, "frame_number")

            zone_name = zone_name_map.get(str(zone_id), str(zone_id))
            time_text = f"F{frame_number}" if frame_number is not None else f"{index + 1}분 전"
            dot = dot_map.get(event_type, "dot-gray")

            st.markdown(
                f"""
                <div class="event-row">
                    <span class="badge badge-{event_type}">{event_type}</span>
                    <div style="flex:1;">
                        <div class="event-zone">{zone_name}</div>
                        <div class="event-id">ID-{track_id}</div>
                    </div>
                    <div class="event-time">{time_text}</div>
                    <div class="event-dot {dot}"></div>
                </div>
                """,
                unsafe_allow_html=True,
            )
    else:
        st.markdown(
            f"""
            <div style="height:260px;display:flex;align-items:center;justify-content:center;
                        color:{c["TEXT_SUB"]};font-size:17px;text-align:center;">
                이벤트 없음<br>
                영상을 업로드하고 파이프라인을 실행하세요.
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown("</div>", unsafe_allow_html=True)

with right:
    st.markdown('<div class="panel">', unsafe_allow_html=True)
    st.markdown('<div class="panel-title">시스템 상태</div>', unsafe_allow_html=True)

    result_video = output_status["result_video"]
    events_file = output_status["events"]
    csv_file = output_status["csv"]
    summary_file = output_status["summary"]

    st.markdown(
        f"""
        <div class="status-row">
            <span class="status-label">AI 모델 상태</span>
            <span class="status-ok">정상</span>
        </div>
        <div class="status-row">
            <span class="status-label">위험구역</span>
            <span class="status-cyan">{len(zones)}개 설정</span>
        </div>
        <div class="status-row">
            <span class="status-label">이벤트 로그</span>
            <span class="{'status-ok' if events_file['exists'] else 'status-label'}">
                {"생성됨" if events_file["exists"] else "대기"}
            </span>
        </div>
        <div class="status-row">
            <span class="status-label">CSV 출력</span>
            <span class="{'status-ok' if csv_file['exists'] else 'status-label'}">
                {"생성됨" if csv_file["exists"] else "대기"}
            </span>
        </div>
        <div class="status-row">
            <span class="status-label">Summary JSON</span>
            <span class="{'status-ok' if summary_file['exists'] else 'status-label'}">
                {"생성됨" if summary_file["exists"] else "대기"}
            </span>
        </div>
        <div class="status-row">
            <span class="status-label">결과 영상</span>
            <span class="{'status-ok' if result_video['exists'] else 'status-label'}">
                {"생성됨" if result_video["exists"] else "대기"}
            </span>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown("</div>", unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

st.markdown(
    f"""
    <div style="background:linear-gradient(135deg,rgba(18,187,211,.14),rgba(8,47,73,.56));
                border:1px solid rgba(18,187,211,.36);border-radius:20px;padding:24px 30px;">
        <div style="color:#F8FAFC;font-size:22px;font-weight:900;margin-bottom:10px;">데이터 연결 상태</div>
        <div style="color:#A7B4C8;font-size:16px;line-height:1.8;">
            A 산출물: events.jsonl / result.mp4 / zones.json<br>
            B 산출물: events.csv / summary.json / event_aggregator.py / charts.py<br>
            현재 홈 화면은 summary.json과 events.jsonl을 기준으로 표시됩니다.
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