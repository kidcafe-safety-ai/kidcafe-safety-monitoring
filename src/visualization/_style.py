"""공통 CSS 스타일 및 헬퍼."""

DARK_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@300;400;500;700&family=Inter:wght@300;400;500;600;700&display=swap');

/* ─────────────────────────────────────────────
   전체 레이아웃
───────────────────────────────────────────── */
html, body, [data-testid="stAppViewContainer"], [data-testid="stMain"] {
    background-color: #0b1120 !important;
    color: #e2e8f0;
    font-family: 'Noto Sans KR', 'Inter', sans-serif;
}

/* 메인 영역 */
.main .block-container {
    padding-top: 2rem;
    padding-left: 2rem;
    padding-right: 2rem;
}

/* ─────────────────────────────────────────────
   사이드바
───────────────────────────────────────────── */
[data-testid="stSidebar"] {
    background: #08101d !important;
    border-right: 1px solid #172235;
    min-width: 300px !important;
}

[data-testid="stSidebar"] * {
    color: #e2e8f0 !important;
}

/* 기본 streamlit 네비 숨김 */
[data-testid="stSidebarNav"] {
    padding-top: 20px;
}

/* 네비게이션 버튼 */
[data-testid="stSidebarNav"] ul {
    gap: 10px;
}

[data-testid="stSidebarNav"] li {
    margin-bottom: 10px;
}

/* 페이지 버튼 */
[data-testid="stSidebarNav"] a {
    border-radius: 16px !important;
    padding: 14px 18px !important;
    background: transparent !important;
    transition: all 0.2s ease;
    border: 1px solid transparent;
    font-size: 18px !important;
    font-weight: 600 !important;
}

/* hover */
[data-testid="stSidebarNav"] a:hover {
    background: rgba(0,210,200,0.08) !important;
    border: 1px solid rgba(0,210,200,0.15);
}

/* 선택된 메뉴 */
[data-testid="stSidebarNav"] a[aria-current="page"] {
    background: linear-gradient(90deg, #18d5e2, #1eb6d4) !important;
    color: #08101d !important;
    border-radius: 18px !important;
    font-weight: 700 !important;
    border: none !important;
    box-shadow: 0 6px 20px rgba(24,213,226,0.25);
}

/* 선택된 메뉴 글자 */
[data-testid="stSidebarNav"] a[aria-current="page"] span {
    color: #08101d !important;
}

/* 메뉴 아이콘/텍스트 정렬 */
[data-testid="stSidebarNav"] span {
    font-size: 16px !important;
}

/* ─────────────────────────────────────────────
   KPI 카드
───────────────────────────────────────────── */
.kpi-card {
    background: linear-gradient(135deg, #141b2d 0%, #1a2340 100%);
    border: 1px solid #1e2d45;
    border-radius: 18px;
    padding: 22px 24px;
    position: relative;
    overflow: hidden;
}

.kpi-card::before {
    content: '';
    position: absolute;
    top: -40px;
    right: -40px;
    width: 100px;
    height: 100px;
    border-radius: 50%;
    background: radial-gradient(circle,
        var(--accent-glow, rgba(0,210,200,0.08)),
        transparent 70%);
}

.kpi-icon {
    width: 44px;
    height: 44px;
    border-radius: 12px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 20px;
    margin-bottom: 12px;
}

.kpi-label {
    font-size: 13px;
    color: #8896a8;
    margin-bottom: 6px;
}

.kpi-value {
    font-size: 34px;
    font-weight: 700;
    color: #f0f6ff;
    line-height: 1.1;
}

.kpi-delta {
    font-size: 12px;
    font-weight: 600;
    padding: 4px 10px;
    border-radius: 20px;
    position: absolute;
    top: 16px;
    right: 16px;
}

.delta-up {
    background: rgba(0,200,120,0.15);
    color: #00c878;
}

.delta-down {
    background: rgba(255,80,80,0.15);
    color: #ff5050;
}

.delta-live {
    background: rgba(0,210,200,0.15);
    color: #00d2c8;
}

/* ─────────────────────────────────────────────
   패널
───────────────────────────────────────────── */
.panel {
    background: #111827;
    border: 1px solid #1e2d45;
    border-radius: 22px;
    padding: 24px;
    box-shadow: 0 4px 20px rgba(0,0,0,0.18);
}

.panel-title {
    font-size: 18px;
    font-weight: 700;
    color: #f8fafc;
    margin-bottom: 20px;
}

/* ─────────────────────────────────────────────
   이벤트 배지
───────────────────────────────────────────── */
.badge {
    display: inline-block;
    font-size: 11px;
    font-weight: 700;
    padding: 4px 10px;
    border-radius: 7px;
    letter-spacing: 0.04em;
}

.badge-ENTER {
    background: rgba(0,200,120,0.2);
    color: #00c878;
    border: 1px solid rgba(0,200,120,0.3);
}

.badge-DWELL {
    background: rgba(255,170,0,0.2);
    color: #ffaa00;
    border: 1px solid rgba(255,170,0,0.3);
}

.badge-EXIT {
    background: rgba(255,80,80,0.2);
    color: #ff5050;
    border: 1px solid rgba(255,80,80,0.3);
}

/* ─────────────────────────────────────────────
   이벤트 리스트
───────────────────────────────────────────── */
.event-row {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 14px;
    background: #1a2340;
    border: 1px solid #1e2d45;
    border-radius: 14px;
    margin-bottom: 10px;
}

.event-zone {
    font-size: 14px;
    font-weight: 600;
    color: #e2e8f0;
    flex: 1;
}

.event-id {
    font-size: 12px;
    color: #8896a8;
}

.event-time {
    font-size: 12px;
    color: #8896a8;
}

.event-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    flex-shrink: 0;
}

.dot-green {
    background: #00c878;
    box-shadow: 0 0 8px #00c878;
}

.dot-orange {
    background: #ffaa00;
    box-shadow: 0 0 8px #ffaa00;
}

.dot-red {
    background: #ff5050;
    box-shadow: 0 0 8px #ff5050;
}

/* ─────────────────────────────────────────────
   상태 영역
───────────────────────────────────────────── */
.status-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 12px 0;
    border-bottom: 1px solid #1e2d45;
    font-size: 13px;
}

.status-row:last-child {
    border-bottom: none;
}

.status-label {
    color: #8896a8;
}

.status-ok {
    color: #00c878;
    font-weight: 600;
}

.status-warn {
    color: #ffaa00;
    font-weight: 600;
}

.status-cyan {
    color: #00d2c8;
    font-weight: 600;
}

/* ─────────────────────────────────────────────
   하단 상태 카드
───────────────────────────────────────────── */
.sys-status {
    background: #1a2740;
    border: 1px solid #233554;
    border-radius: 18px;
    padding: 16px;
    font-size: 13px;
    margin-top: 20px;
}

/* ─────────────────────────────────────────────
   Streamlit 기본 컴포넌트
───────────────────────────────────────────── */
.stButton > button {
    background: linear-gradient(90deg, #18d5e2, #1eb6d4) !important;
    color: #08101d !important;
    border: none !important;
    border-radius: 12px !important;
    font-weight: 700 !important;
    font-size: 15px !important;
    height: 48px;
}

.stButton > button:hover {
    opacity: 0.92;
}

div[data-testid="metric-container"] {
    background: #141b2d;
    border: 1px solid #1e2d45;
    border-radius: 16px;
    padding: 16px;
}

.stTextInput > div > div > input,
.stSelectbox > div > div,
.stNumberInput > div > div > input {
    background: #111827 !important;
    border: 1px solid #1e2d45 !important;
    color: #e2e8f0 !important;
    border-radius: 12px !important;
}

.stDataFrame {
    background: #141b2d !important;
}

hr {
    border-color: #1e2d45 !important;
}

h1, h2, h3 {
    color: #f0f6ff !important;
}

p, li {
    color: #c8d3e0;
}
</style>
"""

def sidebar_status():
    """공통 사이드바 하단 시스템 상태."""
    import streamlit as st

    st.markdown("---")

    st.markdown("""
    <div class="sys-status">
      <div style="display:flex;align-items:center;gap:10px;margin-bottom:6px;">
        <div style="
            width:10px;
            height:10px;
            border-radius:50%;
            background:#00c878;
            box-shadow:0 0 8px #00c878;">
        </div>

        <span style="
            font-weight:700;
            color:#f8fafc;
            font-size:15px;">
            시스템 정상
        </span>
      </div>

      <div style="
          color:#94a3b8;
          font-size:13px;">
          AI 모델: v2.1.0
      </div>
    </div>
    """, unsafe_allow_html=True)


def page_header(title: str, subtitle: str):
    import streamlit as st

    st.markdown(f"# {title}")

    st.markdown(
        f"""
        <p style='
            color:#8896a8;
            margin-top:-12px;
            margin-bottom:20px;
            font-size:15px;'>
            {subtitle}
        </p>
        """,
        unsafe_allow_html=True
    )