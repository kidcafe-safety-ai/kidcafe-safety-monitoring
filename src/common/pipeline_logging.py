"""
파이프라인 logging / 진행률 표시 유틸리티.

담당 기능:
- logging 초기화
- ETA 시간 포맷 변환
"""

from __future__ import annotations

import logging


def setup_logging(log_level: str = "INFO") -> None:
    """
    logging 설정을 초기화한다.

    Args:
        log_level: DEBUG, INFO, WARNING, ERROR 중 하나
    """
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)

    logging.basicConfig(
        level=numeric_level,
        format="[%(levelname)s] %(message)s",
    )


def format_eta(seconds: float) -> str:
    """
    남은 시간을 HH:MM:SS 형식으로 변환한다.

    Args:
        seconds: 남은 시간(초)

    Returns:
        HH:MM:SS 형식 문자열
    """
    seconds = max(int(seconds), 0)

    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60

    return f"{hours:02d}:{minutes:02d}:{secs:02d}"