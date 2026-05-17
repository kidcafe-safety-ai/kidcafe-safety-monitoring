"""페이지 3 — 실시간 모니터링"""
import json
import sys
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))
from _style import DARK_CSS, sidebar_status

st.set_page_config(page_title="모니터링 · KidCafe Safety AI", page_icon="📹", layout="wide")
st.markdown(DARK_CSS, unsafe_allow_html=True)

for key, val in {"video_path": None, "zones_path": "data/zones/sample.json",
                 "events_path": "outputs/events.jsonl", "pipeline_done": False,
                 "_playing": False}.items():
    if key not in st.session_state:
        st.session_state[key] = val

# ── 헬퍼 ──────────────────────────────────────────────────────────────────────
ZONE_COLORS_BGR = [(0,210,200),(255,170,0),(255,80,80),(0,200,120),(128,0,255)]

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

def draw_overlay(frame, zones, tracks, zone_name_map):
    out = frame.copy()
    h, w = out.shape[:2]
    for i, z in enumerate(zones):
        color = ZONE_COLORS_BGR[i % len(ZONE_COLORS_BGR)]
        pts = np.array([[int(p[0]*w), int(p[1]*h)] for p in z["points"]], np.int32)
        overlay = out.copy()
        cv2.fillPoly(overlay, [pts], (*color, 30))
        cv2.addWeighted(overlay, 0.15, out, 0.85, 0, out)
        cv2.polylines(out, [pts], True, color, 2)
        lx, ly = int(z["points"][0][0]*w), max(int(z["points"][0][1]*h)-8, 12)
        cv2.putText(out, z["name"], (lx, ly), cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1, cv2.LINE_AA)
    for t in tracks:
        x1, y1, x2, y2 = (int(v) for v in t["bbox"])
        cv2.rectangle(out, (x1, y1), (x2, y2), (0, 210, 200), 2)
        label = f"ID-{t['track_id']}"
        (lw, lh), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        cv2.rectangle(out, (x1, y1-lh-8), (x1+lw+6, y1), (0,210,200), -1)
        cv2.putText(out, label, (x1+3, y1-4), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (10,14,20), 1, cv2.LINE_AA)
    return out

# ── 사이드바 ──────────────────────────────────────────────────────────────────
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

    play_btn = st.button("▶ 재생", use_container_width=True)
    stop_btn = st.button("⏸ 정지", use_container_width=True)
    if play_btn: st.session_state._playing = True
    if stop_btn: st.session_state._playing = False

    sidebar_status()

# ── 데이터 ───────────────────────────────────────────────────────────────────
events = load_events(st.session_state.events_path)
zones  = load_zones(st.session_state.zones_path)
zone_name_map = {z["zone_id"]: z["name"] for z in zones}
frame_track_map = defaultdict(list)
for e in events:
    frame_track_map[e["frame_number"]].append({"track_id": e["track_id"], "bbox": e["bbox"]})

enters = sum(1 for e in events if e["event_type"] == "ENTER")
dwells = sum(1 for e in events if e["event_type"] == "DWELL")
track_ids = {e["track_id"] for e in events}

# ── 헤더 ──────────────────────────────────────────────────────────────────────
h_col1, h_col2 = st.columns([4, 1])
with h_col1:
    st.markdown("# 실시간 모니터링")
    st.markdown("<p style='color:#8896a8;margin-top:-12px;'>Vision AI 기반 안전 감시 시스템</p>",
                unsafe_allow_html=True)
with h_col2:
    live_color = "#ff4444" if st.session_state._playing else "#8896a8"
    st.markdown(f"""
    <div style="display:flex;align-items:center;justify-content:flex-end;gap:8px;padding-top:16px;">
      <div style="width:10px;height:10px;border-radius:50%;background:{live_color};
           box-shadow:0 0 8px {live_color};"></div>
      <span style="font-size:14px;font-weight:700;color:{live_color};">
        {'LIVE' if st.session_state._playing else 'STANDBY'}
      </span>
    </div>
    """, unsafe_allow_html=True)

# ── KPI 3개 ───────────────────────────────────────────────────────────────────
k1, k2, k3 = st.columns(3)
for col, icon, bg, label, value in [
    (k1, "👥", "#0080ff", "현재 감지 인원",   f"{len(track_ids)}"),
    (k2, "⚠️", "#ffaa00", "위험구역 내 인원", f"{dwells}"),
    (k3, "🕐", "#00d2c8", "평균 체류 시간",   "4.2분"),
]:
    with col:
        st.markdown(f"""
        <div class="kpi-card">
          <div style="display:flex;align-items:center;gap:16px;">
            <div class="kpi-icon" style="background:rgba({
              '0,128,255' if bg=='#0080ff' else '255,170,0' if bg=='#ffaa00' else '0,210,200'
            },0.15);">{icon}</div>
            <div>
              <div class="kpi-value" style="color:{bg};font-size:36px;">{value}</div>
              <div class="kpi-label">{label}</div>
            </div>
          </div>
        </div>
        """, unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# ── 메인: 영상 | 이벤트 패널 ──────────────────────────────────────────────────
vid_col, evt_col = st.columns([3, 1], gap="medium")

with vid_col:
    st.markdown('<div class="panel">', unsafe_allow_html=True)
    st.markdown("""
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
      <div class="panel-title" style="margin-bottom:0;">실시간 영상</div>
    </div>
    """, unsafe_allow_html=True)

    frame_placeholder = st.empty()
    vpath = st.session_state.get("video_path")
    cap_ok = vpath and Path(vpath).exists()

    if cap_ok and st.session_state._playing:
        cap = cv2.VideoCapture(vpath)
        total_f = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        fn = 0
        while st.session_state._playing:
            ret, frame = cap.read()
            if not ret:
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0); fn = 0; continue
            tracks = frame_track_map.get(fn, [])
            ov = draw_overlay(frame, zones, tracks, zone_name_map)
            # camera info overlay
            cv2.putText(ov, f"● Camera 01   FPS: 30   Frame: {fn}/{total_f}",
                        (12, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200,200,200), 1)
            frame_placeholder.image(cv2.cvtColor(ov, cv2.COLOR_BGR2RGB), use_column_width=True)
            fn += 1
            if fn % 3 != 0: continue
        cap.release()

    elif cap_ok:
        cap = cv2.VideoCapture(vpath)
        target = events[-1]["frame_number"] if events else 0
        cap.set(cv2.CAP_PROP_POS_FRAMES, target)
        ret, frame = cap.read()
        cap.release()
        if ret:
            tracks = frame_track_map.get(target, [])
            ov = draw_overlay(frame, zones, tracks, zone_name_map)
            cv2.putText(ov, f"● Camera 01   FPS: 30   Frame: {target}",
                        (12, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200,200,200), 1)
            frame_placeholder.image(cv2.cvtColor(ov, cv2.COLOR_BGR2RGB), use_column_width=True)
        else:
            frame_placeholder.info("프레임을 읽을 수 없습니다.")
    else:
        frame_placeholder.markdown("""
        <div style="height:380px;background:#0f1117;border:2px dashed #1e2d45;border-radius:12px;
             display:flex;flex-direction:column;align-items:center;justify-content:center;gap:10px;">
          <div style="font-size:36px;">📹</div>
          <div style="color:#8896a8;">홈 페이지에서 영상을 업로드하세요</div>
          <div style="color:#1e2d45;font-size:12px;">data/videos/test.mp4</div>
        </div>
        """, unsafe_allow_html=True)

    # 타임라인
    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown('<div class="panel-title">타임라인</div>', unsafe_allow_html=True)

    if events:
        import pandas as pd
        df = pd.DataFrame(events)
        type_color = {"ENTER": "#00c878", "DWELL": "#ffaa00", "EXIT": "#ff5050"}
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(7, 1.8))
        fig.patch.set_facecolor("#141b2d")
        ax.set_facecolor("#0f1117")
        for etype, color in type_color.items():
            sub = df[df["event_type"] == etype]
            ax.scatter(sub["frame_number"], sub["track_id"],
                       color=color, s=24, alpha=0.8, label=etype, zorder=3)
        ax.set_xlabel("Frame", color="#8896a8", fontsize=8)
        ax.set_ylabel("Track ID", color="#8896a8", fontsize=8)
        ax.tick_params(colors="#8896a8", labelsize=7)
        for sp in ax.spines.values(): sp.set_color("#1e2d45")
        ax.grid(True, color="#1e2d45", lw=0.5, alpha=0.5)
        ax.legend(fontsize=7, framealpha=0, labelcolor="white", loc="upper left")
        plt.tight_layout(pad=0.3)
        st.pyplot(fig, use_container_width=False)
        plt.close(fig)
    else:
        st.markdown('<p style="color:#8896a8;font-size:13px;">이벤트 없음</p>', unsafe_allow_html=True)

    st.markdown('</div>', unsafe_allow_html=True)

with evt_col:
    st.markdown('<div class="panel" style="height:100%;">', unsafe_allow_html=True)
    st.markdown('<div class="panel-title">실시간 이벤트</div>', unsafe_allow_html=True)

    EVT_BG = {"DWELL": ("#2a1c00","#ffaa00"), "ENTER": ("#0c2a1c","#00c878"), "EXIT": ("#2a0c0c","#ff5050")}
    recent = events[-12:][::-1] if events else []

    if recent:
        for i, e in enumerate(recent):
            etype = e["event_type"]
            bg, color = EVT_BG.get(etype, ("#1a2340","#8896a8"))
            zname = zone_name_map.get(e["zone_id"], e["zone_id"])
            ago = f"{i+1}초" if i < 10 else f"{i//10}분"
            st.markdown(f"""
            <div style="background:{bg};border:1px solid {color}33;border-radius:10px;
                 padding:12px;margin-bottom:8px;">
              <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">
                <span class="badge badge-{etype}">{etype}</span>
                <span style="color:#8896a8;font-size:11px;">{ago}</span>
              </div>
              <div style="font-size:14px;font-weight:600;color:#e2e8f0;">ID-{e['track_id']}</div>
              <div style="font-size:12px;color:#8896a8;">{zname}</div>
            </div>
            """, unsafe_allow_html=True)
    else:
        st.markdown('<p style="color:#8896a8;text-align:center;padding:20px;">이벤트 없음</p>',
                    unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

st.markdown("---")
st.caption("한이음 드림업 프로젝트 2026 · KidCafe Safety AI Team")