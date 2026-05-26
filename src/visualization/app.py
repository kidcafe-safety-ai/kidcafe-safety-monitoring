"""
KidCafe Safety AI - 메인 진입점
실행: streamlit run src/visualization/app.py
"""

from __future__ import annotations

import streamlit as st

st.set_page_config(
    page_title="KidCafe Safety AI",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# 세션 전역 초기화
# 모든 페이지가 같은 경로와 설정값을 공유한다.
defaults = {
    # A 입력/산출물
    "video_path": None,
    "zones_path": "data/zones/sample.json",
    "events_path": "outputs/events.jsonl",
    "result_video_path": "outputs/result.mp4",

    # B 산출물
    "csv_path": "outputs/events.csv",
    "summary_path": "outputs/summary.json",

    # 파이프라인/업로드 상태
    "pipeline_done": False,
    "uploaded_video_name": None,

    # 모델/이벤트 설정
    "conf_threshold": 0.5,
    "track_stability": 0.60,
    "dwell_sec": 10,

    # 알림 설정
    "alert_enter": True,
    "alert_dwell": True,
    "alert_daily": True,
    "alert_weekly": False,

    # UI 설정
    "theme_mode": "dark",
}

for key, val in defaults.items():
    if key not in st.session_state:
        st.session_state[key] = val

st.switch_page("pages/01_home.py")