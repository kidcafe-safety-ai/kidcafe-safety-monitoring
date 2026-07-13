"""Streamlit 대시보드 공통 데이터 로더.

A 산출물:
- outputs/events.jsonl
- outputs/result.mp4
- data/zones/*.json

B 산출물/API:
- outputs/events.csv
- outputs/summary.json
- src.common.event_aggregator
- src.visualization.charts

각 페이지는 이 파일을 통해 데이터를 읽고, 화면 구현에만 집중한다.
"""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import pandas as pd


ROOT_DIR = Path(__file__).resolve().parents[2]

DEFAULT_EVENTS_PATH = "outputs/events.jsonl"
DEFAULT_CSV_PATH = "outputs/events.csv"
DEFAULT_SUMMARY_PATH = "outputs/summary.json"
DEFAULT_RESULT_VIDEO_PATH = "outputs/result.mp4"
DEFAULT_ZONES_PATH = "data/zones/sample.json"

DEFAULT_SUMMARY: Dict[str, Any] = {
    "total_events": 0,
    "enter_count": 0,
    "dwell_count": 0,
    "exit_count": 0,
    "total_tracks": 0,
    "video_count": 0,
    "avg_dwell_seconds": 0.0,
}


try:
    from src.common.event_aggregator import (
        calculate_summary_kpi as b_calculate_summary_kpi,
        count_events_by_type as b_count_events_by_type,
        count_events_by_zone as b_count_events_by_zone,
        generate_insights as b_generate_insights,
        get_recent_events as b_get_recent_events,
        get_summary_kpi as b_get_summary_kpi,
        get_track_ids_in_period as b_get_track_ids_in_period,
        get_track_summary as b_get_track_summary,
        load_events_from_jsonl as b_load_events_from_jsonl,
        time_per_zone_by_track as b_time_per_zone_by_track,
    )
except Exception:
    b_calculate_summary_kpi = None
    b_count_events_by_type = None
    b_count_events_by_zone = None
    b_generate_insights = None
    b_get_recent_events = None
    b_get_summary_kpi = None
    b_get_track_ids_in_period = None
    b_get_track_summary = None
    b_load_events_from_jsonl = None
    b_time_per_zone_by_track = None


def resolve_path(path_value: str | Path | None) -> Optional[Path]:
    """상대 경로를 프로젝트 루트 기준 절대 경로로 변환한다."""
    if path_value is None:
        return None

    path = Path(path_value)

    if path.is_absolute():
        return path

    return ROOT_DIR / path


def event_to_dict(event: Any) -> Dict[str, Any]:
    """Event dataclass/dict/object를 화면에서 쓰기 좋은 dict로 변환한다."""
    if event is None:
        return {}

    if isinstance(event, dict):
        return event

    if is_dataclass(event):
        return asdict(event)

    if hasattr(event, "__dict__"):
        return dict(event.__dict__)

    return {}


def event_get(event: Any, key: str, default: Any = None) -> Any:
    """dict/Event dataclass/object에서 안전하게 값을 꺼낸다."""
    if isinstance(event, dict):
        return event.get(key, default)

    return getattr(event, key, default)


def zone_to_dict(zone: Any) -> Dict[str, Any]:
    """Zone dataclass/dict/object를 dict로 변환한다."""
    if zone is None:
        return {}

    if isinstance(zone, dict):
        return zone

    if is_dataclass(zone):
        return asdict(zone)

    if hasattr(zone, "__dict__"):
        return dict(zone.__dict__)

    return {}


def load_events(
    path: str | Path = DEFAULT_EVENTS_PATH,
    *,
    use_b_api: bool = True,
    strict: bool = False,
) -> List[Any]:
    """events.jsonl을 로드한다.

    기본적으로 B의 load_events_from_jsonl을 먼저 사용한다.
    실패하면 JSONL fallback 로더로 전환한다.
    """
    resolved = resolve_path(path)

    if resolved is None or not resolved.exists():
        return []

    if use_b_api and b_load_events_from_jsonl is not None:
        try:
            return b_load_events_from_jsonl(str(resolved))
        except Exception:
            if strict:
                raise

    events: List[Dict[str, Any]] = []

    with open(resolved, "r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            line = line.strip()

            if not line:
                continue

            try:
                events.append(json.loads(line))
            except json.JSONDecodeError as error:
                if strict:
                    raise ValueError(
                        f"잘못된 JSONL 형식입니다. file={resolved}, line={line_number}"
                    ) from error

    return events


def events_to_dataframe(events: Iterable[Any]) -> pd.DataFrame:
    """이벤트 목록을 DataFrame으로 변환한다."""
    rows = [event_to_dict(event) for event in events]

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

    if not rows:
        return pd.DataFrame(columns=columns)

    df = pd.DataFrame(rows)

    for column in columns:
        if column not in df.columns:
            df[column] = None

    return df


def load_zones(path: str | Path = DEFAULT_ZONES_PATH) -> List[Dict[str, Any]]:
    """Zone JSON을 로드한다.

    지원 형식:
    - [ {...}, {...} ]
    - { "zones": [ {...}, {...} ] }
    """
    resolved = resolve_path(path)

    if resolved is None or not resolved.exists():
        return []

    with open(resolved, "r", encoding="utf-8") as file:
        data = json.load(file)

    if isinstance(data, dict) and isinstance(data.get("zones"), list):
        return [zone_to_dict(zone) for zone in data["zones"]]

    if isinstance(data, list):
        return [zone_to_dict(zone) for zone in data]

    return []


def get_zone_name_map(zones: Iterable[Any]) -> Dict[str, str]:
    """zone_id -> zone name 매핑을 만든다."""
    result: Dict[str, str] = {}

    for zone in zones:
        data = zone_to_dict(zone)
        zone_id = data.get("zone_id")
        name = data.get("name", zone_id)

        if zone_id:
            result[str(zone_id)] = str(name)

    return result


def get_summary(
    events: Optional[List[Any]] = None,
    summary_path: str | Path = DEFAULT_SUMMARY_PATH,
    *,
    use_b_api: bool = True,
) -> Dict[str, Any]:
    """summary.json을 로드하고, 없으면 이벤트에서 계산한다."""
    resolved = resolve_path(summary_path)

    if use_b_api and b_get_summary_kpi is not None:
        try:
            summary = b_get_summary_kpi(str(resolved))
            return normalize_summary(summary)
        except Exception:
            pass

    if resolved is not None and resolved.exists():
        try:
            with open(resolved, "r", encoding="utf-8") as file:
                return normalize_summary(json.load(file))
        except Exception:
            pass

    if events is None:
        events = []

    if use_b_api and b_calculate_summary_kpi is not None:
        try:
            return normalize_summary(b_calculate_summary_kpi(events))
        except Exception:
            pass

    return calculate_summary_fallback(events)


def normalize_summary(summary: Dict[str, Any] | None) -> Dict[str, Any]:
    """summary dict에 기본 키를 보장한다."""
    normalized = DEFAULT_SUMMARY.copy()

    if isinstance(summary, dict):
        normalized.update(summary)

    for key in [
        "total_events",
        "enter_count",
        "dwell_count",
        "exit_count",
        "total_tracks",
        "video_count",
    ]:
        try:
            normalized[key] = int(normalized.get(key, 0) or 0)
        except (TypeError, ValueError):
            normalized[key] = 0

    try:
        normalized["avg_dwell_seconds"] = float(
            normalized.get("avg_dwell_seconds", 0.0) or 0.0
        )
    except (TypeError, ValueError):
        normalized["avg_dwell_seconds"] = 0.0

    return normalized


def calculate_summary_fallback(events: Iterable[Any]) -> Dict[str, Any]:
    """B API 없이 KPI summary를 계산한다."""
    event_list = list(events)

    enter_count = sum(1 for event in event_list if event_get(event, "event_type") == "ENTER")
    dwell_count = sum(1 for event in event_list if event_get(event, "event_type") == "DWELL")
    exit_count = sum(1 for event in event_list if event_get(event, "event_type") == "EXIT")

    track_ids = {
        event_get(event, "track_id")
        for event in event_list
        if event_get(event, "track_id") is not None
    }

    video_sources = {
        event_get(event, "video_source")
        for event in event_list
        if event_get(event, "video_source")
    }

    return {
        "total_events": len(event_list),
        "enter_count": enter_count,
        "dwell_count": dwell_count,
        "exit_count": exit_count,
        "total_tracks": len(track_ids),
        "video_count": len(video_sources),
        "avg_dwell_seconds": 0.0,
    }


def get_recent_events(events: List[Any], n: int = 10) -> List[Any]:
    """최근 이벤트 n개를 반환한다."""
    if n <= 0:
        return []

    if b_get_recent_events is not None:
        try:
            return b_get_recent_events(events, n=n)
        except Exception:
            pass

    return list(events)[-n:][::-1]


def count_events_by_type(events: List[Any]) -> Dict[str, int]:
    """event_type별 이벤트 수를 반환한다."""
    if b_count_events_by_type is not None:
        try:
            return b_count_events_by_type(events)
        except Exception:
            pass

    result = {"ENTER": 0, "DWELL": 0, "EXIT": 0}

    for event in events:
        event_type = str(event_get(event, "event_type", "UNKNOWN"))
        result[event_type] = result.get(event_type, 0) + 1

    return result


def count_events_by_zone(events: List[Any]) -> Dict[str, int]:
    """zone_id별 이벤트 수를 반환한다."""
    if b_count_events_by_zone is not None:
        try:
            return b_count_events_by_zone(events)
        except Exception:
            pass

    result: Dict[str, int] = {}

    for event in events:
        zone_id = str(event_get(event, "zone_id", "UNKNOWN"))
        result[zone_id] = result.get(zone_id, 0) + 1

    return result


def generate_insights(events: List[Any]) -> List[str]:
    """B API 기반 인사이트를 반환한다."""
    if b_generate_insights is not None:
        try:
            insights = b_generate_insights(events)
            if insights:
                return list(insights)
        except Exception:
            pass

    type_counts = count_events_by_type(events)
    zone_counts = count_events_by_zone(events)

    insights: List[str] = []

    if type_counts.get("DWELL", 0) > 0:
        insights.append(f"장시간 체류 이벤트가 {type_counts['DWELL']}건 감지되었습니다.")

    if zone_counts:
        top_zone, top_count = max(zone_counts.items(), key=lambda item: item[1])
        insights.append(f"{top_zone} 구역 이벤트가 가장 많습니다. 총 {top_count}건입니다.")

    if not insights:
        insights.append("현재 이벤트 데이터 기준 특이 위험 패턴은 없습니다.")

    return insights


def get_track_ids(events: List[Any], start: Any = None, end: Any = None) -> List[int]:
    """track_id 목록을 반환한다."""
    if b_get_track_ids_in_period is not None:
        try:
            return sorted(b_get_track_ids_in_period(events, start, end))
        except Exception:
            pass

    track_ids = {
        event_get(event, "track_id")
        for event in events
        if event_get(event, "track_id") is not None
    }

    return sorted(track_ids)


def get_track_summary(events: List[Any], track_id: int) -> Dict[str, Any]:
    """특정 track_id 활동 요약을 반환한다."""
    if b_get_track_summary is not None:
        try:
            return normalize_track_summary(b_get_track_summary(events, track_id), events, track_id)
        except Exception:
            pass

    return normalize_track_summary({}, events, track_id)


def normalize_track_summary(
    summary: Dict[str, Any] | None,
    events: List[Any],
    track_id: int,
) -> Dict[str, Any]:
    """자녀 리포트용 track summary 키를 통일한다."""
    child_events = [
        event
        for event in events
        if event_get(event, "track_id") == track_id
    ]

    frames = [
        event_get(event, "frame_number")
        for event in child_events
        if event_get(event, "frame_number") is not None
    ]

    visited_zones = {
        event_get(event, "zone_id")
        for event in child_events
        if event_get(event, "zone_id") is not None
    }

    risk_event_count = sum(
        1
        for event in child_events
        if event_get(event, "event_type") in {"ENTER", "DWELL"}
    )

    fallback_activity_seconds = max(frames) / 30 if frames else 0.0

    data = summary if isinstance(summary, dict) else {}

    visited_value = (
        data.get("visited_zone_count")
        or data.get("visited_zones")
        or len(visited_zones)
    )

    if isinstance(visited_value, list | set | tuple):
        visited_value = len(visited_value)

    return {
        "total_activity_seconds": (
            data.get("total_activity_seconds")
            or data.get("total_activity_time")
            or data.get("activity_seconds")
            or fallback_activity_seconds
        ),
        "visited_zone_count": int(visited_value or 0),
        "movement_distance": data.get("movement_distance") or data.get("distance") or 0,
        "risk_event_count": (
            data.get("risk_event_count")
            or data.get("danger_event_count")
            or risk_event_count
        ),
    }


def time_per_zone_by_track(events: List[Any], track_id: int) -> Dict[str, float]:
    """특정 track_id의 구역별 체류 시간을 반환한다."""
    if b_time_per_zone_by_track is not None:
        try:
            return b_time_per_zone_by_track(events, track_id)
        except Exception:
            pass

    child_events = [
        event
        for event in events
        if event_get(event, "track_id") == track_id
    ]

    result: Dict[str, float] = {}

    for event in child_events:
        zone_id = str(event_get(event, "zone_id", "UNKNOWN"))
        result[zone_id] = result.get(zone_id, 0.0) + 1.0

    return result


def get_video_status(path: str | Path = DEFAULT_RESULT_VIDEO_PATH) -> Dict[str, Any]:
    """영상 파일 상태를 반환한다."""
    resolved = resolve_path(path)

    if resolved is None:
        return {
            "path": None,
            "exists": False,
            "ok": False,
            "size": 0,
            "message": "경로 없음",
        }

    if not resolved.exists():
        return {
            "path": resolved,
            "exists": False,
            "ok": False,
            "size": 0,
            "message": "파일 없음",
        }

    size = resolved.stat().st_size

    if size < 10_000:
        return {
            "path": resolved,
            "exists": True,
            "ok": False,
            "size": size,
            "message": f"파일이 너무 작음 ({size} bytes)",
        }

    return {
        "path": resolved,
        "exists": True,
        "ok": True,
        "size": size,
        "message": f"{size / 1024 / 1024:.1f} MB",
    }


def get_output_status(
    events_path: str | Path = DEFAULT_EVENTS_PATH,
    csv_path: str | Path = DEFAULT_CSV_PATH,
    summary_path: str | Path = DEFAULT_SUMMARY_PATH,
    result_video_path: str | Path = DEFAULT_RESULT_VIDEO_PATH,
) -> Dict[str, Dict[str, Any]]:
    """대시보드 산출물 상태를 한 번에 반환한다."""
    result: Dict[str, Dict[str, Any]] = {}

    for key, path_value in {
        "events": events_path,
        "csv": csv_path,
        "summary": summary_path,
        "result_video": result_video_path,
    }.items():
        resolved = resolve_path(path_value)
        exists = bool(resolved and resolved.exists())
        size = resolved.stat().st_size if exists and resolved is not None else 0

        result[key] = {
            "path": resolved,
            "exists": exists,
            "size": size,
            "message": f"{size / 1024:.1f} KB" if exists else "파일 없음",
        }

    return result
