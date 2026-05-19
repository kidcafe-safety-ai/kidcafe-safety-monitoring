"""공통 CSS 스타일 및 헬퍼."""

import streamlit as st


# ── 세션 초기화 ───────────────────────────────────────────────────────────────
def _init():
    if "theme_mode" not in st.session_state:
        st.session_state.theme_mode = "dark"

_init()


# ── 테마별 색상 (함수로 호출해서 항상 최신 테마 반영) ────────────────────────
def _colors():
    dark = st.session_state.get("theme_mode", "dark") == "dark"
    return {
        "BG_MAIN":   "#0b1120" if dark else "#f3f6fb",
        "BG_SIDE":   "#08101d" if dark else "#ffffff",
        "TEXT":      "#e2e8f0" if dark else "#111827",
        "TEXT_SUB":  "#8896a8" if dark else "#475569",
        "PANEL":     "#111827" if dark else "#ffffff",
        "CARD":      "#141b2d" if dark else "#ffffff",
        "BORDER":    "#1e2d45" if dark else "#dbe4f0",
    }


# ── CSS 생성 (매 페이지 로드마다 현재 테마로 생성) ───────────────────────────
def get_css() -> str:
    c = _colors()
    return f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@300;400;500;700&family=Inter:wght@300;400;500;600;700&display=swap');

html, body,
[data-testid="stAppViewContainer"],
[data-testid="stMain"] {{
    background-color: {c['BG_MAIN']} !important;
    color: {c['TEXT']};
    font-family: 'Noto Sans KR', 'Inter', sans-serif;
}}
.main .block-container {{
    padding-top: 2rem;
    padding-left: 2rem;
    padding-right: 2rem;
}}

/* 사이드바 */
[data-testid="stSidebar"] {{
    background: {c['BG_SIDE']} !important;
    border-right: 1px solid {c['BORDER']};
    min-width: 260px !important;
}}
[data-testid="stSidebar"] * {{ color: {c['TEXT']} !important; }}
[data-testid="stSidebarNav"] {{ padding-top: 16px; }}
[data-testid="stSidebarNav"] li {{ margin-bottom: 8px; }}
[data-testid="stSidebarNav"] a {{
    border-radius: 14px !important;
    padding: 12px 16px !important;
    background: transparent !important;
    transition: all 0.2s ease;
    border: 1px solid transparent;
    font-size: 15px !important;
    font-weight: 600 !important;
}}
[data-testid="stSidebarNav"] a:hover {{
    background: rgba(0,210,200,0.08) !important;
    border: 1px solid rgba(0,210,200,0.15);
}}
[data-testid="stSidebarNav"] a[aria-current="page"] {{
    background: linear-gradient(90deg,#18d5e2,#1eb6d4) !important;
    color: #08101d !important;
    border-radius: 14px !important;
    font-weight: 700 !important;
    border: none !important;
    box-shadow: 0 4px 16px rgba(24,213,226,0.25);
}}
[data-testid="stSidebarNav"] a[aria-current="page"] span {{ color: #08101d !important; }}
[data-testid="stSidebarNav"] span {{ font-size: 15px !important; }}

/* KPI 카드 */
.kpi-card {{
    background: {c['CARD']};
    border: 1px solid {c['BORDER']};
    border-radius: 18px;
    padding: 22px 24px;
    position: relative;
    overflow: hidden;
}}
.kpi-label {{ font-size: 13px; color: {c['TEXT_SUB']}; margin-bottom: 6px; }}
.kpi-value {{ font-size: 34px; font-weight: 700; color: {c['TEXT']}; line-height: 1.1; }}

/* 패널 */
.panel {{
    background: {c['PANEL']};
    border: 1px solid {c['BORDER']};
    border-radius: 20px;
    padding: 22px;
    box-shadow: 0 4px 20px rgba(0,0,0,0.06);
}}
.panel-title {{ font-size: 17px; font-weight: 700; color: {c['TEXT']}; margin-bottom: 18px; }}

/* 이벤트 배지 */
.badge {{
    display: inline-block;
    font-size: 11px; font-weight: 700;
    padding: 3px 10px; border-radius: 6px;
    letter-spacing: 0.04em;
}}
.badge-ENTER {{ background: rgba(0,200,120,0.2);  color:#00c878; border:1px solid rgba(0,200,120,0.3); }}
.badge-DWELL {{ background: rgba(255,170,0,0.2);  color:#ffaa00; border:1px solid rgba(255,170,0,0.3); }}
.badge-EXIT  {{ background: rgba(255,80,80,0.2);  color:#ff5050; border:1px solid rgba(255,80,80,0.3); }}

/* 이벤트 로우 */
.event-row {{
    display: flex; align-items: center; gap: 12px;
    padding: 14px;
    background: {c['CARD']};
    border: 1px solid {c['BORDER']};
    border-radius: 14px;
    margin-bottom: 10px;
}}
.event-zone {{ font-size: 14px; font-weight: 600; color: {c['TEXT']}; flex: 1; }}
.event-id, .event-time {{ font-size: 12px; color: {c['TEXT_SUB']}; }}
.event-dot {{ width:8px; height:8px; border-radius:50%; flex-shrink:0; }}
.dot-green  {{ background:#00c878; box-shadow:0 0 6px #00c878; }}
.dot-orange {{ background:#ffaa00; box-shadow:0 0 6px #ffaa00; }}
.dot-red    {{ background:#ff5050; box-shadow:0 0 6px #ff5050; }}

/* 상태 행 */
.status-row {{
    display: flex; justify-content: space-between; align-items: center;
    padding: 12px 0; border-bottom: 1px solid {c['BORDER']}; font-size: 13px;
}}
.status-row:last-child {{ border-bottom: none; }}
.status-label {{ color: {c['TEXT_SUB']}; }}
.status-ok   {{ color:#00c878; font-weight:600; }}
.status-warn {{ color:#ffaa00; font-weight:600; }}
.status-cyan {{ color:#00d2c8; font-weight:600; }}

/* 시스템 상태 카드 */
.sys-status {{
    background: {c['CARD']};
    border: 1px solid {c['BORDER']};
    border-radius: 16px;
    padding: 14px 16px;
    font-size: 13px;
    margin-top: 16px;
}}

/* 버튼 */
.stButton > button {{
    background: linear-gradient(90deg,#18d5e2,#1eb6d4) !important;
    color: #08101d !important;
    border: none !important;
    border-radius: 12px !important;
    font-weight: 700 !important;
    font-size: 14px !important;
    height: 44px;
}}
.stButton > button:hover {{ opacity: 0.9; }}

/* 입력창 */
.stTextInput > div > div > input,
.stSelectbox > div > div,
.stNumberInput > div > div > input {{
    background: {c['PANEL']} !important;
    border: 1px solid {c['BORDER']} !important;
    color: {c['TEXT']} !important;
    border-radius: 12px !important;
}}
.stDataFrame {{ background: {c['CARD']} !important; }}
hr          {{ border-color: {c['BORDER']} !important; }}
h1, h2, h3  {{ color: {c['TEXT']} !important; }}
p, li       {{ color: {c['TEXT']}; }}
</style>
"""

# ── 하위 호환: 기존 코드에서 DARK_CSS 직접 임포트하는 경우 대비 ───────────────
DARK_CSS = get_css()


# ── 공통 사이드바 하단 ────────────────────────────────────────────────────────
def sidebar_status():
    c = _colors()
    st.markdown("---")

    # 테마 토글 버튼
    is_dark = st.session_state.get("theme_mode", "dark") == "dark"
    label   = "☀️ 라이트 모드" if is_dark else "🌙 다크 모드"

    if st.button(label, use_container_width=True, key="__theme_toggle__"):
        st.session_state.theme_mode = "light" if is_dark else "dark"
        st.rerun()

    # 시스템 상태 카드 — st.markdown 으로 단순하게
    st.markdown(
        f'<div class="sys-status">'
        f'  <div style="display:flex;align-items:center;gap:10px;margin-bottom:6px;">'
        f'    <div style="width:10px;height:10px;border-radius:50%;'
        f'         background:#00c878;box-shadow:0 0 8px #00c878;"></div>'
        f'    <span style="font-weight:700;color:{c["TEXT"]};font-size:15px;">시스템 정상</span>'
        f'  </div>'
        f'  <div style="color:{c["TEXT_SUB"]};font-size:13px;">AI 모델: v2.1.0</div>'
        f'</div>',
        unsafe_allow_html=True,
    )


# ── 페이지 공통 헤더 ──────────────────────────────────────────────────────────
def page_header(title: str, subtitle: str):
    c = _colors()
    st.markdown(f"# {title}")
    st.markdown(
        f'<p style="color:{c["TEXT_SUB"]};margin-top:-12px;'
        f'margin-bottom:20px;font-size:15px;">{subtitle}</p>',
        unsafe_allow_html=True,
    )


# ── 각 페이지 최상단에서 호출할 CSS 주입 함수 ────────────────────────────────
def inject_css():
    """매 페이지에서 st.markdown(get_css(), ...) 대신 이걸 호출."""
    st.markdown(get_css(), unsafe_allow_html=True)