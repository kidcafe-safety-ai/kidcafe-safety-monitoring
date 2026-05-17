"""페이지 6 — 설정"""
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))
from _style import DARK_CSS, sidebar_status

st.set_page_config(page_title="설정 · KidCafe Safety AI", page_icon="⚙️", layout="wide")
st.markdown(DARK_CSS, unsafe_allow_html=True)

for key, val in {
    "conf_threshold": 0.75, "track_stability": 0.60, "dwell_sec": 10,
    "alert_enter": True, "alert_dwell": True, "alert_daily": True, "alert_weekly": False,
    "events_path": "outputs/events.jsonl",
}.items():
    if key not in st.session_state:
        st.session_state[key] = val

with st.sidebar:
    st.markdown("""
    <div style="display:flex;align-items:center;gap:10px;padding:8px 0 16px;">
      <div style="background:linear-gradient(135deg,#00d2c8,#0080ff);width:36px;height:36px;
           border-radius:10px;display:flex;align-items:center;justify-content:center;">🛡️</div>
      <div>
        <div style="font-size:15px;font-weight:700;color:#f0f6ff;">KidCafe Safety AI</div>
        <div style="font-size:11px;color:#8896a8;">Vision AI 모니터링</div>
      </div>
    </div>
    """, unsafe_allow_html=True)
    sidebar_status()

st.markdown("# ⚙️ 설정")
st.markdown("<p style='color:#8896a8;margin-top:-12px;'>시스템 설정 및 환경 구성</p>",
            unsafe_allow_html=True)
st.divider()

top_col1, top_col2 = st.columns(2, gap="medium")

# ── AI 모델 설정 ──────────────────────────────────────────────────────────────
with top_col1:
    st.markdown('<div class="panel">', unsafe_allow_html=True)
    st.markdown("""
    <div style="display:flex;align-items:center;gap:12px;margin-bottom:16px;">
      <div style="background:rgba(0,128,255,0.15);width:44px;height:44px;border-radius:12px;
           display:flex;align-items:center;justify-content:center;font-size:22px;">🛡️</div>
      <div>
        <div style="font-size:16px;font-weight:600;color:#f0f6ff;">AI 모델 설정</div>
        <div style="font-size:12px;color:#8896a8;">감지 임계값 및 민감도 조정</div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    conf = st.slider(f"감지 신뢰도 임계값: {st.session_state.conf_threshold:.2f}",
                     0.1, 1.0, st.session_state.conf_threshold, 0.05, key="conf_sl")
    st.session_state.conf_threshold = conf

    stab = st.slider(f"추적 안정성: {st.session_state.track_stability:.2f}",
                     0.1, 1.0, st.session_state.track_stability, 0.05, key="stab_sl")
    st.session_state.track_stability = stab

    dwell = st.slider(f"위험 체류 시간 (초): {st.session_state.dwell_sec}",
                      1, 60, st.session_state.dwell_sec, 1, key="dwell_sl")
    st.session_state.dwell_sec = dwell

    st.markdown("<br>", unsafe_allow_html=True)
    auto_retrain = st.toggle("자동 재학습", value=True,
                             help="데이터 축적 시 모델 자동 업데이트")
    st.markdown("""
    <div style="background:#0f1117;border:1px solid #1e2d45;border-radius:8px;
         padding:10px 14px;margin-top:8px;">
      <div style="font-size:12px;color:#8896a8;">자동 재학습</div>
      <div style="font-size:12px;color:#c8d3e0;">데이터 축적 시 모델 자동 업데이트</div>
    </div>
    """, unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

# ── 알림 설정 ─────────────────────────────────────────────────────────────────
with top_col2:
    st.markdown('<div class="panel">', unsafe_allow_html=True)
    st.markdown("""
    <div style="display:flex;align-items:center;gap:12px;margin-bottom:16px;">
      <div style="background:rgba(255,170,0,0.15);width:44px;height:44px;border-radius:12px;
           display:flex;align-items:center;justify-content:center;font-size:22px;">🔔</div>
      <div>
        <div style="font-size:16px;font-weight:600;color:#f0f6ff;">알림 설정</div>
        <div style="font-size:12px;color:#8896a8;">위험 이벤트 알림 관리</div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    alerts = [
        ("alert_enter", "위험구역 진입 알림",  "고위험 구역 진입 시"),
        ("alert_dwell", "장시간 체류 알림",    "임계값 초과 시"),
        ("alert_daily", "일일 리포트",         "매일 오후 6시"),
        ("alert_weekly","주간 요약",           "매주 월요일"),
    ]
    for key, label, desc in alerts:
        col_a, col_b = st.columns([3, 1])
        with col_a:
            st.markdown(f"""
            <div style="padding:8px 0;border-bottom:1px solid #1e2d45;">
              <div style="font-size:14px;font-weight:500;color:#e2e8f0;">{label}</div>
              <div style="font-size:12px;color:#8896a8;">{desc}</div>
            </div>
            """, unsafe_allow_html=True)
        with col_b:
            st.session_state[key] = st.toggle("", value=st.session_state[key], key=f"tog_{key}",
                                               label_visibility="collapsed")
    st.markdown('</div>', unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)
bot_col1, bot_col2 = st.columns(2, gap="medium")

# ── 데이터 관리 ───────────────────────────────────────────────────────────────
with bot_col1:
    st.markdown('<div class="panel">', unsafe_allow_html=True)
    st.markdown("""
    <div style="display:flex;align-items:center;gap:12px;margin-bottom:16px;">
      <div style="background:rgba(0,210,200,0.15);width:44px;height:44px;border-radius:12px;
           display:flex;align-items:center;justify-content:center;font-size:22px;">🗄️</div>
      <div>
        <div style="font-size:16px;font-weight:600;color:#f0f6ff;">데이터 관리</div>
        <div style="font-size:12px;color:#8896a8;">이벤트 로그 및 저장소 관리</div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    events_path = st.text_input("Events 저장 경로", value=st.session_state.events_path)
    st.session_state.events_path = events_path

    from pathlib import Path
    p = Path(events_path)
    size_str = "—"
    count_str = "—"
    if p.exists():
        size_str = f"{p.stat().st_size / 1024:.1f} KB"
        with open(p, encoding="utf-8") as f:
            count_str = str(sum(1 for line in f if line.strip()))

    st.markdown(f"""
    <div class="status-row"><span class="status-label">파일 크기</span>
      <span class="status-cyan">{size_str}</span></div>
    <div class="status-row"><span class="status-label">이벤트 수</span>
      <span class="status-cyan">{count_str}건</span></div>
    """, unsafe_allow_html=True)

    col_d1, col_d2 = st.columns(2)
    with col_d1:
        if st.button("🗑 로그 초기화", use_container_width=True):
            if p.exists():
                p.write_text("")
                st.success("초기화 완료")
    with col_d2:
        if p.exists():
            with open(p, "rb") as f:
                st.download_button("⬇ 백업", f, "events_backup.jsonl",
                                   "application/jsonl", use_container_width=True)
    st.markdown('</div>', unsafe_allow_html=True)

# ── 시스템 정보 ───────────────────────────────────────────────────────────────
with bot_col2:
    st.markdown('<div class="panel">', unsafe_allow_html=True)
    st.markdown("""
    <div style="display:flex;align-items:center;gap:12px;margin-bottom:16px;">
      <div style="background:rgba(0,200,120,0.15);width:44px;height:44px;border-radius:12px;
           display:flex;align-items:center;justify-content:center;font-size:22px;">ℹ️</div>
      <div>
        <div style="font-size:16px;font-weight:600;color:#f0f6ff;">시스템 정보</div>
        <div style="font-size:12px;color:#8896a8;">버전 및 환경 정보</div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    import platform, sys as _sys
    info = [
        ("AI 모델",      "YOLOv8n + ByteTrack"),
        ("모델 버전",    "v2.1.0"),
        ("Python",       _sys.version.split()[0]),
        ("플랫폼",       platform.system()),
        ("Streamlit",    "1.34.0"),
        ("프로젝트",     "KidCafe Safety AI MVP"),
    ]
    for label, value in info:
        st.markdown(f"""
        <div class="status-row">
          <span class="status-label">{label}</span>
          <span style="color:#c8d3e0;font-size:13px;">{value}</span>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("⚙️ 설정 저장", use_container_width=True):
        st.success(f"✅ 저장 완료! (신뢰도: {st.session_state.conf_threshold:.2f}, 체류: {st.session_state.dwell_sec}초)")
    st.markdown('</div>', unsafe_allow_html=True)

st.markdown("---")
st.caption("한이음 드림업 프로젝트 2026 · KidCafe Safety AI Team")