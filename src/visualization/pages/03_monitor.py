"""페이지 3 - 실시간 모니터링"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import time
from pathlib import Path

import cv2
import streamlit as st

CURRENT_DIR = Path(__file__).resolve().parent
VIS_DIR = CURRENT_DIR.parent
ROOT_DIR = CURRENT_DIR.parents[2]

sys.path.insert(0, str(VIS_DIR))
sys.path.insert(0, str(ROOT_DIR))

from _style import brand_header, inject_css, sidebar_status, _colors
from dashboard_data import (
    event_get,
    get_recent_events,
    get_video_status,
    get_zone_name_map,
    load_events,
    load_zones,
    resolve_path,
)

try:
    from src.visualization.charts import make_timeline_chart
except Exception:
    make_timeline_chart = None


st.set_page_config(page_title="모니터링 · KidCafe Safety AI", page_icon="📹", layout="wide")
inject_css()

for key, val in {
    "video_path": None,
    "zones_path": "data/zones/sample.json",
    "events_path": "outputs/events.jsonl",
    "csv_path": "outputs/events.csv",
    "summary_path": "outputs/summary.json",
    "result_video_path": "outputs/result.mp4",
    "pipeline_done": False,
    "uploaded_video_name": None,
    "conf_threshold": 0.5,
    "theme_mode": "dark",
}.items():
    if key not in st.session_state:
        st.session_state[key] = val

c = _colors()


def render_compact_kpi(icon, value, label, tone):
    color = {
        "blue": "#12BBD3",
        "yellow": "#F59E0B",
        "green": "#10B981",
        "red": "#EF4444",
    }.get(tone, "#12BBD3")

    return (
        f'<div class="panel" style="padding:26px 28px;">'
        f'  <div style="display:flex;align-items:center;gap:18px;">'
        f'    <div style="width:54px;height:54px;border-radius:14px;background:rgba(18,187,211,.16);'
        f'                display:flex;align-items:center;justify-content:center;color:{color};font-size:25px;">{icon}</div>'
        f'    <div>'
        f'      <div style="font-size:32px;font-weight:900;color:#F8FAFC;line-height:1;">{value}</div>'
        f'      <div style="font-size:17px;color:#A7B4C8;margin-top:8px;">{label}</div>'
        f"    </div>"
        f"  </div>"
        f"</div>"
    )


def render_video_placeholder(message):
    st.markdown(
        f"""
        <div style="height:520px;background:linear-gradient(145deg,#080E1A,#0B1220);
                    border:1px solid #1D3152;border-radius:16px;position:relative;overflow:hidden;">
            <div style="position:absolute;top:28px;left:36px;color:#E5EDF8;font-weight:800;">
                <span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:#64748B;margin-right:10px;"></span>
                Camera 01
                <span style="margin-left:42px;color:#E5EDF8;">FPS: 30</span>
            </div>
            <div style="height:100%;display:flex;align-items:center;justify-content:center;color:{c["TEXT_SUB"]};
                        font-size:18px;font-weight:700;text-align:center;">
                {message}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_opencv_video_viewer(video_path: Path, label: str):
    cap = cv2.VideoCapture(str(video_path))

    if not cap.isOpened():
        st.error(f"{label}을 OpenCV로 열 수 없습니다.")
        return

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0

    if total_frames <= 0:
        cap.release()
        st.error(f"{label}의 프레임 정보를 읽을 수 없습니다.")
        return

    frame_box = st.empty()
    control_left, control_right = st.columns([4, 1])

    with control_left:
        frame_idx = st.slider(
            "프레임",
            min_value=0,
            max_value=max(total_frames - 1, 0),
            value=0,
            step=1,
            key=f"frame_{video_path.name}",
        )

    with control_right:
        play = st.toggle("재생", value=False, key=f"play_{video_path.name}")

    if play:
        start_frame = frame_idx

        for idx in range(start_frame, total_frames):
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ok, frame = cap.read()

            if not ok:
                break

            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            frame_box.image(
                frame_rgb,
                use_column_width=True,
                caption=f"{label} · Frame {idx}/{total_frames - 1}",
            )

            time.sleep(min(1.0 / fps, 0.05))
    else:
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ok, frame = cap.read()

        if ok:
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            frame_box.image(
                frame_rgb,
                use_column_width=True,
                caption=f"{label} · Frame {frame_idx}/{total_frames - 1}",
            )
        else:
            st.error("선택한 프레임을 읽을 수 없습니다.")

    cap.release()


def run_pipeline(frames_limit):
    if not st.session_state.video_path:
        st.error("영상을 먼저 업로드하세요.")
        return

    args = [
        sys.executable,
        "-m",
        "src.main",
        "--video",
        st.session_state.video_path,
        "--zones",
        str(resolve_path(st.session_state.zones_path)),
        "--output",
        str(resolve_path(st.session_state.events_path)),
        "--csv-output",
        str(resolve_path(st.session_state.csv_path)),
        "--summary-output",
        str(resolve_path(st.session_state.summary_path)),
        "--overlay-output",
        str(resolve_path(st.session_state.result_video_path)),
        "--conf",
        str(st.session_state.conf_threshold),
    ]

    if frames_limit > 0:
        args += ["--frames-limit", str(frames_limit)]

    with st.spinner("YOLO + ByteTrack 파이프라인 처리 중..."):
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            cwd=str(ROOT_DIR),
        )

    if result.returncode == 0:
        st.session_state.pipeline_done = True
        st.success("파이프라인 완료. 결과 영상을 다시 불러옵니다.")
        st.rerun()

    st.error("파이프라인 오류")
    with st.expander("오류 보기", expanded=True):
        st.code(" ".join(args), language="bash")
        st.code(result.stderr or result.stdout or "출력 없음")


with st.sidebar:
    brand_header()

    st.markdown("**영상 업로드**")
    uploaded = st.file_uploader(
        "영상 파일",
        type=["mp4", "avi", "mov"],
        label_visibility="collapsed",
    )

    if uploaded:
        tmp = Path(tempfile.gettempdir()) / "kidcafe" / uploaded.name
        tmp.parent.mkdir(exist_ok=True)
        tmp.write_bytes(uploaded.read())

        st.session_state.video_path = str(tmp)
        st.session_state.uploaded_video_name = uploaded.name
        st.success(uploaded.name)

    frames_limit = st.number_input("처리 프레임 수", 0, 10000, 60, 10)

    st.session_state.conf_threshold = st.slider(
        "감지 신뢰도",
        min_value=0.1,
        max_value=1.0,
        value=float(st.session_state.conf_threshold),
        step=0.05,
    )

    if st.button("파이프라인 실행", use_container_width=True):
        run_pipeline(frames_limit)

    st.markdown("---")
    st.session_state.events_path = st.text_input("이벤트 파일", st.session_state.events_path)
    st.session_state.result_video_path = st.text_input("결과 영상", st.session_state.result_video_path)

    sidebar_status()


events = load_events(st.session_state.events_path)
zones = load_zones(st.session_state.zones_path)
zone_name_map = get_zone_name_map(zones)

track_ids = {
    event_get(event, "track_id")
    for event in events
    if event_get(event, "track_id") is not None
}

dwells = sum(1 for event in events if event_get(event, "event_type") == "DWELL")
danger_tracks = {
    event_get(event, "track_id")
    for event in events
    if event_get(event, "event_type") in {"ENTER", "DWELL"}
    and event_get(event, "track_id") is not None
}

result_status = get_video_status(st.session_state.result_video_path)
raw_status = get_video_status(st.session_state.video_path)

top_left, top_right = st.columns([4, 1])

with top_left:
    st.markdown("# 실시간 모니터링")
    st.markdown(
        '<div class="kc-page-subtitle">Vision AI 기반 안전 감시 시스템</div>',
        unsafe_allow_html=True,
    )

with top_right:
    live = result_status["ok"] or raw_status["ok"]
    st.markdown(
        f"""
        <div style="display:flex;justify-content:flex-end;padding-top:16px;">
            <div style="display:flex;align-items:center;gap:10px;border:1px solid rgba(239,68,68,.45);
                        background:rgba(239,68,68,.16);color:#FF5B5B;border-radius:14px;
                        padding:12px 22px;font-weight:900;font-size:17px;">
                <span style="width:10px;height:10px;border-radius:50%;background:#FF4B4B;box-shadow:0 0 10px #FF4B4B;"></span>
                {"LIVE" if live else "STANDBY"}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


k1, k2, k3 = st.columns(3, gap="large")

with k1:
    st.markdown(
        render_compact_kpi("♙", str(len(track_ids)), "현재 감지 인원", "blue"),
        unsafe_allow_html=True,
    )

with k2:
    st.markdown(
        render_compact_kpi("!", str(len(danger_tracks)), "위험구역 내 인원", "yellow"),
        unsafe_allow_html=True,
    )

with k3:
    st.markdown(
        render_compact_kpi("◷", "4.2분", "평균 체류 시간", "blue"),
        unsafe_allow_html=True,
    )

st.markdown("<br>", unsafe_allow_html=True)

video_col, event_col = st.columns([2.35, 1.15], gap="large")

with video_col:
    st.markdown('<div class="panel">', unsafe_allow_html=True)

    ctrl_left, ctrl_right = st.columns([4, 1])

    with ctrl_left:
        st.markdown('<div class="panel-title">실시간 영상</div>', unsafe_allow_html=True)

    with ctrl_right:
        st.markdown(
            """
            <div style="display:flex;justify-content:flex-end;gap:10px;">
                <div style="width:40px;height:40px;border-radius:14px;background:#1B2940;display:flex;align-items:center;justify-content:center;color:#CBD5E1;font-weight:900;">Ⅱ</div>
                <div style="width:40px;height:40px;border-radius:14px;background:#16B8CD;display:flex;align-items:center;justify-content:center;color:#03111B;font-weight:900;">▷</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    if result_status["ok"]:
        render_opencv_video_viewer(result_status["path"], "결과 영상")
        st.caption(f"결과 영상: {result_status['path']} ({result_status['message']})")
    elif raw_status["ok"]:
        render_opencv_video_viewer(raw_status["path"], "원본 영상")
        st.warning("아직 재생 가능한 outputs/result.mp4가 없어 업로드한 원본 영상을 표시합니다.")
    else:
        if result_status["exists"] and not result_status["ok"]:
            render_video_placeholder(
                f"결과 영상 파일은 있지만 재생 가능한 크기가 아닙니다. {result_status['message']}"
            )
            st.warning("파이프라인을 다시 실행해 outputs/result.mp4를 새로 생성하세요.")
        else:
            render_video_placeholder("영상 업로드 후 파이프라인을 실행하면 결과 영상이 표시됩니다.")

    if events and make_timeline_chart is not None:
        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown('<div class="panel-title">이벤트 타임라인</div>', unsafe_allow_html=True)

        try:
            fig = make_timeline_chart(events)
            st.pyplot(fig, use_container_width=True)
        except Exception:
            st.info("타임라인 차트를 표시할 수 없습니다.")

    with st.expander("영상 파일 상태"):
        st.write(
            {
                "result_video_path": str(result_status["path"]) if result_status["path"] else None,
                "result_exists": result_status["exists"],
                "result_size": result_status["size"],
                "result_message": result_status["message"],
                "raw_video_path": str(raw_status["path"]) if raw_status["path"] else None,
                "raw_exists": raw_status["exists"],
                "raw_size": raw_status["size"],
                "raw_message": raw_status["message"],
            }
        )

    st.markdown("</div>", unsafe_allow_html=True)


with event_col:
    st.markdown('<div class="panel" style="min-height:650px;">', unsafe_allow_html=True)
    st.markdown('<div class="panel-title">실시간 이벤트</div>', unsafe_allow_html=True)

    recent = get_recent_events(events, n=12)

    card_style = {
        "DWELL": ("rgba(245,158,11,.13)", "rgba(245,158,11,.42)"),
        "ENTER": ("rgba(16,185,129,.08)", "rgba(29,49,82,.86)"),
        "EXIT": ("rgba(100,116,139,.08)", "rgba(29,49,82,.86)"),
    }

    if recent:
        for i, event in enumerate(recent[:8]):
            etype = event_get(event, "event_type", "UNKNOWN")
            track_id = event_get(event, "track_id", "-")
            zone_id = event_get(event, "zone_id", "-")
            frame_number = event_get(event, "frame_number")

            ago = f"F{frame_number}" if frame_number is not None else f"{i + 1}초"
            zname = zone_name_map.get(str(zone_id), zone_id)

            bg, border = card_style.get(
                etype,
                ("rgba(100,116,139,.08)", "rgba(29,49,82,.86)"),
            )

            st.markdown(
                f"""
                <div style="background:{bg};border:1px solid {border};border-radius:14px;
                            padding:20px;margin-bottom:16px;min-height:90px;">
                    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;">
                        <span class="badge badge-{etype}">{etype}</span>
                        <span style="color:#A7B4C8;font-size:15px;">{ago}</span>
                    </div>
                    <div style="color:#F8FAFC;font-size:19px;font-weight:900;">ID-{track_id}</div>
                    <div style="color:#A7B4C8;font-size:15px;margin-top:4px;">{zname}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
    else:
        st.markdown(
            f"""
            <div style="height:240px;display:flex;align-items:center;justify-content:center;
                        color:{c["TEXT_SUB"]};font-size:16px;text-align:center;">
                이벤트 파일이 비어 있습니다.<br>
                파이프라인 실행 후 events.jsonl이 생성되면 여기에 표시됩니다.
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown("</div>", unsafe_allow_html=True)

st.markdown("---")
st.caption("한이음 드림업 프로젝트 2026 · KidCafe Safety AI Team")