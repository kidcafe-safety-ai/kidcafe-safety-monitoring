"""
KidCafe Safety AI — 메인 진입점
실행: streamlit run src/visualization/app.py
"""
import streamlit as st

st.set_page_config(
    page_title="KidCafe Safety AI",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# 세션 전역 초기화
defaults = {
    "video_path":           None,
    "zones_path":           "data/zones/sample.json",
    "events_path":          "outputs/events.jsonl",
    "pipeline_done":        False,
    "uploaded_video_name":  None,
    "conf_threshold":       0.75,
    "track_stability":      0.60,
    "dwell_sec":            10,
    "alert_enter":          True,
    "alert_dwell":          True,
    "alert_daily":          True,
    "alert_weekly":         False,
    "theme_mode":           "dark",
}
for key, val in defaults.items():
    if key not in st.session_state:
        st.session_state[key] = val

st.switch_page("pages/01_home.py")