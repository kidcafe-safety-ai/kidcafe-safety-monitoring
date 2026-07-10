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

from src.common.types import Event, EventCause, EventCauseEvidence


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

    cause는 dict가 아니라 cause_json(JSON 문자열) 컬럼으로 저장한다.
    참고: docs/api_contract.md "출력 형식" (CSV: cause_json 문자열 컬럼).
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
        "confidence",
        "event_confidence",
        "cause_json",
    ]

    rows = []
    for event in events:
        row = dict(event_to_dict(event))
        cause = row.pop("cause", None)
        row["cause_json"] = json.dumps(cause, ensure_ascii=False) if cause else None
        rows.append(row)

    if not rows:
        return pd.DataFrame(columns=columns)

    df = pd.DataFrame(rows)

    for column in columns:
        if column not in df.columns:
            df[column] = None

    return df[columns]


def _decode_cause(cause: Any) -> EventCause | None:
    """asdict()로 저장된 cause dict를 다시 EventCause로 복원한다.

    Event.__post_init__이 cause를 EventCause 인스턴스 또는 None만 허용하므로,
    JSONL에서 읽은 plain dict를 그대로 넘기면 저장된 cause가 있는 이벤트를
    다시 로드할 때마다 ValueError가 난다.
    """
    if cause is None:
        return None
    evidence = cause["evidence"]
    return EventCause(
        type=cause["type"],
        track_id=cause["track_id"],
        score=cause["score"],
        evidence=EventCauseEvidence(
            min_distance_norm=evidence["min_distance_norm"],
            closing_speed_norm=evidence["closing_speed_norm"],
            time_to_fall_sec=evidence["time_to_fall_sec"],
        ),
    )


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
                data["cause"] = _decode_cause(data.get("cause"))
                events.append(Event(**data))
            except (json.JSONDecodeError, TypeError, ValueError, KeyError) as error:
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