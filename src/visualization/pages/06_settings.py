"""페이지 6 - 설정"""

from __future__ import annotations

import platform
import sys
from pathlib import Path

import streamlit as st

CURRENT_DIR = Path(__file__).resolve().parent
VIS_DIR = CURRENT_DIR.parent
ROOT_DIR = CURRENT_DIR.parents[2]

sys.path.insert(0, str(VIS_DIR))
sys.path.insert(0, str(ROOT_DIR))

from _style import brand_header, inject_css, sidebar_status, _colors
from dashboard_data import get_output_status, get_video_status, resolve_path

try:
    import streamlit as _streamlit_pkg
except Exception:
    _streamlit_pkg = None


st.set_page_config(page_title="설정 · KidCafe Safety AI", page_icon="⚙️", layout="wide")
inject_css()

for key, val in {
    "conf_threshold": 0.5,
    "track_stability": 0.60,
    "dwell_sec": 10,
    "alert_enter": True,
    "alert_dwell": True,
    "alert_daily": True,
    "alert_weekly": False,
    "events_path": "outputs/events.jsonl",
    "csv_path": "outputs/events.csv",
    "summary_path": "outputs/summary.json",
    "result_video_path": "outputs/result.mp4",
    "zones_path": "data/zones/sample.json",
    "theme_mode": "dark",
}.items():
    if key not in st.session_state:
        st.session_state[key] = val

c = _colors()


def render_section_header(icon, title, subtitle, tone="blue"):
    color = {
        "blue": "#12BBD3",
        "yellow": "#F59E0B",
        "green": "#10B981",
        "red": "#EF4444",
    }.get(tone, "#12BBD3")

    return f"""
    <div style="display:flex;align-items:center;gap:16px;margin-bottom:28px;">
        <div style="width:60px;height:60px;border-radius:16px;background:rgba(18,187,211,.16);
                    display:flex;align-items:center;justify-content:center;color:{color};
                    font-size:28px;font-weight:900;">{icon}</div>
        <div>
            <div style="color:#F8FAFC;font-size:27px;font-weight:900;line-height:1;">{title}</div>
            <div style="color:#A7B4C8;font-size:16px;margin-top:10px;">{subtitle}</div>
        </div>
    </div>
    """


def render_status_row(label, value, status_class="status-cyan"):
    st.markdown(
        f"""
        <div class="status-row">
            <span class="status-label">{label}</span>
            <span class="{status_class}">{value}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_file_status(label, file_status):
    exists = file_status["exists"]
    size = file_status["size"]
    message = file_status["message"]
    status_class = "status-ok" if exists else "status-label"

    render_status_row(f"{label} 상태", "존재" if exists else "없음", status_class)
    render_status_row(f"{label} 크기", message, "status-cyan" if exists else "status-label")

    return size


def clear_text_file(path_value):
    path = resolve_path(path_value)

    if path is None or not path.exists():
        return False, "파일이 없습니다."

    if path.suffix.lower() not in {".jsonl", ".csv", ".json", ".txt"}:
        return False, "텍스트 산출물만 초기화할 수 있습니다."

    path.write_text("", encoding="utf-8")
    return True, "초기화 완료"


with st.sidebar:
    brand_header()
    sidebar_status()


output_status = get_output_status(
    st.session_state.events_path,
    st.session_state.csv_path,
    st.session_state.summary_path,
    st.session_state.result_video_path,
)
result_video_status = get_video_status(st.session_state.result_video_path)

st.markdown("# 설정")
st.markdown(
    f'<div style="color:{c["TEXT_SUB"]};font-size:20px;margin-top:-8px;margin-bottom:34px;">'
    f"시스템 설정 및 A/B 산출물 경로 관리</div>",
    unsafe_allow_html=True,
)

top_left, top_right = st.columns(2, gap="large")

with top_left:
    st.markdown('<div class="panel">', unsafe_allow_html=True)
    st.markdown(
        render_section_header("▱", "AI 모델 설정", "홈/모니터링 파이프라인 실행값", "blue"),
        unsafe_allow_html=True,
    )

    st.session_state.conf_threshold = st.slider(
        f"감지 신뢰도 임계값: {st.session_state.conf_threshold:.2f}",
        0.1,
        1.0,
        float(st.session_state.conf_threshold),
        0.05,
        key="conf_threshold_slider",
    )

    st.session_state.track_stability = st.slider(
        f"추적 안정성: {st.session_state.track_stability:.2f}",
        0.1,
        1.0,
        float(st.session_state.track_stability),
        0.05,
        key="track_stability_slider",
    )

    st.session_state.dwell_sec = st.slider(
        f"위험 체류 시간 (초): {st.session_state.dwell_sec}",
        1,
        120,
        int(st.session_state.dwell_sec),
        1,
        key="dwell_sec_slider",
    )

    auto_train = st.toggle("자동 재학습", value=False, help="MVP에서는 표시용 설정입니다.")

    st.markdown(
        f"""
        <div style="background:#0B1220;border:1px solid #1D3152;border-radius:14px;padding:18px 20px;margin-top:24px;">
            <div style="color:#F8FAFC;font-size:18px;font-weight:900;">현재 실행 옵션</div>
            <div style="color:#A7B4C8;font-size:16px;margin-top:10px;">
                --conf {st.session_state.conf_threshold:.2f} / dwell {st.session_state.dwell_sec}초
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown("</div>", unsafe_allow_html=True)

with top_right:
    st.markdown('<div class="panel">', unsafe_allow_html=True)
    st.markdown(
        render_section_header("◎", "알림 설정", "위험 이벤트 알림 관리", "yellow"),
        unsafe_allow_html=True,
    )

    alerts = [
        ("alert_enter", "위험구역 진입 알림", "ENTER 이벤트 발생 시"),
        ("alert_dwell", "장시간 체류 알림", "DWELL 이벤트 발생 시"),
        ("alert_daily", "일일 리포트", "매일 오후 6시"),
        ("alert_weekly", "주간 요약", "매주 월요일"),
    ]

    for key, label, desc in alerts:
        left, right = st.columns([4, 1])

        with left:
            st.markdown(
                f"""
                <div style="background:#0B1220;border:1px solid #1D3152;border-radius:14px;
                            padding:18px 20px;margin-bottom:14px;">
                    <div style="color:#F8FAFC;font-size:19px;font-weight:900;">{label}</div>
                    <div style="color:#A7B4C8;font-size:15px;margin-top:8px;">{desc}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

        with right:
            st.session_state[key] = st.toggle(
                "",
                value=st.session_state[key],
                key=f"toggle_{key}",
                label_visibility="collapsed",
            )

    st.markdown("</div>", unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

mid_left, mid_right = st.columns(2, gap="large")

with mid_left:
    st.markdown('<div class="panel">', unsafe_allow_html=True)
    st.markdown(
        render_section_header("▤", "데이터 경로", "A/B/C가 공유하는 파일 위치", "blue"),
        unsafe_allow_html=True,
    )

    st.session_state.events_path = st.text_input("Events JSONL", value=st.session_state.events_path)
    st.session_state.csv_path = st.text_input("Events CSV", value=st.session_state.csv_path)
    st.session_state.summary_path = st.text_input("Summary JSON", value=st.session_state.summary_path)
    st.session_state.result_video_path = st.text_input("Result MP4", value=st.session_state.result_video_path)
    st.session_state.zones_path = st.text_input("Zones JSON", value=st.session_state.zones_path)

    st.markdown(
        f"""
        <div style="background:#0B1220;border:1px solid #1D3152;border-radius:14px;padding:18px 20px;margin-top:20px;">
            <div style="color:#F8FAFC;font-size:18px;font-weight:900;">경로 기준</div>
            <div style="color:#A7B4C8;font-size:15px;line-height:1.8;margin-top:10px;">
                상대 경로는 프로젝트 루트 기준으로 해석됩니다.<br>
                프로젝트 루트: {ROOT_DIR}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown("</div>", unsafe_allow_html=True)

with mid_right:
    st.markdown('<div class="panel">', unsafe_allow_html=True)
    st.markdown(
        render_section_header("▦", "산출물 상태", "A/B 결과 파일 존재 여부", "green"),
        unsafe_allow_html=True,
    )

    render_file_status("events.jsonl", output_status["events"])
    render_file_status("events.csv", output_status["csv"])
    render_file_status("summary.json", output_status["summary"])
    render_file_status("result.mp4", output_status["result_video"])

    st.markdown("<br>", unsafe_allow_html=True)

    selected_file = st.selectbox(
        "관리할 파일",
        [
            ("events.jsonl", st.session_state.events_path),
            ("events.csv", st.session_state.csv_path),
            ("summary.json", st.session_state.summary_path),
        ],
        format_func=lambda item: item[0],
    )

    selected_label, selected_path = selected_file
    selected_resolved = resolve_path(selected_path)

    col1, col2 = st.columns(2)

    with col1:
        if st.button("파일 초기화", use_container_width=True):
            ok, message = clear_text_file(selected_path)

            if ok:
                st.success(message)
                st.rerun()
            else:
                st.warning(message)

    with col2:
        if selected_resolved and selected_resolved.exists():
            st.download_button(
                "백업 다운로드",
                selected_resolved.read_bytes(),
                file_name=f"{selected_resolved.stem}_backup{selected_resolved.suffix}",
                mime="application/octet-stream",
                use_container_width=True,
            )
        else:
            st.button("백업 다운로드", disabled=True, use_container_width=True)

    st.markdown("</div>", unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

bot_left, bot_right = st.columns(2, gap="large")

with bot_left:
    st.markdown('<div class="panel">', unsafe_allow_html=True)
    st.markdown(
        render_section_header("i", "시스템 정보", "버전 및 실행 환경", "green"),
        unsafe_allow_html=True,
    )

    streamlit_version = getattr(_streamlit_pkg, "__version__", "unknown") if _streamlit_pkg else "unknown"

    system_rows = [
        ("AI 모델", "YOLOv8n + ByteTrack"),
        ("파이프라인", "A result.mp4 + B events/summary"),
        ("Python", sys.version.split()[0]),
        ("플랫폼", platform.system()),
        ("Streamlit", streamlit_version),
        ("프로젝트", "KidCafe Safety AI MVP"),
        ("결과 영상 상태", result_video_status["message"]),
    ]

    for label, value in system_rows:
        render_status_row(label, value, "status-cyan")

    st.markdown("</div>", unsafe_allow_html=True)

with bot_right:
    st.markdown('<div class="panel">', unsafe_allow_html=True)
    st.markdown(
        render_section_header("{}", "설정 요약", "현재 세션 설정값", "blue"),
        unsafe_allow_html=True,
    )

    st.code(
        f"""conf_threshold = {st.session_state.conf_threshold:.2f}
track_stability = {st.session_state.track_stability:.2f}
dwell_sec = {st.session_state.dwell_sec}
events_path = "{st.session_state.events_path}"
csv_path = "{st.session_state.csv_path}"
summary_path = "{st.session_state.summary_path}"
result_video_path = "{st.session_state.result_video_path}"
zones_path = "{st.session_state.zones_path}"
alert_enter = {st.session_state.alert_enter}
alert_dwell = {st.session_state.alert_dwell}
alert_daily = {st.session_state.alert_daily}
alert_weekly = {st.session_state.alert_weekly}""",
        language="toml",
    )

    if st.button("설정 저장", use_container_width=True):
        st.success(
            f"저장 완료: 신뢰도 {st.session_state.conf_threshold:.2f}, "
            f"체류 {st.session_state.dwell_sec}초"
        )

    st.markdown("</div>", unsafe_allow_html=True)

st.markdown("---")
st.caption("한이음 드림업 프로젝트 2026 · KidCafe Safety AI Team")