"""Zone-Track 상태머신 기반 이벤트 매니저.

ENTER / DWELL / EXIT 세 가지 이벤트를 발생시킨다.
"""

from typing import Dict, List, Set, Tuple

from src.common.types import Event, Track, Zone


class EventManager:
    """Track의 zone 진입/체류/이탈 상태머신."""

    def __init__(self, zones: List[Zone], fps: float):
        """
        Args:
            zones: Zone 정의 리스트 (dwell_threshold_sec 정보 포함)
            fps: 영상 FPS (DWELL 시간 계산용)
        """
        self.fps = fps
        # zone_id → Zone 객체 (rules 접근용)
        self.zones_map: Dict[str, Zone] = {z.zone_id: z for z in zones}

        # track_id → 현재 머무는 zone_id 집합
        self.current_zones: Dict[int, Set[str]] = {}

        # (track_id, zone_id) → 진입 frame_number
        self.entry_frames: Dict[Tuple[int, str], int] = {}

        # (track_id, zone_id) → DWELL 이벤트 이미 발생했나
        self.dwell_fired: Set[Tuple[int, str]] = set()

        # track_id → 마지막으로 본 Track (화면 이탈 시 EXIT bbox 재사용)
        self.last_track_info: Dict[int, Track] = {}

    def process(
        self,
        track: Track,
        zones_in: List[str],
        frame_number: int,
        video_source: str,
    ) -> List[Event]:
        """Track의 zone 상태 변화에 따라 Event 생성.

        ENTER: 새로 진입한 zone
        DWELL: 같은 zone에 dwell_threshold_sec 이상 머무름 (zone당 1회)
        EXIT: 있던 zone에서 나감
        """
        events = []
        self.last_track_info[track.track_id] = track
        prev_zones = self.current_zones.get(track.track_id, set())
        new_zones = set(zones_in)

        # ============ ENTER ============
        entered = new_zones - prev_zones
        for zone_id in entered:
            zone = self.zones_map.get(zone_id)
            if zone and zone.rules.enter_alert:
                event = Event.create(
                    event_type="ENTER",
                    track_id=track.track_id,
                    zone_id=zone_id,
                    bbox=track.bbox,
                    foot_point=track.foot_point,
                    frame_number=frame_number,
                    video_source=video_source,
                    timestamp=self._video_timestamp(frame_number),
                )
                events.append(event)
            # enter_alert 여부와 무관하게 DWELL 계산용 진입 시각 기록
            self.entry_frames[(track.track_id, zone_id)] = frame_number

        # ============ DWELL ============
        # 계속 머무는 zone에 대해, 임계시간 초과 + 아직 DWELL 안 발생
        staying = new_zones & prev_zones
        for zone_id in staying:
            key = (track.track_id, zone_id)
            if key in self.dwell_fired:
                continue  # 이미 발생

            zone = self.zones_map.get(zone_id)
            if zone is None:
                continue  # 알 수 없는 zone (방어적)

            entered_frame = self.entry_frames.get(key)
            if entered_frame is None:
                continue

            elapsed_sec = (frame_number - entered_frame) / self.fps
            if elapsed_sec >= zone.rules.dwell_threshold_sec:
                event = Event.create(
                    event_type="DWELL",
                    track_id=track.track_id,
                    zone_id=zone_id,
                    bbox=track.bbox,
                    foot_point=track.foot_point,
                    frame_number=frame_number,
                    video_source=video_source,
                    timestamp=self._video_timestamp(frame_number),
                )
                events.append(event)
                self.dwell_fired.add(key)

        # ============ EXIT ============
        exited = prev_zones - new_zones
        for zone_id in exited:
            event = Event.create(
                event_type="EXIT",
                track_id=track.track_id,
                zone_id=zone_id,
                bbox=track.bbox,
                foot_point=track.foot_point,
                frame_number=frame_number,
                video_source=video_source,
                timestamp=self._video_timestamp(frame_number),
            )
            events.append(event)
            # zone 나가면 진입 시각/DWELL 상태 초기화
            key = (track.track_id, zone_id)
            self.entry_frames.pop(key, None)
            self.dwell_fired.discard(key)

        # 상태 업데이트
        self.current_zones[track.track_id] = new_zones
        return events

    def flush_stale_tracks(
        self,
        active_track_ids: Set[int],
        frame_number: int,
        video_source: str,
    ) -> List[Event]:
        """화면에서 사라진 track의 zone 상태를 정리하고 EXIT 이벤트를 발생시킨다.

        ByteTrack이 track_id를 버리면 process()가 다시 호출되지 않으므로
        zone 안에 있던 track은 EXIT 없이 상태가 남는다.
        매 프레임 현재 활성 track_id 집합을 넘겨 stale 항목을 청소한다.
        """
        events = []
        stale_ids = set(self.current_zones.keys()) - active_track_ids
        for track_id in stale_ids:
            last_track = self.last_track_info.get(track_id)
            if last_track is None:
                # 방어적: last_track_info가 없으면 상태만 정리
                self._clear_track_state(track_id)
                continue

            for zone_id in self.current_zones.get(track_id, set()):
                event = Event.create(
                    event_type="EXIT",
                    track_id=track_id,
                    zone_id=zone_id,
                    bbox=last_track.bbox,
                    foot_point=last_track.foot_point,
                    frame_number=frame_number,
                    video_source=video_source,
                    timestamp=self._video_timestamp(frame_number),
                )
                events.append(event)

            self._clear_track_state(track_id)

        return events

    def get_zone_occupancy(self) -> Dict[str, int]:
        """현재 각 zone에 몇 명이 있는지 반환한다.

        current_zones (track_id → set[zone_id])를 역전환해서 집계한다.
        PUT /status/current 페이로드 생성에 사용한다.
        """
        occupancy: Dict[str, int] = {}
        for zone_ids in self.current_zones.values():
            for zone_id in zone_ids:
                occupancy[zone_id] = occupancy.get(zone_id, 0) + 1
        return occupancy

    def _clear_track_state(self, track_id: int) -> None:
        zones = self.current_zones.pop(track_id, set())
        for zone_id in zones:
            key = (track_id, zone_id)
            self.entry_frames.pop(key, None)
            self.dwell_fired.discard(key)
        self.last_track_info.pop(track_id, None)

    def _video_timestamp(self, frame_number: int) -> str:
        """프레임 번호 → 영상 내 상대 시각 (HH:MM:SS.mmm)."""
        total_seconds = frame_number / self.fps
        hours = int(total_seconds // 3600)
        minutes = int((total_seconds % 3600) // 60)
        seconds = total_seconds % 60
        return f"{hours:02d}:{minutes:02d}:{seconds:06.3f}"
