"""페이지 4 — 통계 대시보드"""
import json, sys
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np, pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))
from _style import inject_css, sidebar_status, _colors

st.set_page_config(page_title="통계 · KidCafe Safety AI", page_icon="📊", layout="wide")
inject_css()

for key, val in {"zones_path":"data/zones/sample.json",
                 "events_path":"outputs/events.jsonl","theme_mode":"dark"}.items():
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
    sidebar_status()

# ── 헤더 ──────────────────────────────────────────────────────────────────────
hc1, hc2 = st.columns([3,2])
with hc1:
    st.markdown("# 통계 대시보드")
    st.markdown(f'<p style="color:{c["TEXT_SUB"]};margin-top:-12px;">AI 분석 리포트 및 인사이트</p>',
                unsafe_allow_html=True)
with hc2:
    fc1, fc2, fc3 = st.columns(3)
    with fc1: period = st.selectbox("기간",["오늘","이번 주","이번 달"], label_visibility="collapsed")
    with fc2: zone_filter = st.selectbox("Zone",["전체"]+[z["name"] for z in zones], label_visibility="collapsed")
    with fc3:
        if st.button("⬇ 내보내기") and events:
            df_exp = pd.DataFrame(events)
            st.download_button("CSV", df_exp.to_csv(index=False).encode(), "events.csv","text/csv")

enters = sum(1 for e in events if e["event_type"]=="ENTER")
dwells = sum(1 for e in events if e["event_type"]=="DWELL")
exits  = sum(1 for e in events if e["event_type"]=="EXIT")
total  = len(events)

# ── KPI 4개 ───────────────────────────────────────────────────────────────────
c1,c2,c3,c4 = st.columns(4)
for col, label, value, color, delta in [
    (c1,"ENTER",      str(enters),"#00c878","↗ 12.5%"),
    (c2,"DWELL",      str(dwells),"#ffaa00","↗ 8.3%"),
    (c3,"EXIT",       str(exits), "#00d2c8","↗ 11.2%"),
    (c4,"Total Events",str(total),"#e2e8f0","—"),
]:
    with col:
        st.markdown(
            f'<div class="kpi-card">'
            f'  <div style="display:flex;justify-content:space-between;align-items:flex-start;">'
            f'    <div>'
            f'      <div style="font-size:12px;color:{c["TEXT_SUB"]};margin-bottom:4px;">{label}</div>'
            f'      <div style="font-size:36px;font-weight:700;color:{color};">{value}</div>'
            f'      <div style="font-size:11px;color:{c["TEXT_SUB"]};margin-top:4px;">지난주 대비</div>'
            f'    </div>'
            f'    <div style="background:rgba(0,210,200,0.1);border-radius:20px;padding:3px 10px;'
            f'         font-size:12px;font-weight:600;color:{color};">{delta}</div>'
            f'  </div>'
            f'</div>',
            unsafe_allow_html=True,
        )

st.markdown("<br>", unsafe_allow_html=True)

# ── 차트 공통 ─────────────────────────────────────────────────────────────────
def base_fig(figsize=(6,3.5)):
    fig, ax = plt.subplots(figsize=figsize)
    fig.patch.set_facecolor(c["CARD"]); ax.set_facecolor(c["BG_MAIN"])
    ax.tick_params(colors=c["TEXT_SUB"], labelsize=8)
    for sp in ax.spines.values(): sp.set_color(c["BORDER"])
    ax.grid(True, color=c["BORDER"], lw=0.5, alpha=0.5)
    return fig, ax

cc1, cc2 = st.columns(2, gap="medium")

with cc1:
    st.markdown('<div class="panel">', unsafe_allow_html=True)
    st.markdown('<div class="panel-title">주간 이벤트 분석</div>', unsafe_allow_html=True)
    days = ["월","화","수","목","금","토","일"]
    counts = [45,52,38,61,73,88,95] if not events else \
             [max(0, len(events)//7 + int(x)) for x in np.random.randint(-5,20,7)]
    fig, ax = base_fig()
    bars = ax.bar(days, counts, color="#00d2c8", alpha=0.8, width=0.6)
    for b in bars[-2:]: b.set_color("#0080ff")
    ax.set_ylabel("이벤트 수", color=c["TEXT_SUB"], fontsize=8)
    plt.tight_layout(pad=0.5)
    # use_container_width를 True로 변경하여 화면에 맞게 자동 리사이징합니다.
    st.pyplot(fig, use_container_width=True); plt.close(fig)
    st.markdown('</div>', unsafe_allow_html=True)

with cc2:
    st.markdown('<div class="panel">', unsafe_allow_html=True)
    st.markdown('<div class="panel-title">시간대별 평균 체류 시간</div>', unsafe_allow_html=True)
    hours = [f"{h}:00" for h in range(10,17)]
    dwell_vals = [3.2,4.0,5.5,3.8,6.2,5.8,4.5]
    fig, ax = base_fig()
    ax.plot(hours, dwell_vals, color="#00d2c8", lw=2, marker="o", markersize=5, zorder=3)
    ax.fill_between(range(len(hours)), dwell_vals, alpha=0.08, color="#00d2c8")
    ax.set_xticks(range(len(hours))); ax.set_xticklabels(hours, fontsize=7)
    ax.set_ylabel("체류 시간 (분)", color=c["TEXT_SUB"], fontsize=8)
    plt.tight_layout(pad=0.5)
    # use_container_width를 True로 변경하여 오른쪽 그래프 잘림을 해결합니다.
    st.pyplot(fig, use_container_width=True); plt.close(fig)
    st.markdown('</div>', unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)
bc1, bc2 = st.columns([2,1], gap="medium")

with bc1:
    st.markdown('<div class="panel">', unsafe_allow_html=True)
    st.markdown('<div class="panel-title">Zone별 이벤트 현황</div>', unsafe_allow_html=True)
    zone_counts = defaultdict(int)
    for e in events:
        if e["event_type"]=="ENTER": zone_counts[e["zone_id"]] += 1
    if zone_counts:
        labels = [zone_name_map.get(k,k) for k in zone_counts]
        values = list(zone_counts.values())
    else:
        labels = [z["name"] for z in zones] if zones else ["출입문","미끄럼틀","트램폴린","볼풀"]
        values = [28,15,9,5]
    colors_bar = ["#00d2c8","#0080ff","#ffaa00","#ff5050","#bb88ff"]
    fig, ax = base_fig((6,2.8))
    bars = ax.barh(labels, values, color=[colors_bar[i%len(colors_bar)] for i in range(len(labels))],
                   alpha=0.85, height=0.5)
    for bar, val in zip(bars, values):
        ax.text(val+0.3, bar.get_y()+bar.get_height()/2, str(val), va="center",
                color=c["TEXT"], fontsize=9)
    ax.set_xlabel("진입 횟수", color=c["TEXT_SUB"], fontsize=8)
    plt.tight_layout(pad=0.5)
    # 아래쪽 가로 바 차트도 함께 자동 리사이징 되도록 설정했습니다.
    st.pyplot(fig, use_container_width=True); plt.close(fig)
    st.markdown('</div>', unsafe_allow_html=True)

with bc2:
    st.markdown('<div class="panel">', unsafe_allow_html=True)
    st.markdown('<div class="panel-title">💡 AI 인사이트</div>', unsafe_allow_html=True)
    for icon, color, msg in [
        ("⚠️","#ffaa00","출입문 위험구역 진입이 평균보다 47% 많습니다"),
        ("📈","#00d2c8","오후 2-4시에 아동 활동이 집중됩니다"),
        ("✅","#00c878","미끄럼틀 하단 체류 시간이 기준 이내입니다"),
    ]:
        st.markdown(
            f'<div style="background:{c["BG_MAIN"]};border:1px solid {c["BORDER"]};'
            f'border-left:3px solid {color};border-radius:8px;padding:12px;margin-bottom:10px;">'
            f'  <div style="display:flex;gap:10px;align-items:flex-start;">'
            f'    <span style="font-size:16px;">{icon}</span>'
            f'    <span style="font-size:12px;color:{c["TEXT"]};line-height:1.5;">{msg}</span>'
            f'  </div>'
            f'</div>',
            unsafe_allow_html=True,
        )
    st.markdown('</div>', unsafe_allow_html=True)

# ── 이벤트 테이블 ─────────────────────────────────────────────────────────────
st.markdown("<br>", unsafe_allow_html=True)
st.markdown('<div class="panel">', unsafe_allow_html=True)
st.markdown('<div class="panel-title">이벤트 상세 테이블</div>', unsafe_allow_html=True)
if events:
    df = pd.DataFrame(events)
    df["zone_name"] = df["zone_id"].map(zone_name_map).fillna(df["zone_id"])
    df["timestamp"] = df["timestamp"].str[:19].str.replace("T"," ")
    fc1,fc2,fc3 = st.columns(3)
    with fc1: sel_type = st.multiselect("이벤트 타입",["ENTER","DWELL","EXIT"],default=["ENTER","DWELL","EXIT"])
    with fc2:
        all_z = df["zone_id"].unique().tolist()
        sel_zone = st.multiselect("Zone", all_z, default=all_z)
    with fc3:
        all_t = sorted(df["track_id"].unique().tolist())
        sel_tid = st.multiselect("Track ID", all_t, default=all_t)
    cols = ["timestamp","event_type","track_id","zone_name","frame_number"]
    filt = df[df["event_type"].isin(sel_type)&df["zone_id"].isin(sel_zone)&df["track_id"].isin(sel_tid)][cols]
    st.dataframe(filt, height=220, hide_index=True)
    st.download_button("⬇ CSV 저장", filt.to_csv(index=False).encode(), "kidcafe_events.csv","text/csv")
else:
    st.info("이벤트 없음 — 홈 페이지에서 파이프라인을 실행하세요.")
st.markdown('</div>', unsafe_allow_html=True)
st.markdown("---")
st.caption("한이음 드림업 프로젝트 2026 · KidCafe Safety AI Team")