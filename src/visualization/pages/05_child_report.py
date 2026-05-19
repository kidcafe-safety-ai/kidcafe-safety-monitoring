"""페이지 5 — 자녀 활동 리포트"""
import json, sys
from pathlib import Path
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))
from _style import inject_css, sidebar_status, _colors

st.set_page_config(page_title="자녀 활동 리포트 · KidCafe Safety AI", page_icon="👨‍👩‍👧", layout="wide")
inject_css()

for key, val in {"events_path":"outputs/events.jsonl",
                 "zones_path":"data/zones/sample.json","theme_mode":"dark"}.items():
    if key not in st.session_state:
        st.session_state[key] = val

c = _colors()

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
    with open(p, encoding="utf-8") as f: return json.load(f)

events = load_events(st.session_state.events_path)
zones  = load_zones(st.session_state.zones_path)
zone_name_map = {z["zone_id"]: z["name"] for z in zones}
track_ids = sorted({e["track_id"] for e in events})

# ── 사이드바 ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown(
        f'<div style="display:flex;align-items:center;gap:10px;padding:8px 0 16px;">'
        f'  <div style="background:linear-gradient(135deg,#00d2c8,#0080ff);width:36px;height:36px;'
        f'       border-radius:10px;display:flex;align-items:center;justify-content:center;">🛡️</div>'
        f'  <div><div style="font-size:15px;font-weight:700;color:{c["TEXT"]};">KidCafe Safety AI</div>'
        f'  <div style="font-size:11px;color:{c["TEXT_SUB"]};">Vision AI 모니터링</div></div></div>',
        unsafe_allow_html=True,
    )
    st.markdown("**👤 아동 선택**")
    selected_id = st.selectbox("Track ID", options=track_ids if track_ids else [1234,5678,9012],
                               format_func=lambda x: f"ID-{x}", label_visibility="collapsed")
    sidebar_status()

child_events = [e for e in events if e["track_id"] == selected_id]
visited_zones = {e["zone_id"] for e in child_events}

# ── 헤더 ──────────────────────────────────────────────────────────────────────
st.markdown("# 👨‍👩‍👧 자녀 활동 리포트")
st.markdown(f'<p style="color:{c["TEXT_SUB"]};margin-top:-12px;">ID-{selected_id} · 오늘의 활동 분석</p>',
            unsafe_allow_html=True)
st.divider()

# ── KPI ───────────────────────────────────────────────────────────────────────
k1,k2,k3,k4 = st.columns(4)
for col, icon, color, label, value in [
    (k1,"🕐","#00d2c8","총 활동 시간","1시간 37분"),
    (k2,"📍","#00c878","방문 구역",str(len(visited_zones))),
    (k3,"⚡","#0080ff","활동 강도","높음"),
    (k4,"🛡️","#00c878","안전 점수","98/100"),
]:
    with col:
        st.markdown(
            f'<div class="kpi-card">'
            f'  <div style="display:flex;align-items:center;gap:12px;">'
            f'    <div style="background:rgba(0,210,200,0.1);width:44px;height:44px;border-radius:12px;'
            f'         display:flex;align-items:center;justify-content:center;font-size:20px;">{icon}</div>'
            f'    <div>'
            f'      <div style="font-size:24px;font-weight:700;color:{color};">{value}</div>'
            f'      <div class="kpi-label">{label}</div>'
            f'    </div>'
            f'  </div>'
            f'</div>',
            unsafe_allow_html=True,
        )

st.markdown("<br>", unsafe_allow_html=True)
left, right = st.columns([3,2], gap="medium")

DEMO_TIMELINE = [
    ("출입문","ENTER","14:23","2분","#00c878","→"),
    ("볼풀","DWELL","14:25","15분","#00d2c8","⏱"),
    ("트램폴린","DWELL","14:40","8분","#00d2c8","⏱"),
    ("미끄럼틀","DWELL","14:48","12분","#ffaa00","⏱"),
]

with left:
    st.markdown('<div class="panel">', unsafe_allow_html=True)
    st.markdown('<div class="panel-title">활동 타임라인</div>', unsafe_allow_html=True)
    timeline_data = []
    if child_events:
        for i, e in enumerate(child_events[:8]):
            zname = zone_name_map.get(e["zone_id"], e["zone_id"])
            etype = e["event_type"]
            color = "#00c878" if etype=="ENTER" else "#00d2c8" if etype=="DWELL" else "#ff5050"
            icon  = "→" if etype=="ENTER" else "⏱" if etype=="DWELL" else "←"
            timeline_data.append((zname, etype, f"F{e['frame_number']}", "—", color, icon))
    else:
        for z,t,ts,dur,col,ic in DEMO_TIMELINE:
            timeline_data.append((z,t,ts,dur,col,ic))

    for i, (zone, etype, ts, dur, color, icon) in enumerate(timeline_data):
        is_last = (i == len(timeline_data)-1)
        connector = "" if is_last else \
            f'<div style="margin-left:15px;width:2px;height:20px;background:linear-gradient({color},#1e2d45);"></div>'
        st.markdown(
            f'<div style="display:flex;gap:14px;align-items:flex-start;">'
            f'  <div style="display:flex;flex-direction:column;align-items:center;flex-shrink:0;">'
            f'    <div style="width:32px;height:32px;border-radius:50%;background:{color};'
            f'         display:flex;align-items:center;justify-content:center;font-size:14px;">{icon}</div>'
            f'    {connector}'
            f'  </div>'
            f'  <div style="background:{c["CARD"]};border:1px solid {c["BORDER"]};border-radius:10px;'
            f'       padding:12px 16px;margin-bottom:4px;flex:1;">'
            f'    <div style="display:flex;justify-content:space-between;align-items:center;">'
            f'      <div style="font-size:15px;font-weight:600;color:{c["TEXT"]};">{zone}</div>'
            f'      <div style="text-align:right;">'
            f'        <div style="font-size:13px;color:{c["TEXT_SUB"]};">{ts}</div>'
            f'        <div style="font-size:12px;color:{c["TEXT_SUB"]};">{dur}</div>'
            f'      </div>'
            f'    </div>'
            f'    <div style="font-size:12px;color:{c["TEXT_SUB"]};margin-top:2px;">{etype}</div>'
            f'  </div>'
            f'</div>',
            unsafe_allow_html=True,
        )
    st.markdown('</div>', unsafe_allow_html=True)

with right:
    st.markdown('<div class="panel" style="margin-bottom:16px;">', unsafe_allow_html=True)
    st.markdown('<div class="panel-title">안전 이벤트</div>', unsafe_allow_html=True)
    for color, msg, ts in [
        ("#00c878","볼풀 영역 진입","14:25"),
        ("#00c878","트램폴린 8분 체류 (정상)","14:43"),
        ("#ffaa00","미끄럼틀 하단 접근","14:52"),
    ]:
        st.markdown(
            f'<div style="background:{c["BG_MAIN"]};border:1px solid {c["BORDER"]};'
            f'border-left:3px solid {color};border-radius:8px;padding:10px 14px;margin-bottom:8px;">'
            f'  <div style="display:flex;align-items:center;gap:8px;">'
            f'    <div style="width:8px;height:8px;border-radius:50%;background:{color};flex-shrink:0;"></div>'
            f'    <div>'
            f'      <div style="font-size:13px;color:{c["TEXT"]};">{msg}</div>'
            f'      <div style="font-size:11px;color:{c["TEXT_SUB"]};">{ts}</div>'
            f'    </div>'
            f'  </div>'
            f'</div>',
            unsafe_allow_html=True,
        )
    st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('<div class="panel">', unsafe_allow_html=True)
    st.markdown('<div class="panel-title">일일 요약</div>', unsafe_allow_html=True)
    st.markdown(f'<p style="color:{c["TEXT"]};font-size:13px;line-height:1.7;margin-bottom:12px;">'
                f'자녀가 키즈카페에서 안전하게 놀았습니다.</p>', unsafe_allow_html=True)
    for icon, color, text in [
        ("✅","#00c878","위험 이벤트 없음"),
        ("✅","#00c878","모든 활동 정상 범위 내"),
        ("📍","#00d2c8",f"총 {len(visited_zones)}개 구역 방문"),
        ("🕐","#0080ff","총 활동 시간 1시간 37분"),
    ]:
        st.markdown(
            f'<div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;">'
            f'  <span style="font-size:14px;">{icon}</span>'
            f'  <span style="font-size:13px;color:{color};">{text}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )
    st.markdown('</div>', unsafe_allow_html=True)

st.markdown("---")
st.caption("한이음 드림업 프로젝트 2026 · KidCafe Safety AI Team")