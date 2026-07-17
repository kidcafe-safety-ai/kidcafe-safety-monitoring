"""Zone/track state machine for geofencing safety events."""

from typing import Dict, List, Set, Tuple

from src.common.types import Event, EventType, Track, Zone


DEFAULT_ENTER_CONFIRM_SEC = 0.3
DEFAULT_EXIT_CONFIRM_SEC = 0.5
DEFAULT_TRACK_LOST_GRACE_SEC = 0.5


class EventManager:
    """Create events from temporally confirmed zone membership changes.

    Raw foot-point membership can oscillate near a polygon boundary. The
    manager therefore keeps candidate transitions separate from stable zone
    state and confirms them only after a continuous time interval.
    """

    def __init__(
        self,
        zones: List[Zone],
        fps: float,
        enter_confirm_sec: float = DEFAULT_ENTER_CONFIRM_SEC,
        exit_confirm_sec: float = DEFAULT_EXIT_CONFIRM_SEC,
        track_lost_grace_sec: float = DEFAULT_TRACK_LOST_GRACE_SEC,
    ):
        if fps <= 0:
            raise ValueError("fps must be greater than 0")
        for name, value in (
            ("enter_confirm_sec", enter_confirm_sec),
            ("exit_confirm_sec", exit_confirm_sec),
            ("track_lost_grace_sec", track_lost_grace_sec),
        ):
            if value < 0:
                raise ValueError(f"{name} must be non-negative")

        self.fps = fps
        self.enter_confirm_sec = enter_confirm_sec
        self.exit_confirm_sec = exit_confirm_sec
        self.track_lost_grace_sec = track_lost_grace_sec
        self.zones_map: Dict[str, Zone] = {zone.zone_id: zone for zone in zones}

        # Confirmed zone membership used by events and CurrentStatus occupancy.
        self.current_zones: Dict[int, Set[str]] = {}
        self.entry_frames: Dict[Tuple[int, str], int] = {}
        self.dwell_fired: Set[Tuple[int, str]] = set()

        # Candidate transition start frames for temporal debounce/hysteresis.
        self.enter_candidate_frames: Dict[Tuple[int, str], int] = {}
        self.exit_candidate_frames: Dict[Tuple[int, str], int] = {}

        self.last_track_info: Dict[int, Track] = {}
        self.last_seen_frames: Dict[int, int] = {}

    def process(
        self,
        track: Track,
        zones_in: List[str],
        frame_number: int,
        video_source: str,
    ) -> List[Event]:
        """Update one track and return newly confirmed zone events."""
        track_id = track.track_id
        self.last_track_info[track_id] = track
        self.last_seen_frames[track_id] = frame_number

        stable_zones = set(self.current_zones.get(track_id, set()))
        observed_zones = {
            zone_id for zone_id in zones_in if zone_id in self.zones_map
        }
        entered: Set[str] = set()
        exited: Set[str] = set()

        for zone_id in sorted(self.zones_map):
            key = (track_id, zone_id)
            is_observed = zone_id in observed_zones
            is_stable = zone_id in stable_zones

            if is_observed:
                self.exit_candidate_frames.pop(key, None)
                if is_stable:
                    self.enter_candidate_frames.pop(key, None)
                    continue

                candidate_frame = self.enter_candidate_frames.setdefault(
                    key, frame_number
                )
                if self._has_elapsed(
                    candidate_frame, frame_number, self.enter_confirm_sec
                ):
                    stable_zones.add(zone_id)
                    entered.add(zone_id)
                    self.enter_candidate_frames.pop(key, None)
                    self.entry_frames[key] = frame_number
                continue

            self.enter_candidate_frames.pop(key, None)
            if not is_stable:
                self.exit_candidate_frames.pop(key, None)
                continue

            candidate_frame = self.exit_candidate_frames.setdefault(
                key, frame_number
            )
            if self._has_elapsed(
                candidate_frame, frame_number, self.exit_confirm_sec
            ):
                stable_zones.remove(zone_id)
                exited.add(zone_id)
                self.exit_candidate_frames.pop(key, None)

        events: List[Event] = []

        for zone_id in sorted(entered):
            zone = self.zones_map[zone_id]
            if zone.rules.enter_alert:
                events.append(
                    self._create_event(
                        event_type=self._enter_event_type(zone),
                        track=track,
                        zone_id=zone_id,
                        frame_number=frame_number,
                        video_source=video_source,
                    )
                )

        # A newly confirmed entry starts the dwell clock at this frame, so it
        # cannot also produce a dwell event in the same process call.
        staying = stable_zones - entered
        for zone_id in sorted(staying):
            key = (track_id, zone_id)
            if key in self.dwell_fired:
                continue

            zone = self.zones_map[zone_id]
            entered_frame = self.entry_frames.get(key)
            if entered_frame is None:
                continue

            elapsed_sec = (frame_number - entered_frame) / self.fps
            if elapsed_sec >= zone.rules.dwell_threshold_sec:
                events.append(
                    self._create_event(
                        event_type=self._dwell_event_type(zone),
                        track=track,
                        zone_id=zone_id,
                        frame_number=frame_number,
                        video_source=video_source,
                    )
                )
                self.dwell_fired.add(key)

        for zone_id in sorted(exited):
            events.append(
                self._create_event(
                    event_type="EXIT",
                    track=track,
                    zone_id=zone_id,
                    frame_number=frame_number,
                    video_source=video_source,
                )
            )
            key = (track_id, zone_id)
            self.entry_frames.pop(key, None)
            self.dwell_fired.discard(key)

        self.current_zones[track_id] = stable_zones
        return events

    def flush_stale_tracks(
        self,
        active_track_ids: Set[int],
        frame_number: int,
        video_source: str,
    ) -> List[Event]:
        """Expire missing tracks after a grace period and emit confirmed exits."""
        events: List[Event] = []
        known_track_ids = set(self.last_track_info) | set(self.current_zones)
        stale_ids = known_track_ids - active_track_ids

        for track_id in sorted(stale_ids):
            last_seen_frame = self.last_seen_frames.get(track_id)
            last_track = self.last_track_info.get(track_id)
            if last_seen_frame is None or last_track is None:
                self._clear_track_state(track_id)
                continue

            # Candidate transitions require continuous observations. A missing
            # track breaks that continuity, while confirmed occupancy remains
            # stable until the separate lost-track grace period expires.
            self._clear_transition_candidates(track_id)
            if not self._has_elapsed(
                last_seen_frame,
                frame_number,
                self.track_lost_grace_sec,
            ):
                continue

            for zone_id in sorted(self.current_zones.get(track_id, set())):
                events.append(
                    self._create_event(
                        event_type="EXIT",
                        track=last_track,
                        zone_id=zone_id,
                        frame_number=frame_number,
                        video_source=video_source,
                    )
                )

            self._clear_track_state(track_id)

        return events

    def get_zone_occupancy(self) -> Dict[str, int]:
        """Return occupancy calculated from confirmed zone state."""
        occupancy: Dict[str, int] = {}
        for zone_ids in self.current_zones.values():
            for zone_id in zone_ids:
                occupancy[zone_id] = occupancy.get(zone_id, 0) + 1
        return occupancy

    def _clear_track_state(self, track_id: int) -> None:
        self.current_zones.pop(track_id, None)
        for state in (
            self.entry_frames,
            self.enter_candidate_frames,
            self.exit_candidate_frames,
        ):
            for key in [key for key in state if key[0] == track_id]:
                state.pop(key, None)
        self.dwell_fired = {
            key for key in self.dwell_fired if key[0] != track_id
        }
        self.last_track_info.pop(track_id, None)
        self.last_seen_frames.pop(track_id, None)

    def _clear_transition_candidates(self, track_id: int) -> None:
        for state in (
            self.enter_candidate_frames,
            self.exit_candidate_frames,
        ):
            for key in [key for key in state if key[0] == track_id]:
                state.pop(key, None)

    def _create_event(
        self,
        event_type: EventType,
        track: Track,
        zone_id: str,
        frame_number: int,
        video_source: str,
    ) -> Event:
        return Event.create(
            event_type=event_type,
            track_id=track.track_id,
            zone_id=zone_id,
            bbox=track.bbox,
            foot_point=track.foot_point,
            frame_number=frame_number,
            video_source=video_source,
            timestamp=self._video_timestamp(frame_number),
        )

    @staticmethod
    def _enter_event_type(zone: Zone) -> EventType:
        if zone.zone_type == "restricted":
            return "ENTER_RESTRICTED"
        return "ENTER"

    @staticmethod
    def _dwell_event_type(zone: Zone) -> EventType:
        if zone.zone_type == "danger":
            return "DANGER_ZONE_DWELL"
        return "DWELL"

    def _has_elapsed(
        self,
        start_frame: int,
        frame_number: int,
        duration_sec: float,
    ) -> bool:
        return (frame_number - start_frame) / self.fps >= duration_sec

    def _video_timestamp(self, frame_number: int) -> str:
        """Convert a frame number to the Event Schema video timestamp."""
        total_seconds = frame_number / self.fps
        hours = int(total_seconds // 3600)
        minutes = int((total_seconds % 3600) // 60)
        seconds = total_seconds % 60
        return f"{hours:02d}:{minutes:02d}:{seconds:06.3f}"
