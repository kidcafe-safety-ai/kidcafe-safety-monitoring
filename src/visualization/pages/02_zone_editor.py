"""페이지 2 — Zone 편집기"""
import json, tempfile
from pathlib import Path
import sys

import cv2
import numpy as np
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))
from _style import inject_css, sidebar_status, _colors

st.set_page_config(page_title="Zone 편집 · KidCafe Safety AI", page_icon="🗺️", layout="wide")
inject_css()

for key, val in {"video_path": None, "zones_path": "data/zones/sample.json",
                 "pipeline_done": False, "theme_mode": "dark"}.items():
    if key not in st.session_state:
        st.session_state[key] = val

c = _colors()

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
    up = st.file_uploader("영상", type=["mp4","avi","mov"], label_visibility="collapsed")
    if up:
        tmp = Path(tempfile.gettempdir()) / "kidcafe" / up.name
        tmp.parent.mkdir(exist_ok=True)
        tmp.write_bytes(up.read())
        st.session_state.video_path = str(tmp)
        st.success(f"✅ {up.name}")
    sidebar_status()

# ── 헤더 ──────────────────────────────────────────────────────────────────────
st.markdown("# Zone 편집")
st.markdown(f'<p style="color:{c["TEXT_SUB"]};margin-top:-12px;">위험 구역을 설정하고 관리합니다</p>',
            unsafe_allow_html=True)

def load_zones(path):
    p = Path(path)
    if not p.exists(): return []
    with open(p, encoding="utf-8") as f: return json.load(f)

existing = load_zones(st.session_state.zones_path)

tab_draw, tab_edit, tab_preview = st.tabs(["🎨 그리기", "✏️ 편집", "👁️ 미리보기"])

# ── 탭 1: 캔버스 그리기 ───────────────────────────────────────────────────────
with tab_draw:
    main_col, side_col = st.columns([2, 1], gap="medium")
    with main_col:
        st.markdown('<div class="panel">', unsafe_allow_html=True)
        first_frame = None
        vpath = st.session_state.get("video_path")
        if vpath and Path(vpath).exists():
            cap = cv2.VideoCapture(vpath)
            ret, frame = cap.read()
            cap.release()
            if ret: first_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        try:
            from streamlit_drawable_canvas import st_canvas
            from PIL import Image
            canvas_w = 680
            bg_img = None
            canvas_h = 400
            if first_frame is not None:
                h, w = first_frame.shape[:2]
                scale = canvas_w / w
                bg_img = Image.fromarray(first_frame).resize((canvas_w, int(h*scale)))
                canvas_h = int(h*scale)

            result = st_canvas(
                fill_color="rgba(0,210,200,0.15)",
                stroke_width=2, stroke_color="#00d2c8",
                background_color=c["CARD"], background_image=bg_img,
                height=canvas_h, width=canvas_w,
                drawing_mode="polygon", key="zone_canvas",
            )
            st.caption("클릭으로 점 추가 → 첫 번째 점 클릭으로 polygon 완성")

            zones_from_canvas = []
            if result.json_data and result.json_data.get("objects"):
                for i, obj in enumerate(result.json_data["objects"]):
                    if obj.get("type") != "path": continue
                    points = []
                    for cmd in obj.get("path", []):
                        if cmd[0] in ("M","L") and len(cmd) >= 3:
                            points.append([round(cmd[1]/canvas_w, 4), round(cmd[2]/canvas_h, 4)])
                    if len(points) >= 3:
                        zones_from_canvas.append({"zone_id": f"zone_{i+1:02d}", "name": f"Zone {i+1}",
                            "type":"polygon","points":points,
                            "rules":{"enter_alert":True,"dwell_threshold_sec":5}})
            if zones_from_canvas:
                st.success(f"✅ {len(zones_from_canvas)}개 Zone 감지됨")
                _j = json.dumps(zones_from_canvas, ensure_ascii=False, indent=2)
                col_s, col_d = st.columns(2)
                with col_s:
                    if st.button("💾 세션 저장", key="save_canvas"):
                        tmp = Path(tempfile.gettempdir()) / "kidcafe" / "zones_canvas.json"
                        tmp.parent.mkdir(exist_ok=True); tmp.write_text(_j, encoding="utf-8")
                        st.session_state.zones_path = str(tmp); st.success("✅ 저장!")
                with col_d:
                    st.download_button("⬇ JSON", _j, "zones.json", "application/json", key="dl_canvas")
        except ImportError:
            if first_frame is not None:
                st.image(first_frame, use_column_width=True, caption="영상 첫 프레임 (Zone 좌표 참고용)")
            else:
                st.markdown(
                    f'<div style="height:360px;background:{c["BG_MAIN"]};border:2px dashed {c["BORDER"]};'
                    f'border-radius:14px;display:flex;flex-direction:column;align-items:center;'
                    f'justify-content:center;gap:12px;">'
                    f'  <div style="font-size:40px;">📹</div>'
                    f'  <div style="color:{c["TEXT_SUB"]};">영상을 업로드하거나 카메라를 선택하세요</div>'
                    f'  <div style="color:{c["TEXT_SUB"]};font-size:12px;">클릭하여 폴리곤 그리기</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
            st.info("💡 `pip install streamlit-drawable-canvas` 설치 시 직접 그리기 가능")
        st.markdown('</div>', unsafe_allow_html=True)

    with side_col:
        st.markdown('<div class="panel">', unsafe_allow_html=True)
        st.markdown('<div class="panel-title">Zone 설정</div>', unsafe_allow_html=True)
        zone_id  = st.text_input("Zone ID",  value="zone_1")
        danger   = st.selectbox("위험도", ["High","Medium","Low"])
        threshold= st.number_input("체류 시간 임계값 (초)", 1, 120, 10)
        dcolor   = {"High":"#ff5050","Medium":"#ffaa00","Low":"#00c878"}[danger]
        st.markdown(
            f'<div style="background:{c["BG_MAIN"]};border:1px solid {c["BORDER"]};border-radius:10px;'
            f'padding:12px;margin-top:8px;">'
            f'  <div style="font-size:12px;color:{c["TEXT_SUB"]};margin-bottom:8px;">현재 Zone 정보</div>'
            f'  <div style="display:flex;justify-content:space-between;">'
            f'    <span style="color:{c["TEXT_SUB"]};">ID</span><span style="color:{c["TEXT"]};">{zone_id}</span></div>'
            f'  <div style="display:flex;justify-content:space-between;margin-top:4px;">'
            f'    <span style="color:{c["TEXT_SUB"]};">위험도</span>'
            f'    <span style="color:{dcolor};font-weight:600;">{danger}</span></div>'
            f'  <div style="display:flex;justify-content:space-between;margin-top:4px;">'
            f'    <span style="color:{c["TEXT_SUB"]};">임계값</span>'
            f'    <span style="color:{c["TEXT"]};">{threshold}초</span></div>'
            f'</div>',
            unsafe_allow_html=True,
        )
        st.markdown('</div>', unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown('<div class="panel">', unsafe_allow_html=True)
        st.markdown(
            f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;">'
            f'  <div class="panel-title" style="margin-bottom:0;">설정된 Zone</div>'
            f'  <div style="background:#00d2c8;color:#0a0d14;width:24px;height:24px;'
            f'       border-radius:6px;display:flex;align-items:center;justify-content:center;font-weight:700;">+</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
        PRESETS = [("출입문","#ff5050",5),("미끄럼틀 하단","#ff5050",10),
                   ("트램폴린","#ffaa00",15),("볼풀","#00c878",30)]
        src = existing[:4] if existing else []
        for i, item in enumerate(src or PRESETS):
            if existing:
                name = item["name"]; thresh = item.get("rules",{}).get("dwell_threshold_sec",5)
                dot = "#00c878"
            else:
                name, dot, thresh = item
            st.markdown(
                f'<div style="background:{c["BG_MAIN"]};border:1px solid {c["BORDER"]};border-radius:10px;'
                f'padding:12px;margin-bottom:8px;display:flex;justify-content:space-between;">'
                f'  <div>'
                f'    <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px;">'
                f'      <div style="width:8px;height:8px;border-radius:50%;background:{dot};"></div>'
                f'      <span style="color:{c["TEXT"]};font-weight:500;">{name}</span></div>'
                f'    <div style="color:{c["TEXT_SUB"]};font-size:12px;">임계값: {thresh}초</div>'
                f'  </div>'
                f'  <span style="color:#ff5050;">🗑</span>'
                f'</div>',
                unsafe_allow_html=True,
            )
        st.markdown('</div>', unsafe_allow_html=True)

# ── 탭 2: 직접 편집 ───────────────────────────────────────────────────────────
with tab_edit:
    st.markdown('<div class="panel">', unsafe_allow_html=True)
    st.markdown('<div class="panel-title">Zone 직접 편집</div>', unsafe_allow_html=True)
    num_zones = st.number_input("Zone 개수", 1, 10, max(1, len(existing)))
    zones_out = []
    for i in range(int(num_zones)):
        ex = existing[i] if i < len(existing) else {}
        with st.expander(f"Zone {i+1}: {ex.get('name', f'Zone {i+1}')}", expanded=(i==0)):
            co1, co2 = st.columns(2)
            with co1:
                zid   = st.text_input("zone_id", value=ex.get("zone_id",f"zone_{i+1:02d}"), key=f"eid_{i}")
                zname = st.text_input("name",    value=ex.get("name",f"Zone {i+1}"),        key=f"enm_{i}")
            with co2:
                dg   = st.selectbox("위험도", ["High","Medium","Low"], key=f"edg_{i}")
                dthr = st.number_input("체류 임계값(초)", 1, 120,
                                       ex.get("rules",{}).get("dwell_threshold_sec",5), key=f"edt_{i}")
            default_pts = ex.get("points", [[0.1,0.1],[0.5,0.1],[0.5,0.5],[0.1,0.5]])
            pts_str = st.text_area("points (x,y 한 줄에 하나)",
                value="\n".join(f"{p[0]},{p[1]}" for p in default_pts), key=f"ept_{i}", height=90)
            points, ok = [], True
            for line in pts_str.strip().split("\n"):
                line = line.strip()
                if not line: continue
                try:
                    x, y = line.split(",")
                    points.append([round(float(x),4), round(float(y),4)])
                except:
                    st.warning(f"⚠️ 파싱 오류: '{line}'"); ok = False
            if ok and len(points) >= 3:
                zones_out.append({"zone_id":zid,"name":zname,"type":"polygon","points":points,
                                  "rules":{"enter_alert":True,"dwell_threshold_sec":int(dthr)}})
    if zones_out:
        jstr = json.dumps(zones_out, ensure_ascii=False, indent=2)
        cs, cd = st.columns(2)
        with cs:
            if st.button("💾 세션 저장", key="save_manual"):
                tmp = Path(tempfile.gettempdir()) / "kidcafe" / "zones_edited.json"
                tmp.parent.mkdir(exist_ok=True); tmp.write_text(jstr, encoding="utf-8")
                st.session_state.zones_path = str(tmp); st.success("✅ 저장!")
        with cd:
            st.download_button("⬇ JSON", jstr, "zones.json", "application/json")
    st.markdown('</div>', unsafe_allow_html=True)

# ── 탭 3: 미리보기 ───────────────────────────────────────────────────────────
with tab_preview:
    st.markdown('<div class="panel">', unsafe_allow_html=True)
    st.markdown('<div class="panel-title">JSON 미리보기</div>', unsafe_allow_html=True)
    preview = load_zones(st.session_state.zones_path)
    if preview: st.json(preview)
    else: st.info("Zone이 설정되지 않았습니다.")
    st.markdown('</div>', unsafe_allow_html=True)

st.markdown("---")
st.caption("한이음 드림업 프로젝트 2026 · KidCafe Safety AI Team")