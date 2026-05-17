"""페이지 2 — Zone 편집기"""
import json
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))
from _style import DARK_CSS, sidebar_status

st.set_page_config(page_title="Zone 편집 · KidCafe Safety AI", page_icon="🗺️", layout="wide")
st.markdown(DARK_CSS, unsafe_allow_html=True)

for key, val in {"video_path": None, "zones_path": "data/zones/sample.json",
                 "pipeline_done": False}.items():
    if key not in st.session_state:
        st.session_state[key] = val

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
    st.markdown("**📹 영상 업로드**")
    up = st.file_uploader("영상", type=["mp4","avi","mov"], label_visibility="collapsed")
    if up:
        tmp = Path(tempfile.gettempdir()) / "kidcafe" / up.name
        tmp.parent.mkdir(exist_ok=True)
        tmp.write_bytes(up.read())
        st.session_state.video_path = str(tmp)
        st.success(f"✅ {up.name}")
    sidebar_status()

# ── 헤더 ──────────────────────────────────────────────────────────────────────
hcol1, hcol2 = st.columns([3, 2])
with hcol1:
    st.markdown("# Zone 편집")
    st.markdown("<p style='color:#8896a8;margin-top:-12px;'>위험 구역을 설정하고 관리합니다</p>",
                unsafe_allow_html=True)
with hcol2:
    # 탭 버튼 흉내 (실제 탭)
    pass

tab_draw, tab_edit, tab_preview = st.tabs(["🎨 그리기", "✏️ 편집", "👁️ 미리보기"])

# ── 기존 zones 로드 ───────────────────────────────────────────────────────────
def load_zones(path):
    p = Path(path)
    if not p.exists(): return []
    with open(p, encoding="utf-8") as f: return json.load(f)

existing = load_zones(st.session_state.zones_path)

# ── 탭 1: 그리기 (canvas) ─────────────────────────────────────────────────────
with tab_draw:
    main_col, side_col = st.columns([2, 1], gap="medium")

    with main_col:
        st.markdown('<div class="panel">', unsafe_allow_html=True)

        # 영상 첫 프레임 로드
        first_frame = None
        vpath = st.session_state.get("video_path")
        if vpath and Path(vpath).exists():
            cap = cv2.VideoCapture(vpath)
            ret, frame = cap.read()
            cap.release()
            if ret:
                first_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        try:
            from streamlit_drawable_canvas import st_canvas
            from PIL import Image

            canvas_w = 680
            canvas_h = 400

            bg_img = None
            if first_frame is not None:
                h, w = first_frame.shape[:2]
                scale = canvas_w / w
                bg_img = Image.fromarray(first_frame).resize((canvas_w, int(h * scale)))
                canvas_h = int(h * scale)

            result = st_canvas(
                fill_color="rgba(0,210,200,0.15)",
                stroke_width=2,
                stroke_color="#00d2c8",
                background_color="#141b2d",
                background_image=bg_img,
                height=canvas_h, width=canvas_w,
                drawing_mode="polygon",
                key="zone_canvas",
            )
            st.caption("클릭으로 점 추가 → 첫 번째 점 클릭으로 polygon 완성")

        except ImportError:
            # canvas 없으면 영상 프레임만 보여줌
            if first_frame is not None:
                st.image(first_frame, use_column_width=True, caption="영상 첫 프레임 (Zone 좌표 참고용)")
            else:
                st.markdown("""
                <div style="height:380px;background:#0f1117;border:2px dashed #1e2d45;border-radius:12px;
                     display:flex;flex-direction:column;align-items:center;justify-content:center;gap:12px;">
                  <div style="font-size:40px;">📹</div>
                  <div style="color:#8896a8;font-size:14px;">영상을 업로드하거나 카메라를 선택하세요</div>
                  <div style="color:#8896a8;font-size:12px;">클릭하여 폴리곤 그리기</div>
                </div>
                """, unsafe_allow_html=True)
            st.info("💡 `pip install streamlit-drawable-canvas` 설치 시 직접 그리기 가능")
        st.markdown('</div>', unsafe_allow_html=True)

    with side_col:
        # ── Zone 설정 패널 ────────────────────────────────────────────────────
        st.markdown('<div class="panel">', unsafe_allow_html=True)
        st.markdown('<div class="panel-title">Zone 설정</div>', unsafe_allow_html=True)

        zone_id   = st.text_input("Zone ID",  value="zone_1")
        danger    = st.selectbox("위험도", ["High", "Medium", "Low"])
        threshold = st.number_input("체류 시간 임계값 (초)", 1, 120, 10)

        danger_color = {"High": "#ff5050", "Medium": "#ffaa00", "Low": "#00c878"}[danger]

        st.markdown(f"""
        <div style="background:#0f1117;border:1px solid #1e2d45;border-radius:8px;padding:12px;margin-top:8px;">
          <div style="font-size:12px;color:#8896a8;margin-bottom:8px;">현재 Zone 정보</div>
          <div style="display:flex;justify-content:space-between;">
            <span style="color:#8896a8;">ID</span>
            <span style="color:#e2e8f0;">{zone_id}</span>
          </div>
          <div style="display:flex;justify-content:space-between;margin-top:4px;">
            <span style="color:#8896a8;">위험도</span>
            <span style="color:{danger_color};font-weight:600;">{danger}</span>
          </div>
          <div style="display:flex;justify-content:space-between;margin-top:4px;">
            <span style="color:#8896a8;">임계값</span>
            <span style="color:#e2e8f0;">{threshold}초</span>
          </div>
        </div>
        """, unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)

        # ── 설정된 Zone 목록 ──────────────────────────────────────────────────
        st.markdown('<div class="panel">', unsafe_allow_html=True)
        st.markdown("""
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;">
          <div class="panel-title" style="margin-bottom:0;">설정된 Zone</div>
          <div style="background:#00d2c8;color:#0a0d14;width:24px;height:24px;border-radius:6px;
               display:flex;align-items:center;justify-content:center;font-weight:700;">+</div>
        </div>
        """, unsafe_allow_html=True)

        ZONE_PRESETS = [
            ("출입문",    "#ff5050", "high",   5),
            ("미끄럼틀 하단", "#ff5050", "high",  10),
            ("트램폴린",  "#ffaa00", "medium", 15),
            ("볼풀",      "#00c878", "low",    30),
        ]
        if existing:
            for z in existing[:4]:
                rules = z.get("rules", {})
                thresh = rules.get("dwell_threshold_sec", 5)
                dot = "#00c878"
                st.markdown(f"""
                <div style="background:#0f1117;border:1px solid #1e2d45;border-radius:10px;
                     padding:12px;margin-bottom:8px;display:flex;justify-content:space-between;">
                  <div>
                    <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px;">
                      <div style="width:8px;height:8px;border-radius:50%;background:{dot};"></div>
                      <span style="color:#e2e8f0;font-weight:500;">{z['name']}</span>
                    </div>
                    <div style="color:#8896a8;font-size:12px;">임계값: {thresh}초</div>
                  </div>
                  <span style="color:#ff5050;cursor:pointer;">🗑</span>
                </div>
                """, unsafe_allow_html=True)
        else:
            for name, dot, danger_l, thresh in ZONE_PRESETS:
                st.markdown(f"""
                <div style="background:#0f1117;border:1px solid #1e2d45;border-radius:10px;
                     padding:12px;margin-bottom:8px;display:flex;justify-content:space-between;">
                  <div>
                    <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px;">
                      <div style="width:8px;height:8px;border-radius:50%;background:{dot};"></div>
                      <span style="color:#e2e8f0;font-weight:500;">{name}</span>
                    </div>
                    <div style="color:#8896a8;font-size:12px;">위험도: {danger_l} · 임계값: {thresh}초</div>
                  </div>
                  <span style="color:#ff5050;cursor:pointer;">🗑</span>
                </div>
                """, unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

# ── 탭 2: 직접 편집 ───────────────────────────────────────────────────────────
with tab_edit:
    st.markdown('<div class="panel">', unsafe_allow_html=True)
    st.markdown('<div class="panel-title">Zone 직접 편집</div>', unsafe_allow_html=True)

    num_zones = st.number_input("Zone 개수", 1, 10, max(1, len(existing)))
    zones_out = []
    for i in range(int(num_zones)):
        ex = existing[i] if i < len(existing) else {}
        with st.expander(f"Zone {i+1}: {ex.get('name', f'Zone {i+1}')}", expanded=(i == 0)):
            c1, c2 = st.columns(2)
            with c1:
                zid  = st.text_input("zone_id", value=ex.get("zone_id", f"zone_{i+1:02d}"), key=f"eid_{i}")
                zname = st.text_input("name",   value=ex.get("name", f"Zone {i+1}"),        key=f"enm_{i}")
            with c2:
                danger_sel = st.selectbox("위험도", ["High","Medium","Low"], key=f"edg_{i}")
                thresh_sel = st.number_input("체류 임계값(초)", 1, 120, ex.get("rules",{}).get("dwell_threshold_sec",5), key=f"edt_{i}")

            default_pts = ex.get("points", [[0.1,0.1],[0.5,0.1],[0.5,0.5],[0.1,0.5]])
            pts_str = st.text_area("points (x,y 정규화 0~1, 한 줄에 하나)",
                value="\n".join(f"{p[0]},{p[1]}" for p in default_pts), key=f"ept_{i}", height=90)

            points = []
            ok = True
            for line in pts_str.strip().split("\n"):
                line = line.strip()
                if not line: continue
                try:
                    x, y = line.split(",")
                    points.append([round(float(x), 4), round(float(y), 4)])
                except:
                    st.warning(f"⚠️ 파싱 오류: '{line}'")
                    ok = False

            if ok and len(points) >= 3:
                zones_out.append({"zone_id": zid, "name": zname, "type": "polygon",
                                  "points": points, "rules": {"enter_alert": True,
                                  "dwell_threshold_sec": int(thresh_sel)}})

    if zones_out:
        json_str = json.dumps(zones_out, ensure_ascii=False, indent=2)
        col_s, col_d = st.columns(2)
        with col_s:
            if st.button("💾 저장 (세션 적용)"):
                tmp = Path(tempfile.gettempdir()) / "kidcafe" / "zones_edited.json"
                tmp.parent.mkdir(exist_ok=True)
                tmp.write_text(json_str, encoding="utf-8")
                st.session_state.zones_path = str(tmp)
                st.success("✅ 저장 완료!")
        with col_d:
            st.download_button("⬇ JSON 다운로드", json_str, "zones.json", "application/json")
    st.markdown('</div>', unsafe_allow_html=True)

# ── 탭 3: 미리보기 ───────────────────────────────────────────────────────────
with tab_preview:
    st.markdown('<div class="panel">', unsafe_allow_html=True)
    st.markdown('<div class="panel-title">JSON 미리보기</div>', unsafe_allow_html=True)
    preview_zones = load_zones(st.session_state.zones_path)
    if preview_zones:
        st.json(preview_zones)
    else:
        st.info("Zone이 설정되지 않았습니다.")
    st.markdown('</div>', unsafe_allow_html=True)

st.markdown("---")
st.caption("한이음 드림업 프로젝트 2026 · KidCafe Safety AI Team")