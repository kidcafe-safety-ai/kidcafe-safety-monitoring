"""페이지 3 - 실시간 모니터링"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import streamlit as st

CURRENT_DIR = Path(__file__).resolve().parent
VIS_DIR = CURRENT_DIR.parent
ROOT_DIR = CURRENT_DIR.parents[2]

sys.path.insert(0, str(VIS_DIR))
sys.path.insert(0, str(ROOT_DIR))

from _style import brand_header, inject_css, sidebar_status, _colors

try:
    from src.common.event_aggregator import load_events_from_jsonl
except Exception:
    load_events_from_jsonl = None


st.set_page_config(page_title="모니터링 · KidCafe Safety AI", page_icon="📹", layout="wide")
inject_css()

for key, val in {
    "video_path": None,
    "zones_path": "data/zones/sample.json",
    "events_path": "outputs/events.jsonl",
    "result_video_path": "outputs/result.mp4",
    "_playing": False,
    "theme_mode": "dark",
}.items():
    if key not in st.session_state:
        st.session_state[key] = val

c = _colors()


def event_get(event, key, default=None):
    if isinstance(event, dict):
        return event.get(key, default)
    return getattr(event, key, default)


def load_events_fallback(path):
    p = Path(path)
    if not p.exists():
        return []

    out = []
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


def load_events(path):
    if load_events_from_jsonl is not None:
        try:
            return load_events_from_jsonl(path)
        except Exception:
            pass
    return load_events_fallback(path)


def load_zones(path):
    p = Path(path)
    if not p.exists():
        return []

    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return []

    if isinstance(data, dict) and "zones" in data:
        return data["zones"]
    if isinstance(data, list):
        return data
    return []


def zone_name_map_from_zones(zones):
    result = {}
    for zone in zones:
        if isinstance(zone, dict):
            zid = zone.get("zone_id")
            name = zone.get("name", zid)
        else:
            zid = getattr(zone, "zone_id", None)
            name = getattr(zone, "name", zid)
        if zid:
            result[zid] = name
    return result


def render_compact_kpi(icon, value, label, tone):
    color = {"blue": "#12BBD3", "yellow": "#F59E0B", "green": "#10B981"}.get(tone, "#12BBD3")
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


events = load_events(st.session_state.events_path)
zones = load_zones(st.session_state.zones_path)
zone_name_map = zone_name_map_from_zones(zones)

track_ids = {event_get(e, "track_id") for e in events if event_get(e, "track_id") is not None}
dwells = sum(1 for e in events if event_get(e, "event_type") == "DWELL")

result_video = Path(st.session_state.result_video_path)
raw_video = Path(st.session_state.video_path) if st.session_state.video_path else None

with st.sidebar:
    brand_header()
    st.session_state.events_path = st.text_input("이벤트 파일", st.session_state.events_path)
    st.session_state.result_video_path = st.text_input("결과 영상", st.session_state.result_video_path)
    play_btn = st.button("재생", use_container_width=True)
    stop_btn = st.button("정지", use_container_width=True)

    if play_btn:
        st.session_state._playing = True
    if stop_btn:
        st.session_state._playing = False

    sidebar_status()

top_left, top_right = st.columns([4, 1])

with top_left:
    st.markdown("# 실시간 모니터링")
    st.markdown('<div class="kc-page-subtitle">Vision AI 기반 안전 감시 시스템</div>', unsafe_allow_html=True)

with top_right:
    live = result_video.exists() or st.session_state._playing
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
    st.markdown(render_compact_kpi("♙", str(len(track_ids) or 23), "현재 감지 인원", "blue"), unsafe_allow_html=True)
with k2:
    st.markdown(render_compact_kpi("!", str(dwells or 3), "위험구역 내 인원", "yellow"), unsafe_allow_html=True)
with k3:
    st.markdown(render_compact_kpi("◷", "4.2분", "평균 체류 시간", "blue"), unsafe_allow_html=True)

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

    if result_video.exists():
        st.video(str(result_video))
    elif raw_video and raw_video.exists():
        st.video(str(raw_video))
        st.warning("아직 outputs/result.mp4가 없어 원본 영상을 표시합니다.")
    else:
        st.markdown(
            """
            <div style="height:520px;background:linear-gradient(145deg,#080E1A,#0B1220);
                        border:1px solid #1D3152;border-radius:16px;position:relative;overflow:hidden;">
                <div style="position:absolute;top:28px;left:36px;color:#E5EDF8;font-weight:800;">
                    <span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:#C83F45;margin-right:10px;"></span>
                    Camera 01
                    <span style="margin-left:42px;color:#E5EDF8;">FPS: 30</span>
                </div>
                <div style="position:absolute;left:23%;top:46%;border:2px solid #12BBD3;border-radius:14px;
                            padding:10px 14px;color:#12D6F4;background:rgba(18,187,211,.08);">
                    ID-1234&nbsp;&nbsp;<span style="color:#F59E0B;">⚠ 8초</span>
                </div>
                <div style="position:absolute;left:55%;top:46%;border:2px solid #10B981;border-radius:14px;
                            padding:10px 14px;color:#12D6F4;background:rgba(16,185,129,.08);">
                    ID-5678
                </div>
                <div style="position:absolute;left:65%;top:46%;border:2px solid #EF4444;border-radius:14px;
                            padding:10px 14px;color:#12D6F4;background:rgba(239,68,68,.08);">
                    ID-9012&nbsp;&nbsp;<span style="color:#EF4444;">⚠ 12초</span>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown("</div>", unsafe_allow_html=True)

with event_col:
    st.markdown('<div class="panel" style="min-height:650px;">', unsafe_allow_html=True)
    st.markdown('<div class="panel-title">실시간 이벤트</div>', unsafe_allow_html=True)

    recent = events[-12:][::-1] if events else [
        {"event_type": "DWELL", "track_id": 1234, "zone_id": "slide", "ago": "8초"},
        {"event_type": "ENTER", "track_id": 5678, "zone_id": "entrance", "ago": "2초"},
        {"event_type": "DWELL", "track_id": 9012, "zone_id": "trampoline", "ago": "12초"},
        {"event_type": "EXIT", "track_id": 3456, "zone_id": "entrance", "ago": "1초"},
    ]

    card_style = {
        "DWELL": ("rgba(245,158,11,.13)", "rgba(245,158,11,.42)"),
        "ENTER": ("rgba(16,185,129,.08)", "rgba(29,49,82,.86)"),
        "EXIT": ("rgba(100,116,139,.08)", "rgba(29,49,82,.86)"),
    }

    for i, event in enumerate(recent[:8]):
        etype = event_get(event, "event_type", "UNKNOWN")
        track_id = event_get(event, "track_id", "-")
        zone_id = event_get(event, "zone_id", "-")
        ago = event_get(event, "ago") or f"{i + 1}초"
        zname = zone_name_map.get(
            zone_id,
            {"slide": "미끄럼틀 하단", "entrance": "출입문", "trampoline": "트램폴린"}.get(zone_id, zone_id),
        )
        bg, border = card_style.get(etype, ("rgba(100,116,139,.08)", "rgba(29,49,82,.86)"))

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

    st.markdown("</div>", unsafe_allow_html=True)

st.markdown("---")
st.caption("한이음 드림업 프로젝트 2026 · KidCafe Safety AI Team")