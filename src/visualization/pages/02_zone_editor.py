"""페이지 2 - Zone 편집기"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import cv2
import streamlit as st

CURRENT_DIR = Path(__file__).resolve().parent
VIS_DIR = CURRENT_DIR.parent
ROOT_DIR = CURRENT_DIR.parents[2]

sys.path.insert(0, str(VIS_DIR))
sys.path.insert(0, str(ROOT_DIR))

from _style import brand_header, inject_css, sidebar_status, _colors

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


def load_zones(path):
    p = Path(path)
    if not p.exists():
        return []

    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:
        st.error(f"Zone JSON을 읽을 수 없습니다: {exc}")
        return []

    if isinstance(data, dict) and "zones" in data:
        return data["zones"]
    if isinstance(data, list):
        return data

    st.warning("Zone JSON 형식이 올바르지 않습니다. 리스트 또는 {'zones': [...]} 형식을 사용하세요.")
    return []


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

        parts = [p.strip() for p in line.split(",")]

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

    zone_id = zone.get("zone_id", "").strip()
    name = zone.get("name", "").strip()
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
        if len(point) != 2:
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

    for i, zone in enumerate(zones, start=1):
        zone_id = zone.get("zone_id", "").strip()

        if zone_id in seen_ids:
            errors.append(f"Zone {i}: zone_id '{zone_id}'가 중복됩니다.")

        seen_ids.add(zone_id)
        errors.extend(validate_zone(zone, i))

    return errors


def zones_to_json(zones):
    return json.dumps(zones, ensure_ascii=False, indent=2)


def get_first_frame(video_path):
    if not video_path or not Path(video_path).exists():
        return None

    cap = cv2.VideoCapture(video_path)
    ret, frame = cap.read()
    cap.release()

    if not ret:
        return None

    return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)


def draw_preview_on_frame(frame, zones):
    import cv2
    import numpy as np

    if frame is None:
        return None

    out = frame.copy()
    h, w = out.shape[:2]
    colors = [
        (18, 187, 211),
        (245, 158, 11),
        (239, 68, 68),
        (16, 185, 129),
        (14, 165, 233),
    ]

    for i, zone in enumerate(zones):
        points = zone.get("points", [])

        if len(points) < 3:
            continue

        color = colors[i % len(colors)]
        pts = np.array([[int(x * w), int(y * h)] for x, y in points], dtype=np.int32)

        overlay = out.copy()
        cv2.fillPoly(overlay, [pts], color)
        cv2.addWeighted(overlay, 0.18, out, 0.82, 0, out)
        cv2.polylines(out, [pts], True, color, 2)

        lx, ly = pts[0]
        ly = max(ly - 8, 14)
        cv2.putText(
            out,
            zone.get("name", zone.get("zone_id", "zone")),
            (lx, ly),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.48,
            color,
            1,
            cv2.LINE_AA,
        )

    return out


with st.sidebar:
    brand_header()

    st.markdown("**영상 업로드**")
    up = st.file_uploader("영상", type=["mp4", "avi", "mov"], label_visibility="collapsed")

    if up:
        tmp = Path(tempfile.gettempdir()) / "kidcafe" / up.name
        tmp.parent.mkdir(exist_ok=True)
        tmp.write_bytes(up.read())
        st.session_state.video_path = str(tmp)
        st.success(up.name)

    st.session_state.zones_path = st.text_input("Zone JSON 경로", st.session_state.zones_path)
    sidebar_status()

st.markdown("# Zone 편집")
st.markdown(
    '<div class="kc-page-subtitle">정규화 좌표값으로 위험 구역을 설정합니다. 좌표 범위는 0~1입니다.</div>',
    unsafe_allow_html=True,
)

existing = load_zones(st.session_state.zones_path)
first_frame = get_first_frame(st.session_state.video_path)

tab_edit, tab_preview, tab_help = st.tabs(["좌표 입력", "미리보기", "좌표 가이드"])

with tab_edit:
    left, right = st.columns([2.1, 1], gap="large")

    with left:
        st.markdown('<div class="panel">', unsafe_allow_html=True)
        st.markdown('<div class="panel-title">Zone 직접 입력</div>', unsafe_allow_html=True)

        num_zones = st.number_input("Zone 개수", 1, 10, max(1, len(existing)))
        zones_out = []
        all_errors = []

        for i in range(int(num_zones)):
            ex = existing[i] if i < len(existing) else {}

            with st.expander(f"Zone {i + 1}: {ex.get('name', f'Zone {i + 1}')}", expanded=(i == 0)):
                co1, co2 = st.columns(2)

                with co1:
                    zid = st.text_input(
                        "zone_id",
                        value=ex.get("zone_id", f"zone_{i + 1:02d}"),
                        key=f"eid_{i}",
                    )
                    zname = st.text_input(
                        "name",
                        value=ex.get("name", f"Zone {i + 1}"),
                        key=f"enm_{i}",
                    )

                with co2:
                    danger = st.selectbox(
                        "위험도",
                        ["High", "Medium", "Low"],
                        index=["High", "Medium", "Low"].index(ex.get("danger_level", "High"))
                        if ex.get("danger_level", "High") in ["High", "Medium", "Low"]
                        else 0,
                        key=f"edg_{i}",
                    )
                    dwell_threshold = st.number_input(
                        "체류 임계값(초)",
                        1,
                        120,
                        int(ex.get("rules", {}).get("dwell_threshold_sec", 5)),
                        key=f"edt_{i}",
                    )

                default_points = ex.get(
                    "points",
                    [[0.1, 0.1], [0.5, 0.1], [0.5, 0.5], [0.1, 0.5]],
                )

                pts_str = st.text_area(
                    "points (x,y 한 줄에 하나)",
                    value="\n".join(f"{p[0]},{p[1]}" for p in default_points),
                    key=f"ept_{i}",
                    height=110,
                    help="예: 0.1,0.1 / 0.5,0.1 / 0.5,0.5 / 0.1,0.5",
                )

                points, errors = parse_points(pts_str)

                for error in errors:
                    st.warning(error)

                if errors:
                    all_errors.extend([f"Zone {i + 1}: {e}" for e in errors])

                zones_out.append(
                    {
                        "zone_id": zid.strip(),
                        "name": zname.strip(),
                        "type": "polygon",
                        "danger_level": danger,
                        "points": points,
                        "rules": {
                            "enter_alert": True,
                            "dwell_threshold_sec": int(dwell_threshold),
                        },
                    }
                )

        schema_errors = validate_zones(zones_out)
        all_errors.extend(schema_errors)
        jstr = zones_to_json(zones_out)

        st.markdown("</div>", unsafe_allow_html=True)

    with right:
        st.markdown('<div class="panel">', unsafe_allow_html=True)
        st.markdown('<div class="panel-title">저장 상태</div>', unsafe_allow_html=True)

        if all_errors:
            st.error(f"수정이 필요한 항목 {len(all_errors)}개")
            with st.expander("검증 오류 보기"):
                for error in all_errors:
                    st.write(f"- {error}")
        else:
            st.success("Zone JSON 검증 통과")

        save_col, download_col = st.columns(2)

        with save_col:
            if st.button("세션 저장", key="save_manual", disabled=bool(all_errors), use_container_width=True):
                tmp = Path(tempfile.gettempdir()) / "kidcafe" / "zones_edited.json"
                tmp.parent.mkdir(exist_ok=True)
                tmp.write_text(jstr, encoding="utf-8")
                st.session_state.zones_path = str(tmp)
                st.success("저장되었습니다.")

        with download_col:
            st.download_button(
                "JSON",
                jstr,
                "zones.json",
                "application/json",
                disabled=bool(all_errors),
                use_container_width=True,
            )

        st.markdown(
            """
            <div class="inner-card" style="margin-top:18px;">
                <div style="color:#A7B4C8;font-size:14px;margin-bottom:10px;">A 모듈 연동 스키마</div>
                <div style="color:#F8FAFC;font-size:15px;line-height:1.8;">
                    zone_id, name, type=polygon, points,<br>
                    rules.enter_alert, rules.dwell_threshold_sec
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.markdown("</div>", unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown('<div class="panel">', unsafe_allow_html=True)
        st.markdown('<div class="panel-title">현재 정의된 Zone</div>', unsafe_allow_html=True)

        if zones_out:
            zone_rows = [
                {
                    "zone_id": z["zone_id"],
                    "name": z["name"],
                    "danger": z["danger_level"],
                    "points": len(z["points"]),
                    "dwell_sec": z["rules"]["dwell_threshold_sec"],
                }
                for z in zones_out
            ]
            st.dataframe(zone_rows, hide_index=True, use_container_width=True)
        else:
            st.info("Zone이 없습니다.")

        st.markdown("</div>", unsafe_allow_html=True)

with tab_preview:
    preview_left, preview_right = st.columns([3, 2], gap="large")

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
                """
                <div style="height:420px;background:#0B1220;border:1px dashed #1D3152;
                            border-radius:16px;display:flex;align-items:center;justify-content:center;
                            color:#A7B4C8;font-size:18px;">
                    영상을 업로드하면 첫 프레임 위에 Zone을 확인할 수 있습니다
                </div>
                """,
                unsafe_allow_html=True,
            )

        st.markdown("</div>", unsafe_allow_html=True)

    with preview_right:
        st.markdown('<div class="panel">', unsafe_allow_html=True)
        st.markdown('<div class="panel-title">JSON 미리보기</div>', unsafe_allow_html=True)

        preview_zones = zones_out if "zones_out" in locals() and zones_out else existing

        if preview_zones:
            st.code(zones_to_json(preview_zones), language="json")
        else:
            st.info("Zone이 설정되지 않았습니다.")

        st.markdown("</div>", unsafe_allow_html=True)

with tab_help:
    st.markdown('<div class="panel">', unsafe_allow_html=True)
    st.markdown('<div class="panel-title">좌표 입력 방법</div>', unsafe_allow_html=True)

    st.markdown(
        """
        <div style="color:#D7E2F1;line-height:1.9;font-size:17px;">
            <b>좌표는 영상 크기와 무관한 정규화 좌표입니다.</b><br>
            왼쪽 위는 <code>0,0</code>, 오른쪽 아래는 <code>1,1</code> 입니다.<br>
            polygon은 최소 3점이 필요하며, 각 줄에 <code>x,y</code> 형식으로 입력합니다.
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.code(
        """0.10,0.10
0.50,0.10
0.50,0.45
0.10,0.45""",
        language="text",
    )

    st.markdown("</div>", unsafe_allow_html=True)

st.markdown("---")
st.caption("한이음 드림업 프로젝트 2026 · KidCafe Safety AI Team")