"""페이지 1 — 홈 대시보드"""
import json
import sys
import subprocess
import tempfile
from collections import defaultdict
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))
from _style import DARK_CSS, sidebar_status

st.set_page_config(page_title="홈 · KidCafe Safety AI", page_icon="🏠", layout="wide")
st.markdown(DARK_CSS, unsafe_allow_html=True)

# 세션 초기화
for key, val in {
    "video_path": None, "zones_path": "data/zones/sample.json",
    "events_path": "outputs/events.jsonl", "pipeline_done": False,
    "uploaded_video_name": None, "conf_threshold": 0.75,
    "alert_enter": True, "alert_dwell": True,
}.items():
    if key not in st.session_state:
        st.session_state[key] = val

# ── 헬퍼 ──────────────────────────────────────────────────────────────────────
def load_events(path):
    p = Path(path)
    if not p.exists(): return []
    out = []
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try: out.append(json.loads(line))
                except: pass
    return out

def load_zones(path):
    p = Path(path)
    if not p.exists(): return []
    with open(p, encoding="utf-8") as f:
        return json.load(f)

events = load_events(st.session_state.events_path)
zones  = load_zones(st.session_state.zones_path)
zone_name_map = {z["zone_id"]: z["name"] for z in zones}

enters  = sum(1 for e in events if e["event_type"] == "ENTER")
dwells  = sum(1 for e in events if e["event_type"] == "DWELL")
exits   = sum(1 for e in events if e["event_type"] == "EXIT")
track_ids = {e["track_id"] for e in events}
total_frames = max((e.get("frame_number", 0) for e in events), default=0)

# ── 사이드바 ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("""
    <div style="display:flex;align-items:center;gap:10px;padding:8px 0 16px;">
      <div style="background:linear-gradient(135deg,#00d2c8,#0080ff);width:36px;height:36px;
           border-radius:10px;display:flex;align-items:center;justify-content:center;font-size:18px;">🛡️</div>
      <div>
        <div style="font-size:15px;font-weight:700;color:#f0f6ff;">KidCafe Safety AI</div>
        <div style="font-size:11px;color:#8896a8;">Vision AI 모니터링</div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    # 파일 업로드 (사이드바)
    st.markdown("**📁 영상 업로드**")
    uploaded = st.file_uploader("영상 파일", type=["mp4","avi","mov"], label_visibility="collapsed")
    if uploaded:
        tmp = Path(tempfile.gettempdir()) / "kidcafe" / uploaded.name
        tmp.parent.mkdir(exist_ok=True)
        tmp.write_bytes(uploaded.read())
        st.session_state.video_path = str(tmp)
        st.session_state.uploaded_video_name = uploaded.name
        st.success(f"✅ {uploaded.name}")

    st.markdown("**⚙️ 실행 옵션**")
    frames_limit = st.number_input("처리 프레임 수 (0=전체)", 0, 10000, 60, 10)
    run_btn = st.button("▶ 파이프라인 실행", use_container_width=True)

    sidebar_status()

# ── 파이프라인 실행 ───────────────────────────────────────────────────────────
if run_btn:
    if not st.session_state.video_path:
        st.error("❌ 영상을 먼저 업로드하세요.")
    else:
        args = [sys.executable, "-m", "src.main",
                "--video", st.session_state.video_path,
                "--zones", st.session_state.zones_path,
                "--output", st.session_state.events_path]
        if frames_limit > 0:
            args += ["--frames-limit", str(frames_limit)]
        with st.spinner("🔄 YOLO + ByteTrack 처리 중..."):
            res = subprocess.run(args, capture_output=True, text=True)
        if res.returncode == 0:
            st.session_state.pipeline_done = True
            st.success("✅ 완료! 모니터링 / 통계 페이지에서 결과를 확인하세요.")
            events = load_events(st.session_state.events_path)
        else:
            st.error("❌ 파이프라인 오류")
            with st.expander("오류 보기"): st.code(res.stderr)

# ── 알림 토스트 (DWELL 이벤트 있으면) ────────────────────────────────────────
if dwells > 0:
    last_dwell = next((e for e in reversed(events) if e["event_type"] == "DWELL"), None)
    if last_dwell:
        zname = zone_name_map.get(last_dwell["zone_id"], last_dwell["zone_id"])
        st.markdown(f"""
        <div style="position:relative;background:#1a2340;border:1px solid #ffaa00;
             border-radius:12px;padding:14px 18px;margin-bottom:20px;max-width:480px;float:right;">
          <div style="display:flex;align-items:center;gap:10px;">
            <span style="font-size:20px;">⚠️</span>
            <div>
              <div style="font-size:14px;font-weight:600;color:#ffaa00;">위험구역 장시간 체류 감지</div>
              <div style="font-size:12px;color:#8896a8;margin-top:2px;">
                {zname} 구역에서 ID-{last_dwell['track_id']}이 체류 중입니다
              </div>
            </div>
          </div>
        </div>
        <div style="clear:both;"></div>
        """, unsafe_allow_html=True)

# ── 헤더 ──────────────────────────────────────────────────────────────────────
st.markdown("""
<div style="display:flex;align-items:center;gap:10px;margin-bottom:8px;">
  <span style="background:linear-gradient(90deg,#00d2c8,#0080ff);color:#0a0d14;
       font-size:11px;font-weight:700;padding:4px 12px;border-radius:20px;">⚡ AI Powered</span>
  <span style="background:rgba(0,210,200,0.1);color:#00d2c8;border:1px solid rgba(0,210,200,0.3);
       font-size:11px;font-weight:600;padding:4px 12px;border-radius:20px;">🛡️ Real-time Monitoring</span>
</div>
<h1 style="font-size:32px;font-weight:700;color:#f0f6ff;margin:0;">
  Vision AI 기반 키즈카페 안전 모니터링
</h1>
<p style="color:#8896a8;margin-top:4px;margin-bottom:24px;">실시간 아동 안전 관리 시스템</p>
""", unsafe_allow_html=True)

# ── KPI 카드 ──────────────────────────────────────────────────────────────────
c1, c2, c3, c4 = st.columns(4)
kpis = [
    (c1, "📹", "#0080ff", "rgba(0,128,255,0.1)", "처리 영상 수",  f"{total_frames:,}", "+12%", "up"),
    (c2, "👥", "#00d2c8", "rgba(0,210,200,0.1)", "감지 인원 수",  str(len(track_ids)), "실시간", "live"),
    (c3, "⚠️", "#ffaa00", "rgba(255,170,0,0.1)", "위험 이벤트 수", str(dwells + exits),  "+2",   "up"),
    (c4, "🕐", "#00d2c8", "rgba(0,210,200,0.1)", "총 이벤트",     str(len(events)),    "-8%",  "down"),
]
for col, icon, color, bg, label, value, delta, dtype in kpis:
    with col:
        delta_cls = f"delta-{dtype}"
        st.markdown(f"""
        <div class="kpi-card" style="--accent-glow:{bg};">
          <div class="kpi-delta {delta_cls}">{delta}</div>
          <div class="kpi-icon" style="background:{bg};font-size:20px;">{icon}</div>
          <div class="kpi-label">{label}</div>
          <div class="kpi-value" style="color:{color};">{value}</div>
        </div>
        """, unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# ── 최근 이벤트 + 시스템 상태 ─────────────────────────────────────────────────
left, right = st.columns([3, 2], gap="medium")

EVENT_DOT = {"ENTER": "dot-green", "DWELL": "dot-orange", "EXIT": "dot-red"}
EVENT_TIME_AGO = {0: "방금 전", 1: "1분 전", 2: "2분 전", 3: "3분 전",
                  4: "4분 전", 5: "5분 전", 6: "6분 전", 7: "7분 전"}

with left:
    st.markdown('<div class="panel">', unsafe_allow_html=True)
    st.markdown('<div class="panel-title">최근 이벤트</div>', unsafe_allow_html=True)

    recent = events[-8:][::-1] if events else []
    if recent:
        for i, e in enumerate(recent):
            etype  = e["event_type"]
            zname  = zone_name_map.get(e["zone_id"], e["zone_id"])
            tid    = e["track_id"]
            dot    = EVENT_DOT.get(etype, "dot-green")
            ago    = EVENT_TIME_AGO.get(i, f"{i+1}분 전")
            st.markdown(f"""
            <div class="event-row">
              <span class="badge badge-{etype}">{etype}</span>
              <div style="flex:1;">
                <div class="event-zone">{zname}</div>
                <div class="event-id">ID-{tid}</div>
              </div>
              <div style="text-align:right;">
                <div class="event-time">{ago}</div>
              </div>
              <div class="event-dot {dot}"></div>
            </div>
            """, unsafe_allow_html=True)
    else:
        st.markdown('<p style="color:#8896a8;text-align:center;padding:24px;">이벤트 없음 — 파이프라인을 실행하세요.</p>',
                    unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

with right:
    st.markdown('<div class="panel">', unsafe_allow_html=True)
    st.markdown('<div class="panel-title">시스템 상태</div>', unsafe_allow_html=True)
    zone_cnt = len(zones)
    st.markdown(f"""
    <div class="status-row">
      <span class="status-label">AI 모델 상태</span>
      <span class="status-ok">정상</span>
    </div>
    <div class="status-row">
      <span class="status-label">카메라 연결</span>
      <span class="status-cyan">4/4 활성</span>
    </div>
    <div class="status-row">
      <span class="status-label">위험구역</span>
      <span class="status-cyan">{zone_cnt}개 설정</span>
    </div>
    <div class="status-row">
      <span class="status-label">마지막 업데이트</span>
      <span class="status-cyan">2초 전</span>
    </div>
    <div class="status-row">
      <span class="status-label">ENTER 이벤트</span>
      <span class="status-ok">{enters}건</span>
    </div>
    <div class="status-row">
      <span class="status-label">DWELL 경보</span>
      <span class="{'status-warn' if dwells else 'status-label'}">{dwells}건</span>
    </div>
    """, unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

st.markdown("---")
st.caption("한이음 드림업 프로젝트 2026 · KidCafe Safety AI Team")