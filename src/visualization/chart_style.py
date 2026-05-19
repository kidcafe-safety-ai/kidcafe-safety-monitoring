"""
matplotlib 차트 공통 스타일 설정.

담당 기능:
- 한글 폰트 설정
- 마이너스 기호 깨짐 방지
"""

from __future__ import annotations

import matplotlib


def configure_matplotlib_korean_font() -> None:
    """
    matplotlib 차트에서 한글이 깨지지 않도록 폰트를 설정한다.

    Windows:
        Malgun Gothic

    macOS:
        AppleGothic

    Linux:
        NanumGothic

    fallback:
        DejaVu Sans
    """
    matplotlib.rcParams["font.family"] = [
        "Malgun Gothic",
        "AppleGothic",
        "NanumGothic",
        "DejaVu Sans",
    ]
    matplotlib.rcParams["axes.unicode_minus"] = False