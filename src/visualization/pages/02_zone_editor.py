"""페이지 2 - Zone 편집기"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np
import pandas as pd
import streamlit as st

CURRENT_DIR = Path(__file__).resolve().parent
VIS_DIR = CURRENT_DIR.parent
ROOT_DIR = CURRENT_DIR.parents[2]

sys.path.insert(0, str(VIS_DIR))
sys.path.insert(0, str(ROOT_DIR))

from _style import brand_header, inject_css, sidebar_status, _colors
from dashboard_data import get_zone_name_map, load_zones, resolve_path

st.set_page_config(page_title="Zone 편집 · KidCafe Safety AI", page_icon="🗺️", layout="wide")
inject_css()

for key, val in {
    "video_path": None,
    "zones_path": "data/zones/sample.json",
    "pipeline_done": False,
    "theme_mode": "dark",
}.items():
    if key not in st.session_state:
        st.session_state[key] = val

c = _colors()


def parse_points(text):
    points = []
    errors = []

    for line_no, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()

        if not line:
            continue

        if "," not in line:
            errors.append(f"{line_no}행: 쉼표로 x,y를 구분하세요.")
            continue

        parts = [part.strip() for part in line.split(",")]

        if len(parts) != 2:
            errors.append(f"{line_no}행: 좌표는 x,y 두 값만 입력하세요.")
            continue

        try:
            x = round(float(parts[0]), 4)
            y = round(float(parts[1]), 4)
        except ValueError:
            errors.append(f"{line_no}행: 숫자로 변환할 수 없습니다.")
            continue

        if not 0 <= x <= 1 or not 0 <= y <= 1:
            errors.append(f"{line_no}행: 좌표는 0~1 범위여야 합니다. 입력값: {x}, {y}")
            continue

        points.append([x, y])

    if len(points) < 3:
        errors.append("polygon은 최소 3개 이상의 좌표가 필요합니다.")

    return points, errors


def validate_zone(zone, index):
    errors = []

    zone_id = str(zone.get("zone_id", "")).strip()
    name = str(zone.get("name", "")).strip()
    zone_type = zone.get("type")
    points = zone.get("points", [])
    rules = zone.get("rules", {})

    if not zone_id:
        errors.append(f"Zone {index}: zone_id가 비어 있습니다.")

    if not name:
        errors.append(f"Zone {index}: name이 비어 있습니다.")

    if zone_type != "polygon":
        errors.append(f"Zone {index}: type은 polygon이어야 합니다.")

    if len(points) < 3:
        errors.append(f"Zone {index}: polygon은 최소 3점 이상이어야 합니다.")

    for point_index, point in enumerate(points, start=1):
        if not isinstance(point, list | tuple) or len(point) != 2:
            errors.append(f"Zone {index} point {point_index}: x,y 두 값이 필요합니다.")
            continue

        x, y = point

        if not 0 <= x <= 1 or not 0 <= y <= 1:
            errors.append(f"Zone {index} point {point_index}: 좌표는 0~1 범위여야 합니다.")

    dwell_threshold = rules.get("dwell_threshold_sec")

    if not isinstance(dwell_threshold, int) or dwell_threshold < 1:
        errors.append(f"Zone {index}: dwell_threshold_sec는 1 이상의 정수여야 합니다.")

    return errors


def validate_zones(zones):
    errors = []
    seen_ids = set()

    for index, zone in enumerate(zones, start=1):
        zone_id = str(zone.get("zone_id", "")).strip()

        if zone_id in seen_ids:
            errors.append(f"Zone {index}: zone_id '{zone_id}'가 중복됩니다.")

        seen_ids.add(zone_id)
        errors.extend(validate_zone(zone, index))

    return errors


def zones_to_json(zones):
    return json.dumps(zones, ensure_ascii=False, indent=2)


def get_first_frame(video_path):
    path = resolve_path(video_path)

    if path is None or not path.exists():
        return None

    cap = cv2.VideoCapture(str(path))
    ret, frame = cap.read()
    cap.release()

    if not ret:
        return None

    return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)


def draw_preview_on_frame(frame, zones):
    if frame is None:
        return None

    out = frame.copy()
    h, w = out.shape[:2]

    colors = [
        (18, 187, 211),
        (245, 158, 11),
        (239, 68, 68),
        (16, 185, 129),
        (100, 116, 139),
    ]

    for index, zone in enumerate(zones):
        points = zone.get("points", [])

        if len(points) < 3:
            continue

        color = colors[index % len(colors)]
        pts = np.array(
            [[int(x * w), int(y * h)] for x, y in points],
            dtype=np.int32,
        )

        overlay = out.copy()
        cv2.fillPoly(overlay, [pts], color)
        cv2.addWeighted(overlay, 0.18, out, 0.82, 0, out)
        cv2.polylines(out, [pts], True, color, 2)

        lx, ly = pts[0]
        ly = max(ly - 8, 14)

        cv2.putText(
            out,
            zone.get("name", zone.get("zone_id", "zone")),
            (int(lx), int(ly)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.48,
            color,
            1,
            cv2.LINE_AA,
        )

    return out


def render_help_card():
    st.markdown(
        f"""
        <div style="background:#0B1220;border:1px solid #1D3152;border-radius:14px;padding:20px;">
            <div style="color:#F8FAFC;font-size:18px;font-weight:900;margin-bottom:10px;">좌표 기준</div>
            <div style="color:#A7B4C8;font-size:15px;line-height:1.8;">
                좌표는 영상 크기와 무관한 정규화 좌표입니다.<br>
                왼쪽 위는 <code>0,0</code>, 오른쪽 아래는 <code>1,1</code>입니다.<br>
                polygon은 최소 3점 이상 필요합니다.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


with st.sidebar:
    brand_header()

    st.markdown("**영상 업로드**")
    uploaded = st.file_uploader(
        "영상",
        type=["mp4", "avi", "mov"],
        label_visibility="collapsed",
    )

    if uploaded:
        tmp = Path(tempfile.gettempdir()) / "kidcafe" / uploaded.name
        tmp.parent.mkdir(exist_ok=True)
        tmp.write_bytes(uploaded.read())

        st.session_state.video_path = str(tmp)
        st.success(uploaded.name)

    st.session_state.zones_path = st.text_input("Zone JSON 경로", st.session_state.zones_path)

    sidebar_status()


existing = load_zones(st.session_state.zones_path)
first_frame = get_first_frame(st.session_state.video_path)

st.markdown("# Zone 편집")
st.markdown(
    f'<div style="color:{c["TEXT_SUB"]};font-size:20px;margin-top:-8px;margin-bottom:26px;">'
    f"A 파이프라인에서 사용할 위험구역 좌표를 설정합니다.</div>",
    unsafe_allow_html=True,
)

tab_edit, tab_preview, tab_json = st.tabs(["좌표 입력", "미리보기", "JSON 확인"])

with tab_edit:
    left, right = st.columns([2.1, 1], gap="large")

    with left:
        st.markdown('<div class="panel">', unsafe_allow_html=True)
        st.markdown('<div class="panel-title">Zone 직접 입력</div>', unsafe_allow_html=True)

        num_zones = st.number_input(
            "Zone 개수",
            min_value=1,
            max_value=10,
            value=max(1, len(existing)),
            step=1,
        )

        zones_out = []
        all_errors = []

        for index in range(int(num_zones)):
            ex = existing[index] if index < len(existing) else {}

            expander_title = f"Zone {index + 1}: {ex.get('name', f'Zone {index + 1}')}"
            with st.expander(expander_title, expanded=(index == 0)):
                col1, col2 = st.columns(2)

                with col1:
                    zone_id = st.text_input(
                        "zone_id",
                        value=ex.get("zone_id", f"zone_{index + 1:02d}"),
                        key=f"zone_id_{index}",
                    )
                    name = st.text_input(
                        "name",
                        value=ex.get("name", f"Zone {index + 1}"),
                        key=f"zone_name_{index}",
                    )

                with col2:
                    danger = st.selectbox(
                        "위험도",
                        ["High", "Medium", "Low"],
                        index=["High", "Medium", "Low"].index(ex.get("danger_level", "High"))
                        if ex.get("danger_level", "High") in ["High", "Medium", "Low"]
                        else 0,
                        key=f"danger_{index}",
                    )
                    dwell_threshold = st.number_input(
                        "체류 임계값(초)",
                        min_value=1,
                        max_value=120,
                        value=int(ex.get("rules", {}).get("dwell_threshold_sec", 5)),
                        step=1,
                        key=f"dwell_{index}",
                    )

                default_points = ex.get(
                    "points",
                    [[0.10, 0.10], [0.50, 0.10], [0.50, 0.45], [0.10, 0.45]],
                )

                points_text = st.text_area(
                    "points (x,y 한 줄에 하나)",
                    value="\n".join(f"{point[0]},{point[1]}" for point in default_points),
                    height=120,
                    key=f"points_{index}",
                    help="예: 0.1,0.1 / 0.5,0.1 / 0.5,0.5 / 0.1,0.5",
                )

                points, point_errors = parse_points(points_text)

                if point_errors:
                    for error in point_errors:
                        st.warning(error)
                    all_errors.extend([f"Zone {index + 1}: {error}" for error in point_errors])

                zone = {
                    "zone_id": zone_id.strip(),
                    "name": name.strip(),
                    "type": "polygon",
                    "danger_level": danger,
                    "points": points,
                    "rules": {
                        "enter_alert": True,
                        "dwell_threshold_sec": int(dwell_threshold),
                    },
                }

                zones_out.append(zone)

        schema_errors = validate_zones(zones_out)
        all_errors.extend(schema_errors)
        json_text = zones_to_json(zones_out)

        st.markdown("</div>", unsafe_allow_html=True)

    with right:
        st.markdown('<div class="panel">', unsafe_allow_html=True)
        st.markdown('<div class="panel-title">검증 및 저장</div>', unsafe_allow_html=True)

        if all_errors:
            st.error(f"수정이 필요한 항목 {len(all_errors)}개")
            with st.expander("검증 오류 보기"):
                for error in all_errors:
                    st.write(f"- {error}")
        else:
            st.success("Zone JSON 검증 통과")

        save_col, download_col = st.columns(2)

        with save_col:
            if st.button(
                "세션 저장",
                key="save_zones",
                disabled=bool(all_errors),
                use_container_width=True,
            ):
                tmp = Path(tempfile.gettempdir()) / "kidcafe" / "zones_edited.json"
                tmp.parent.mkdir(exist_ok=True)
                tmp.write_text(json_text, encoding="utf-8")

                st.session_state.zones_path = str(tmp)
                st.success("저장 완료")

        with download_col:
            st.download_button(
                "JSON 다운로드",
                json_text,
                "zones.json",
                "application/json",
                disabled=bool(all_errors),
                use_container_width=True,
            )

        st.markdown("<br>", unsafe_allow_html=True)
        render_help_card()
        st.markdown("</div>", unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)

        st.markdown('<div class="panel">', unsafe_allow_html=True)
        st.markdown('<div class="panel-title">현재 Zone 목록</div>', unsafe_allow_html=True)

        if zones_out:
            zone_rows = [
                {
                    "zone_id": zone["zone_id"],
                    "name": zone["name"],
                    "danger": zone["danger_level"],
                    "points": len(zone["points"]),
                    "dwell_sec": zone["rules"]["dwell_threshold_sec"],
                }
                for zone in zones_out
            ]
            st.dataframe(
                pd.DataFrame(zone_rows),
                hide_index=True,
                use_container_width=True,
                height=240,
            )
        else:
            st.info("Zone이 없습니다.")

        st.markdown("</div>", unsafe_allow_html=True)

with tab_preview:
    preview_left, preview_right = st.columns([2, 1], gap="large")

    with preview_left:
        st.markdown('<div class="panel">', unsafe_allow_html=True)
        st.markdown('<div class="panel-title">영상 위 Zone 미리보기</div>', unsafe_allow_html=True)

        preview_zones = zones_out if "zones_out" in locals() and zones_out else existing
        frame_preview = draw_preview_on_frame(first_frame, preview_zones)

        if frame_preview is not None:
            st.image(frame_preview, use_column_width=True)
        elif first_frame is not None:
            st.image(first_frame, use_column_width=True, caption="영상 첫 프레임")
            st.info("표시할 Zone 좌표가 없습니다.")
        else:
            st.markdown(
                f"""
                <div style="height:420px;background:#0B1220;border:1px dashed #1D3152;
                            border-radius:16px;display:flex;align-items:center;justify-content:center;
                            color:{c["TEXT_SUB"]};font-size:17px;text-align:center;">
                    영상을 업로드하면 첫 프레임 위에 Zone을 확인할 수 있습니다.
                </div>
                """,
                unsafe_allow_html=True,
            )

        st.markdown("</div>", unsafe_allow_html=True)

    with preview_right:
        st.markdown('<div class="panel">', unsafe_allow_html=True)
        st.markdown('<div class="panel-title">Zone 이름 매핑</div>', unsafe_allow_html=True)

        preview_zones = zones_out if "zones_out" in locals() and zones_out else existing
        zone_map = get_zone_name_map(preview_zones)

        if zone_map:
            for zone_id, name in zone_map.items():
                st.markdown(
                    f"""
                    <div class="status-row">
                        <span class="status-label">{zone_id}</span>
                        <span class="status-cyan">{name}</span>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
        else:
            st.info("Zone이 없습니다.")

        st.markdown("</div>", unsafe_allow_html=True)

with tab_json:
    st.markdown('<div class="panel">', unsafe_allow_html=True)
    st.markdown('<div class="panel-title">JSON 미리보기</div>', unsafe_allow_html=True)

    preview_zones = zones_out if "zones_out" in locals() and zones_out else existing

    if preview_zones:
        st.code(zones_to_json(preview_zones), language="json")
    else:
        st.info("Zone이 설정되지 않았습니다.")

    st.markdown("</div>", unsafe_allow_html=True)

st.markdown("---")
st.caption("한이음 드림업 프로젝트 2026 · KidCafe Safety AI Team")