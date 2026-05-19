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

try:
    import streamlit as _streamlit_pkg
except Exception:
    _streamlit_pkg = None


st.set_page_config(page_title="설정 · KidCafe Safety AI", page_icon="⚙️", layout="wide")
inject_css()

for key, val in {
    "conf_threshold": 0.75,
    "track_stability": 0.60,
    "dwell_sec": 10,
    "alert_enter": True,
    "alert_dwell": True,
    "alert_daily": True,
    "alert_weekly": False,
    "auto_retrain": True,
    "developer_mode": False,
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


def section_header(icon, title, subtitle, tone="#12BBD3"):
    st.markdown(
        f"""
        <div style="display:flex;align-items:center;gap:18px;margin-bottom:26px;">
            <div style="width:60px;height:60px;border-radius:16px;background:{tone}22;
                        display:flex;align-items:center;justify-content:center;color:{tone};
                        font-size:28px;font-weight:900;">{icon}</div>
            <div>
                <div style="font-size:27px;font-weight:900;color:#F8FAFC;">{title}</div>
                <div style="font-size:17px;color:#A7B4C8;margin-top:6px;">{subtitle}</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def card_text(title, desc, danger=False):
    border = "rgba(239,68,68,.45)" if danger else "#1D3152"
    bg = "rgba(239,68,68,.10)" if danger else "#0B1220"
    color = "#EF4444" if danger else "#F8FAFC"

    st.markdown(
        f"""
        <div style="background:{bg};border:1px solid {border};border-radius:14px;
                    padding:18px 20px;margin-bottom:14px;">
            <div style="color:{color};font-size:19px;font-weight:900;">{title}</div>
            <div style="color:#A7B4C8;font-size:16px;margin-top:8px;">{desc}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def info_row(label, value):
    st.markdown(
        f"""
        <div class="status-row">
            <span class="status-label">{label}</span>
            <span style="color:#F8FAFC;font-weight:900;">{value}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


with st.sidebar:
    brand_header()
    sidebar_status()

st.markdown("# 설정")
st.markdown('<div class="kc-page-subtitle">시스템 설정 및 환경 구성</div>', unsafe_allow_html=True)

top1, top2 = st.columns(2, gap="large")

with top1:
    section_header("▱", "AI 모델 설정", "감지 임계값 및 민감도 조정", "#12BBD3")

    st.markdown(
        f'<div style="font-size:17px;color:#A7B4C8;margin-bottom:10px;">감지 신뢰도 임계값: '
        f'<b style="color:#F8FAFC;">{st.session_state.conf_threshold:.2f}</b></div>',
        unsafe_allow_html=True,
    )
    st.session_state.conf_threshold = st.slider(
        "감지 신뢰도 임계값",
        0.1,
        1.0,
        float(st.session_state.conf_threshold),
        0.05,
        label_visibility="collapsed",
    )

    st.markdown(
        f'<div style="font-size:17px;color:#A7B4C8;margin:28px 0 10px;">추적 안정성: '
        f'<b style="color:#F8FAFC;">{st.session_state.track_stability:.2f}</b></div>',
        unsafe_allow_html=True,
    )
    st.session_state.track_stability = st.slider(
        "추적 안정성",
        0.1,
        1.0,
        float(st.session_state.track_stability),
        0.05,
        label_visibility="collapsed",
    )

    st.markdown(
        f'<div style="font-size:17px;color:#A7B4C8;margin:28px 0 10px;">위험 체류 시간 (초): '
        f'<b style="color:#F8FAFC;">{st.session_state.dwell_sec}</b></div>',
        unsafe_allow_html=True,
    )
    st.session_state.dwell_sec = st.slider(
        "위험 체류 시간",
        1,
        120,
        int(st.session_state.dwell_sec),
        1,
        label_visibility="collapsed",
    )

    st.markdown("<br>", unsafe_allow_html=True)
    col_a, col_b = st.columns([5, 1])
    with col_a:
        card_text("자동 재학습", "데이터 축적 시 모델 자동 업데이트")
    with col_b:
        st.session_state.auto_retrain = st.toggle(
            "자동 재학습",
            value=st.session_state.auto_retrain,
            label_visibility="collapsed",
        )

with top2:
    section_header("◎", "알림 설정", "위험 이벤트 알림 관리", "#F59E0B")

    alerts = [
        ("alert_enter", "위험구역 진입 알림", "고위험 구역 진입 시"),
        ("alert_dwell", "장시간 체류 알림", "임계값 초과 시"),
        ("alert_daily", "일일 리포트", "매일 오후 6시"),
        ("alert_weekly", "주간 요약", "매주 월요일"),
    ]

    for key, title, desc in alerts:
        col_a, col_b = st.columns([5, 1])
        with col_a:
            card_text(title, desc)
        with col_b:
            st.session_state[key] = st.toggle(
                title,
                value=st.session_state[key],
                key=f"toggle_{key}",
                label_visibility="collapsed",
            )

st.markdown("<br>", unsafe_allow_html=True)

bottom1, bottom2 = st.columns(2, gap="large")

with bottom1:
    section_header("▤", "데이터 관리", "저장소 및 백업 설정", "#0EA5E9")

    st.markdown(
        """
        <div style="background:#0B1220;border:1px solid #1D3152;border-radius:14px;padding:18px 20px;margin-bottom:18px;">
            <div style="display:flex;justify-content:space-between;align-items:center;">
                <div style="color:#A7B4C8;font-size:17px;">영상 저장 기간</div>
                <div style="color:#F8FAFC;font-size:22px;font-weight:900;">30일</div>
            </div>
            <div style="height:10px;background:#233147;border-radius:999px;margin:18px 0 10px;overflow:hidden;">
                <div style="height:10px;width:75%;background:#12BBD3;border-radius:999px;"></div>
            </div>
            <div style="color:#A7B4C8;font-size:15px;">저장공간: 142GB / 200GB</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    card_text("데이터 내보내기", "CSV 또는 JSON 형식")
    card_text("자동 백업 설정", "클라우드 동기화")
    card_text("모든 데이터 삭제", "영구적으로 삭제됩니다", danger=True)

with bottom2:
    section_header("i", "시스템 정보", "버전 및 상태", "#10B981")

    streamlit_version = getattr(_streamlit_pkg, "__version__", "unknown") if _streamlit_pkg else "unknown"

    for label, value in [
        ("AI 모델 버전", "v2.1.0"),
        ("프론트엔드 버전", "v1.3.2"),
        ("마지막 업데이트", "2026-05-15"),
        ("총 처리 영상", "12,473"),
        ("시스템 가동시간", "47일 12시간"),
        ("Streamlit", streamlit_version),
        ("Python", sys.version.split()[0]),
        ("플랫폼", platform.system()),
    ]:
        info_row(label, value)

    dev_col, save_col = st.columns([2, 3])
    with dev_col:
        st.session_state.developer_mode = st.toggle(
            "개발자 모드",
            value=st.session_state.developer_mode,
        )
    with save_col:
        if st.button("설정 저장", use_container_width=True):
            st.success(
                f"저장되었습니다. 신뢰도 {st.session_state.conf_threshold:.2f}, "
                f"체류 {st.session_state.dwell_sec}초"
            )

st.markdown("---")
st.caption("한이음 드림업 프로젝트 2026 · KidCafe Safety AI Team")