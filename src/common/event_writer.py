"""이벤트를 JSONL 파일로 저장."""

import json
from dataclasses import asdict
from pathlib import Path
from typing import Iterable

from src.common.types import Event


class EventWriter:
    """이벤트를 JSONL 형식으로 append 저장."""

    def __init__(self, output_path: str = "outputs/events.jsonl"):
        self.output_path = Path(output_path)
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.output_path.write_text("")  # 기존 내용 초기화

    def write(self, event: Event):
        with open(self.output_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(event), ensure_ascii=False) + "\n")

    def write_batch(self, events: Iterable[Event]):
        for ev in events:
            self.write(ev)