"""
이벤트 파일 입출력 유틸리티.

담당 기능:
- Event를 dict로 변환
- events.jsonl 로드
- Event 리스트를 DataFrame으로 변환
- events.csv 저장
- summary.json 저장/로드
"""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List

import pandas as pd

from src.common.types import Event


DEFAULT_SUMMARY: Dict[str, Any] = {
    "total_events": 0,
    "enter_count": 0,
    "dwell_count": 0,
    "exit_count": 0,
    "total_tracks": 0,
    "video_count": 0,
    "avg_dwell_seconds": 0.0,
}


def event_to_dict(event: Event | Dict[str, Any]) -> Dict[str, Any]:
    """
    Event dataclass 또는 dict를 dict로 변환한다.
    """
    if isinstance(event, dict):
        return event

    if is_dataclass(event):
        return asdict(event)

    raise TypeError(f"지원하지 않는 이벤트 타입입니다: {type(event)}")


def events_to_dataframe(events: Iterable[Event | Dict[str, Any]]) -> pd.DataFrame:
    """
    Event 리스트를 pandas DataFrame으로 변환한다.
    """
    columns = [
        "event_id",
        "timestamp",
        "event_type",
        "track_id",
        "zone_id",
        "bbox",
        "foot_point",
        "frame_number",
        "video_source",
    ]

    rows = [event_to_dict(event) for event in events]

    if not rows:
        return pd.DataFrame(columns=columns)

    df = pd.DataFrame(rows)

    for column in columns:
        if column not in df.columns:
            df[column] = None

    return df[columns]


def load_events_from_jsonl(path: str) -> List[Event]:
    """
    JSONL 파일에서 Event 리스트를 로드한다.
    """
    jsonl_path = Path(path)

    if not jsonl_path.exists():
        return []

    events: List[Event] = []

    with open(jsonl_path, "r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            line = line.strip()

            if not line:
                continue

            try:
                data = json.loads(line)
                events.append(Event(**data))
            except (json.JSONDecodeError, TypeError, ValueError) as error:
                raise ValueError(
                    f"잘못된 JSONL 형식입니다. file={path}, line={line_number}"
                ) from error

    return events


def save_events_to_csv(
    events: Iterable[Event | Dict[str, Any]],
    output_path: str = "outputs/events.csv",
) -> None:
    """
    Event 리스트를 CSV로 저장한다.
    """
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    df = events_to_dataframe(events)
    df.to_csv(path, index=False, encoding="utf-8-sig")


def get_summary_kpi(summary_path: str = "outputs/summary.json") -> Dict[str, Any]:
    """
    summary.json을 로드한다.

    파일이 없으면 기본 KPI 값을 반환한다.
    """
    path = Path(summary_path)

    if not path.exists():
        return DEFAULT_SUMMARY.copy()

    with open(path, "r", encoding="utf-8") as file:
        data = json.load(file)

    summary = DEFAULT_SUMMARY.copy()
    summary.update(data)

    return summary


def save_summary_json(
    summary: Dict[str, Any],
    output_path: str = "outputs/summary.json",
) -> None:
    """
    summary dict를 JSON 파일로 저장한다.
    """
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w", encoding="utf-8") as file:
        json.dump(summary, file, ensure_ascii=False, indent=2)