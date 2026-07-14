"""
이벤트 저장 Writer.

담당 기능:
- events.jsonl append 저장
- 메모리에 저장된 이벤트 목록 유지
- 파이프라인 종료 시 events.csv 저장
- 파이프라인 종료 시 summary.json 저장

B 역할:
- A가 생성한 Event를 받아 JSONL/CSV/Summary 형태로 확장 저장한다.
- C는 outputs/events.csv, outputs/summary.json을 대시보드에서 사용할 수 있다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, List

from src.common.event_counter import calculate_summary_kpi
from src.common.event_io import event_to_dict, save_events_to_csv, save_summary_json
from src.common.types import Event


class EventWriter:
    """
    이벤트를 JSONL 형식으로 저장하고,
    CSV/summary.json 생성을 지원한다.
    """

    def __init__(
        self,
        output_path: str = "outputs/events.jsonl",
        csv_output_path: str = "outputs/events.csv",
        summary_output_path: str = "outputs/summary.json",
        reset: bool = True,
    ):
        self.output_path = Path(output_path)
        self.csv_output_path = csv_output_path
        self.summary_output_path = summary_output_path
        self.events: List[Event] = []

        self.output_path.parent.mkdir(parents=True, exist_ok=True)

        if reset:
            self.output_path.write_text("", encoding="utf-8")

    def write(self, event: Event) -> None:
        """
        이벤트 1개를 JSONL에 append 저장한다.
        """
        self.events.append(event)

        with open(self.output_path, "a", encoding="utf-8") as file:
            file.write(json.dumps(event_to_dict(event), ensure_ascii=False) + "\n")

    def write_batch(self, events: Iterable[Event]) -> None:
        """
        이벤트 여러 개를 JSONL에 append 저장한다.
        """
        for event in events:
            self.write(event)

    def save_csv(self) -> None:
        """
        현재까지 저장된 이벤트를 CSV로 저장한다.
        """
        save_events_to_csv(self.events, self.csv_output_path)

    def save_summary(self, fps: float = 30.0) -> None:
        """
        현재까지 저장된 이벤트를 기반으로 summary.json을 저장한다.
        """
        summary = calculate_summary_kpi(self.events, fps=fps)
        save_summary_json(summary, self.summary_output_path)

    def finalize(self, fps: float = 30.0) -> None:
        """
        파이프라인 종료 시 CSV와 summary.json을 저장한다.

        이벤트가 없어도 빈 CSV와 기본 summary.json을 생성한다.
        """
        self.save_csv()
        self.save_summary(fps=fps)
