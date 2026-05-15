"""Zone-Track 상태머신 기반 이벤트 매니저."""

from typing import Dict, List, Set

from src.common.types import Event, Track


class EventManager:
    """Track의 zone 진입/체류/이탈 상태머신."""

    def __init__(self):
        # track_id → 현재 머무는 zone_id 집합
        self.current_zones: Dict[int, Set[str]] = {}

    def process(
        self,
        track: Track,
        zones_in: List[str],
        frame_number: int,
        video_source: str,
    ) -> List[Event]:
        """Track의 zone 상태 변화에 따라 Event 생성."""
        events = []
        prev_zones = self.current_zones.get(track.track_id, set())
        new_zones = set(zones_in)

        # ENTER: 새로 진입한 zone
        entered = new_zones - prev_zones
        for zone_id in entered:
            event = Event.create(
                event_type="ENTER",
                track_id=track.track_id,
                zone_id=zone_id,
                bbox=track.bbox,
                foot_point=track.foot_point,
                frame_number=frame_number,
                video_source=video_source,
            )
            events.append(event)

        # TODO(개발자 3): DWELL 이벤트
        # - 같은 zone에 dwell_threshold_sec 이상 머물면 발생
        # - zone별 진입 frame_number 기록 필요

        # TODO(개발자 3): EXIT 이벤트
        # exited = prev_zones - new_zones
        # for zone_id in exited:
        #     events.append(Event.create(event_type="EXIT", ...))

        self.current_zones[track.track_id] = new_zones
        return events