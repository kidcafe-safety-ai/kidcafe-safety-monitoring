"""공통 CSS 스타일 및 헬퍼."""

from __future__ import annotations

import streamlit as st


EVENT_COLORS = {
    "ENTER": "#10B981",
    "DWELL": "#F59E0B",
    "EXIT": "#64748B",
}


def _init():
    if "theme_mode" not in st.session_state:
        st.session_state.theme_mode = "dark"


_init()


def _colors():
    return {
        "BG_MAIN": "#070D1A",
        "BG_SIDE": "#0B1118",
        "TEXT": "#F8FAFC",
        "TEXT_SUB": "#A7B4C8",
        "PANEL": "#111827",
        "CARD": "#0B1220",
        "BORDER": "#1D3152",
        "ENTER": EVENT_COLORS["ENTER"],
        "DWELL": EVENT_COLORS["DWELL"],
        "EXIT": EVENT_COLORS["EXIT"],
        "SUCCESS": "#10B981",
        "ACCENT": "#12BBD3",
        "BLUE": "#0EA5E9",
        "WARNING": "#F59E0B",
        "DANGER": "#EF4444",
    }


def get_css() -> str:
    c = _colors()
    return f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;500;600;700;800;900\
&display=swap');

html, body,
[data-testid="stAppViewContainer"],
[data-testid="stMain"] {{
    background: {c['BG_MAIN']} !important;
    color: {c['TEXT']};
    font-family: 'Noto Sans KR', sans-serif;
}}

.main .block-container {{
    max-width: none;
    padding: 32px 42px 36px 36px;
}}

[data-testid="stSidebar"] {{
    background: {c['BG_SIDE']} !important;
    border-right: 1px solid rgba(148,163,184,0.12);
    min-width: 320px !important;
    width: 320px !important;
}}

[data-testid="stSidebar"] > div:first-child {{
    padding: 28px 20px 24px;
}}

[data-testid="stSidebar"] * {{
    color: {c['TEXT']} !important;
    font-family: 'Noto Sans KR', sans-serif;
}}

[data-testid="stSidebarNav"] {{
    padding-top: 18px;
    border-top: 1px solid rgba(148,163,184,0.12);
}}

[data-testid="stSidebarNav"] ul {{
    padding-left: 0;
}}

[data-testid="stSidebarNav"] li {{
    margin: 8px 0;
}}

[data-testid="stSidebarNav"] a {{
    min-height: 58px;
    border-radius: 14px !important;
    padding: 0 20px !important;
    background: transparent !important;
    border: 2px solid transparent;
    font-size: 19px !important;
    font-weight: 800 !important;
    transition: all 0.18s ease;
}}

[data-testid="stSidebarNav"] a:hover {{
    background: rgba(18,187,211,0.12) !important;
}}

[data-testid="stSidebarNav"] a[aria-current="page"] {{
    background: #16B8CD !important;
    color: #03111B !important;
    border: 2px solid rgba(255,255,255,0.92) !important;
    box-shadow: 0 12px 30px rgba(18,187,211,0.28);
}}

[data-testid="stSidebarNav"] a[aria-current="page"] span {{
    color: #03111B !important;
}}

h1 {{
    color: {c['TEXT']} !important;
    font-size: 40px !important;
    font-weight: 900 !important;
    letter-spacing: 0 !important;
    margin: 0 0 8px !important;
}}

h2, h3 {{
    color: {c['TEXT']} !important;
    font-weight: 900 !important;
}}

p, li, label {{
    color: {c['TEXT']};
}}

hr {{
    border-color: rgba(148,163,184,0.14) !important;
}}

.kc-brand {{
    display: flex;
    align-items: center;
    gap: 14px;
    padding: 0 4px 26px;
}}

.kc-logo {{
    width: 50px;
    height: 50px;
    border-radius: 16px;
    background: #12BBD3;
    color: #03111B;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 28px;
    font-weight: 900;
}}

.kc-brand-title {{
    color: #FFFFFF;
    font-size: 30px;
    font-weight: 900;
    line-height: 1.16;
}}

.kc-brand-sub {{
    color: {c['TEXT_SUB']};
    font-size: 15px;
    margin-top: 8px;
}}

.kc-page-subtitle {{
    color: {c['TEXT_SUB']};
    font-size: 20px;
    margin-top: -4px;
    margin-bottom: 28px;
}}

.kc-pill-row {{
    display: flex;
    gap: 14px;
    margin-bottom: 14px;
}}

.kc-pill {{
    display: inline-flex;
    align-items: center;
    gap: 8px;
    border-radius: 999px;
    padding: 7px 17px;
    background: rgba(18,187,211,0.16);
    border: 1px solid rgba(18,187,211,0.42);
    color: #14D5F0;
    font-weight: 900;
}}

.kc-pill-green {{
    background: rgba(16,185,129,0.16);
    border-color: rgba(16,185,129,0.42);
    color: #10D99B;
}}

.kpi-card {{
    min-height: 155px;
    background: linear-gradient(135deg, rgba(18,187,211,0.16), rgba(17,24,39,0.95));
    border: 1px solid rgba(18,187,211,0.36);
    border-radius: 20px;
    padding: 28px 30px;
    position: relative;
    overflow: hidden;
    box-shadow: none;
}}

.kpi-card.green {{
    background: linear-gradient(135deg, rgba(16,185,129,0.14), rgba(12,45,40,0.62));
    border-color: rgba(16,185,129,0.36);
}}

.kpi-card.warn {{
    background: linear-gradient(135deg, rgba(245,158,11,0.18), rgba(42,28,10,0.74));
    border-color: rgba(245,158,11,0.42);
}}

.kpi-card.blue {{
    background: linear-gradient(135deg, rgba(14,165,233,0.18), rgba(8,47,73,0.70));
    border-color: rgba(14,165,233,0.40);
}}

.kpi-icon {{
    width: 60px;
    height: 60px;
    border-radius: 16px;
    background: #071222;
    display: flex;
    align-items: center;
    justify-content: center;
    color: #12BBD3;
    font-size: 26px;
    margin-bottom: 20px;
}}

.kpi-label {{
    color: {c['TEXT_SUB']};
    font-size: 17px;
    font-weight: 700;
    margin-bottom: 8px;
}}

.kpi-value {{
    color: #F8FAFC;
    font-size: 40px;
    font-weight: 900;
    line-height: 1;
}}

.kpi-delta {{
    position: absolute;
    right: 28px;
    top: 30px;
    border-radius: 999px;
    padding: 6px 12px;
    background: rgba(16,185,129,0.20);
    color: #10D99B;
    font-weight: 900;
}}

.panel {{
    background: {c['PANEL']};
    border: 1px solid {c['BORDER']};
    border-radius: 20px;
    padding: 28px 30px;
    box-shadow: none;
}}

.panel-title {{
    color: #F8FAFC;
    font-size: 27px;
    font-weight: 900;
    margin-bottom: 24px;
}}

.inner-card {{
    background: {c['CARD']};
    border: 1px solid rgba(29,49,82,0.86);
    border-radius: 14px;
    padding: 18px 20px;
}}

.event-row {{
    display: flex;
    align-items: center;
    gap: 18px;
    min-height: 72px;
    padding: 13px 20px;
    background: {c['CARD']};
    border: 1px solid rgba(29,49,82,0.86);
    border-radius: 14px;
    margin-bottom: 14px;
}}

.event-zone {{
    color: #F8FAFC;
    font-size: 18px;
    font-weight: 900;
}}

.event-id,
.event-time {{
    color: {c['TEXT_SUB']};
    font-size: 16px;
}}

.event-dot {{
    width: 10px;
    height: 10px;
    border-radius: 50%;
    flex-shrink: 0;
}}

.dot-enter,
.dot-green {{
    background: #10B981;
    box-shadow: 0 0 8px #10B981;
}}

.dot-dwell,
.dot-orange {{
    background: #F59E0B;
    box-shadow: 0 0 8px #F59E0B;
}}

.dot-exit,
.dot-gray,
.dot-grey,
.dot-red {{
    background: #64748B;
    box-shadow: 0 0 8px #64748B;
}}

.badge {{
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-width: 70px;
    height: 30px;
    padding: 0 14px;
    border-radius: 999px;
    font-size: 13px;
    font-weight: 900;
    letter-spacing: 0;
}}

.badge-ENTER {{
    background: rgba(16,185,129,0.20);
    color: #10D99B;
    border: none;
}}

.badge-DWELL {{
    background: rgba(245,158,11,0.22);
    color: #F59E0B;
    border: none;
}}

.badge-EXIT {{
    background: rgba(100,116,139,0.26);
    color: #CBD5E1;
    border: none;
}}

.status-row {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    min-height: 56px;
    padding: 0 16px;
    background: {c['CARD']};
    border-radius: 14px;
    margin-bottom: 14px;
    color: {c['TEXT_SUB']};
    font-size: 17px;
    border-bottom: none;
}}

.status-label {{
    color: {c['TEXT_SUB']};
}}

.status-ok {{
    color: #10D99B;
    font-weight: 900;
}}

.status-warn {{
    color: #F59E0B;
    font-weight: 900;
}}

.status-danger {{
    color: #EF4444;
    font-weight: 900;
}}

.status-cyan {{
    color: #14D5F0;
    font-weight: 900;
}}

.sys-status {{
    position: fixed;
    left: 20px;
    bottom: 22px;
    width: 280px;
    background: #1B2940;
    border: 0;
    border-radius: 14px;
    padding: 16px 18px;
    color: #D7E2F1;
    font-size: 15px;
}}

.alert-toast {{
    position: fixed;
    top: 28px;
    right: 0;
    width: 540px;
    z-index: 9999;
    background: #211C17;
    border: 1px solid rgba(245,158,11,0.45);
    border-radius: 18px 0 0 18px;
    padding: 22px 26px;
    display: flex;
    gap: 18px;
    color: #F8FAFC;
    box-shadow: 0 24px 80px rgba(0,0,0,0.35);
}}

.alert-icon {{
    width: 44px;
    height: 44px;
    border-radius: 14px;
    background: rgba(245,158,11,0.18);
    color: #F59E0B;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 22px;
}}

.alert-title {{
    color: #F59E0B;
    font-size: 20px;
    font-weight: 900;
    margin-bottom: 8px;
}}

.alert-text {{
    color: {c['TEXT_SUB']};
    font-size: 16px;
    line-height: 1.55;
}}

.stButton > button,
.stDownloadButton > button {{
    background: #16B8CD !important;
    color: #03111B !important;
    border: none !important;
    border-radius: 14px !important;
    height: 48px;
    font-size: 16px !important;
    font-weight: 900 !important;
}}

.stButton > button:hover,
.stDownloadButton > button:hover {{
    opacity: 0.94;
    border: none !important;
}}

.stTextInput input,
.stNumberInput input,
.stSelectbox div[data-baseweb="select"] {{
    background: {c['CARD']} !important;
    border: 1px solid {c['BORDER']} !important;
    color: {c['TEXT']} !important;
    border-radius: 14px !important;
}}

.stDataFrame,
[data-testid="stDataFrame"] {{
    background: {c['PANEL']} !important;
}}

[data-testid="stMetric"] {{
    background: {c['PANEL']};
    border: 1px solid {c['BORDER']};
    border-radius: 18px;
    padding: 18px;
}}
</style>
"""


DARK_CSS = get_css()


def sidebar_status():
    c = _colors()
    st.markdown("---")
    st.markdown(
        f'<div class="sys-status">'
        f'  <div style="display:flex;align-items:center;gap:10px;margin-bottom:8px;">'
        f'    <div style="width:10px;height:10px;border-radius:50%;background:#10B981;"></div>'
        f'    <span style="font-weight:900;color:{c["TEXT"]};">시스템 정상</span>'
        f"  </div>"
        f'  <div style="color:{c["TEXT_SUB"]};font-size:14px;">AI 모델: v2.1.0</div>'
        f"</div>",
        unsafe_allow_html=True,
    )


def page_header(title: str, subtitle: str):
    st.markdown(f"# {title}")
    st.markdown(
        f'<div class="kc-page-subtitle">{subtitle}</div>',
        unsafe_allow_html=True,
    )


def brand_header():
    st.markdown(
        """
        <div class="kc-brand">
            <div class="kc-logo">⌁</div>
            <div>
                <div class="kc-brand-title">KidCafe<br>Safety AI</div>
                <div class="kc-brand-sub">Vision AI 모니터링</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def inject_css():
    """매 페이지에서 공통 CSS를 주입한다."""
    st.markdown(get_css(), unsafe_allow_html=True)
