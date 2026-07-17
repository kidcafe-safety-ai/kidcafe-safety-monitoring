"""Events 모듈 테스트 (ENTER + DWELL + EXIT)."""

from src.common.types import Track, Zone, ZoneRules
from src.events.event_manager import EventManager


class TestEventManager:
    def _make_zones(self):
        return [
            Zone(
                zone_id="zone_a",
                name="Test A",
                type="polygon",
                zone_type="play",
                points=[[0.3, 0.4], [0.7, 0.4], [0.7, 0.9], [0.3, 0.9]],
                rules=ZoneRules(enter_alert=True, dwell_threshold_sec=3),
            ),
        ]

    def _make_track(self, track_id=1):
        return Track(
            track_id=track_id,
            bbox=[100, 100, 200, 300],
            foot_point=[150, 300],
            confidence=0.9,
        )

    def _make_manager(self, zones=None):
        if zones is None:
            zones = self._make_zones()
        return EventManager(
            zones=zones,
            fps=30.0,
            enter_confirm_sec=0.0,
            exit_confirm_sec=0.0,
            track_lost_grace_sec=0.0,
        )

    def test_enter_event(self):
        manager = self._make_manager()
        events = manager.process(self._make_track(), ["zone_a"], 0, "test.mp4")
        assert len(events) == 1
        assert events[0].event_type == "ENTER"
        assert events[0].timestamp == "00:00:00.000"

    def test_no_duplicate_enter(self):
        manager = self._make_manager()
        manager.process(self._make_track(), ["zone_a"], 0, "test.mp4")
        events = manager.process(self._make_track(), ["zone_a"], 1, "test.mp4")
        assert events == []

    def test_dwell_event_after_threshold(self):
        """3초 임계, 30fps → 90프레임 후 DWELL 발생."""
        manager = self._make_manager()
        manager.process(self._make_track(), ["zone_a"], 0, "test.mp4")

        # 89 프레임 (≈2.97초) — 아직 안 발생
        events = manager.process(self._make_track(), ["zone_a"], 89, "test.mp4")
        assert events == []

        # 90 프레임 (3.0초) — 발생
        events = manager.process(self._make_track(), ["zone_a"], 90, "test.mp4")
        assert len(events) == 1
        assert events[0].event_type == "DWELL"

    def test_dwell_only_once(self):
        manager = self._make_manager()
        manager.process(self._make_track(), ["zone_a"], 0, "test.mp4")
        # 90 프레임에서 DWELL 발생
        manager.process(self._make_track(), ["zone_a"], 90, "test.mp4")
        # 120 프레임 (4초) — 이미 발생했으므로 추가 발생 X
        events = manager.process(self._make_track(), ["zone_a"], 120, "test.mp4")
        assert events == []

    def test_exit_event(self):
        manager = self._make_manager()
        manager.process(self._make_track(), ["zone_a"], 0, "test.mp4")
        # zone에서 나감
        events = manager.process(self._make_track(), [], 50, "test.mp4")
        assert len(events) == 1
        assert events[0].event_type == "EXIT"

    def test_enter_after_exit(self):
        """나갔다 다시 들어오면 새 ENTER + DWELL 카운트 리셋."""
        manager = self._make_manager()
        manager.process(self._make_track(), ["zone_a"], 0, "test.mp4")
        manager.process(self._make_track(), [], 50, "test.mp4")  # EXIT

        # 다시 진입
        events = manager.process(self._make_track(), ["zone_a"], 100, "test.mp4")
        assert len(events) == 1
        assert events[0].event_type == "ENTER"

    def test_enter_alert_false_suppresses_enter_event(self):
        """enter_alert=False 이면 ENTER 이벤트가 발생하지 않는다."""
        zones = [
            Zone(
                zone_id="zone_a",
                name="Test A",
                type="polygon",
                zone_type="play",
                points=[[0.3, 0.4], [0.7, 0.4], [0.7, 0.9], [0.3, 0.9]],
                rules=ZoneRules(enter_alert=False, dwell_threshold_sec=3),
            )
        ]
        manager = self._make_manager(zones)
        events = manager.process(self._make_track(), ["zone_a"], 0, "test.mp4")
        assert events == []

    def test_enter_alert_false_dwell_still_fires(self):
        """enter_alert=False 여도 DWELL은 정상 발생한다."""
        zones = [
            Zone(
                zone_id="zone_a",
                name="Test A",
                type="polygon",
                zone_type="play",
                points=[[0.3, 0.4], [0.7, 0.4], [0.7, 0.9], [0.3, 0.9]],
                rules=ZoneRules(enter_alert=False, dwell_threshold_sec=3),
            )
        ]
        manager = self._make_manager(zones)
        manager.process(self._make_track(), ["zone_a"], 0, "test.mp4")
        events = manager.process(self._make_track(), ["zone_a"], 90, "test.mp4")
        assert len(events) == 1
        assert events[0].event_type == "DWELL"

    def test_flush_stale_tracks_emits_exit(self):
        """zone 안에 있는 track이 화면에서 사라지면 flush 시 EXIT가 발생한다."""
        manager = self._make_manager()
        manager.process(self._make_track(), ["zone_a"], 0, "test.mp4")  # ENTER

        events = manager.flush_stale_tracks(
            active_track_ids=set(), frame_number=10, video_source="test.mp4"
        )
        assert len(events) == 1
        assert events[0].event_type == "EXIT"
        assert events[0].track_id == 1

    def test_flush_stale_tracks_clears_state(self):
        """flush 이후 해당 track_id의 상태가 완전히 제거된다."""
        manager = self._make_manager()
        manager.process(self._make_track(), ["zone_a"], 0, "test.mp4")
        manager.flush_stale_tracks(
            active_track_ids=set(), frame_number=10, video_source="test.mp4"
        )
        assert 1 not in manager.current_zones
        assert 1 not in manager.last_track_info

    def test_flush_stale_tracks_ignores_active_tracks(self):
        """active_track_ids에 포함된 track은 flush해도 상태가 유지된다."""
        manager = self._make_manager()
        manager.process(self._make_track(track_id=1), ["zone_a"], 0, "test.mp4")
        manager.process(self._make_track(track_id=2), ["zone_a"], 0, "test.mp4")

        # track_id=1만 active
        events = manager.flush_stale_tracks(
            active_track_ids={1}, frame_number=10, video_source="test.mp4"
        )
        assert len(events) == 1
        assert events[0].track_id == 2
        assert 1 in manager.current_zones  # track_id=1은 유지


class TestGetZoneOccupancy:
    def _make_zone(self, zone_id: str):
        return Zone(
            zone_id=zone_id,
            name=zone_id,
            type="polygon",
            zone_type="play",
            points=[[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]],
            rules=ZoneRules(enter_alert=True, dwell_threshold_sec=3),
        )

    def _make_track(self, track_id: int):
        return Track(
            track_id=track_id,
            bbox=[10, 10, 100, 200],
            foot_point=[55, 200],
            confidence=0.9,
        )

    def _make_manager(self, zones: list[Zone]) -> EventManager:
        return EventManager(
            zones=zones,
            fps=30.0,
            enter_confirm_sec=0.0,
            exit_confirm_sec=0.0,
            track_lost_grace_sec=0.0,
        )

    def test_empty_when_no_tracks(self):
        manager = self._make_manager([self._make_zone("zone_a")])
        assert manager.get_zone_occupancy() == {}

    def test_single_track_single_zone(self):
        manager = self._make_manager([self._make_zone("zone_a")])
        manager.process(self._make_track(1), ["zone_a"], 0, "test.mp4")
        assert manager.get_zone_occupancy() == {"zone_a": 1}

    def test_multiple_tracks_same_zone(self):
        manager = self._make_manager([self._make_zone("zone_a")])
        manager.process(self._make_track(1), ["zone_a"], 0, "test.mp4")
        manager.process(self._make_track(2), ["zone_a"], 1, "test.mp4")
        assert manager.get_zone_occupancy() == {"zone_a": 2}

    def test_tracks_in_different_zones(self):
        zones = [self._make_zone("zone_a"), self._make_zone("zone_b")]
        manager = self._make_manager(zones)
        manager.process(self._make_track(1), ["zone_a"], 0, "test.mp4")
        manager.process(self._make_track(2), ["zone_b"], 1, "test.mp4")
        assert manager.get_zone_occupancy() == {"zone_a": 1, "zone_b": 1}

    def test_occupancy_decreases_after_exit(self):
        manager = self._make_manager([self._make_zone("zone_a")])
        manager.process(self._make_track(1), ["zone_a"], 0, "test.mp4")
        assert manager.get_zone_occupancy() == {"zone_a": 1}
        manager.process(self._make_track(1), [], 1, "test.mp4")
        assert manager.get_zone_occupancy() == {}


class TestZoneSafetyPolicy:
    def _make_zone(
        self,
        zone_id: str,
        zone_type: str,
        dwell_threshold_sec: int = 3,
    ) -> Zone:
        return Zone(
            zone_id=zone_id,
            name=zone_id,
            type="polygon",
            zone_type=zone_type,
            points=[[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]],
            rules=ZoneRules(
                enter_alert=True,
                dwell_threshold_sec=dwell_threshold_sec,
            ),
        )

    def _make_track(self, track_id: int = 1) -> Track:
        return Track(
            track_id=track_id,
            bbox=[10, 10, 100, 200],
            foot_point=[55, 200],
            confidence=0.9,
        )

    def _make_manager(self, zones: list[Zone]) -> EventManager:
        return EventManager(zones=zones, fps=30.0)

    def test_restricted_enter_replaces_general_enter_after_confirmation(self):
        manager = self._make_manager(
            [self._make_zone("staff_only", "restricted")]
        )

        assert manager.process(
            self._make_track(), ["staff_only"], 0, "test.mp4"
        ) == []
        events = manager.process(
            self._make_track(), ["staff_only"], 9, "test.mp4"
        )

        assert [event.event_type for event in events] == ["ENTER_RESTRICTED"]
        assert manager.get_zone_occupancy() == {"staff_only": 1}

    def test_short_boundary_entry_is_suppressed(self):
        manager = self._make_manager([self._make_zone("play", "play")])

        assert manager.process(self._make_track(), ["play"], 0, "test.mp4") == []
        assert manager.process(self._make_track(), [], 1, "test.mp4") == []

        assert manager.get_zone_occupancy() == {}

    def test_danger_dwell_replaces_general_dwell(self):
        manager = self._make_manager(
            [self._make_zone("stairs", "danger", dwell_threshold_sec=1)]
        )
        manager.process(self._make_track(), ["stairs"], 0, "test.mp4")
        enter_events = manager.process(
            self._make_track(), ["stairs"], 9, "test.mp4"
        )

        dwell_events = manager.process(
            self._make_track(), ["stairs"], 39, "test.mp4"
        )

        assert [event.event_type for event in enter_events] == ["ENTER"]
        assert [event.event_type for event in dwell_events] == [
            "DANGER_ZONE_DWELL"
        ]

    def test_exit_requires_continuous_outside_confirmation(self):
        manager = self._make_manager([self._make_zone("play", "play")])
        manager.process(self._make_track(), ["play"], 0, "test.mp4")
        manager.process(self._make_track(), ["play"], 9, "test.mp4")

        assert manager.process(self._make_track(), [], 10, "test.mp4") == []
        assert manager.get_zone_occupancy() == {"play": 1}
        assert manager.process(self._make_track(), ["play"], 11, "test.mp4") == []
        assert manager.process(self._make_track(), [], 12, "test.mp4") == []
        assert manager.process(self._make_track(), [], 26, "test.mp4") == []

        events = manager.process(self._make_track(), [], 27, "test.mp4")

        assert [event.event_type for event in events] == ["EXIT"]
        assert manager.get_zone_occupancy() == {}

    def test_stale_track_uses_grace_period_before_exit(self):
        manager = self._make_manager([self._make_zone("play", "play")])
        manager.process(self._make_track(), ["play"], 0, "test.mp4")
        manager.process(self._make_track(), ["play"], 9, "test.mp4")

        assert manager.flush_stale_tracks(set(), 10, "test.mp4") == []
        events = manager.flush_stale_tracks(set(), 24, "test.mp4")

        assert [event.event_type for event in events] == ["EXIT"]

    def test_missing_track_resets_unconfirmed_entry_candidate(self):
        manager = self._make_manager([self._make_zone("play", "play")])
        manager.process(self._make_track(), ["play"], 0, "test.mp4")

        assert manager.flush_stale_tracks(set(), 1, "test.mp4") == []
        assert manager.process(self._make_track(), ["play"], 9, "test.mp4") == []

        events = manager.process(self._make_track(), ["play"], 18, "test.mp4")
        assert [event.event_type for event in events] == ["ENTER"]
