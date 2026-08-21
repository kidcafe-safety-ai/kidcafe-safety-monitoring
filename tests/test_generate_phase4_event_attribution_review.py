from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import generate_phase4_event_attribution_review as generate_review  # noqa: E402


def _segment_row(**overrides) -> dict[str, str]:
    row = {
        "run_id": "run_test",
        "video_id": "vid",
        "start_frame": "0",
        "end_frame": "99",
        "track_id": "1",
        "actor_id": "A01",
        "review_status": "reviewed",
        "notes": "",
    }
    row.update(overrides)
    return row


class TestResolveActor:
    def test_finds_actor_covering_frame(self):
        rows = [_segment_row(track_id="1", start_frame="0", end_frame="99", actor_id="A01")]

        assert (
            generate_review.resolve_actor(rows, video_id="vid", track_id=1, frame_number=50)
            == "A01"
        )

    def test_returns_empty_string_for_non_actor(self):
        rows = [_segment_row(track_id="5", actor_id="", notes="reviewed non-actor track")]

        assert (
            generate_review.resolve_actor(rows, video_id="vid", track_id=5, frame_number=10) == ""
        )

    def test_returns_none_when_not_found(self):
        rows = [_segment_row(track_id="1", start_frame="0", end_frame="99")]

        assert (
            generate_review.resolve_actor(rows, video_id="vid", track_id=2, frame_number=10)
            is None
        )

    def test_ignores_other_videos(self):
        rows = [_segment_row(video_id="other", track_id="1", start_frame="0", end_frame="99")]

        assert (
            generate_review.resolve_actor(rows, video_id="vid", track_id=1, frame_number=10)
            is None
        )

    def test_falls_back_to_nearest_preceding_segment_when_no_exact_match(self):
        rows = [_segment_row(track_id="1", start_frame="0", end_frame="99", actor_id="A02")]

        result = generate_review.resolve_actor(rows, video_id="vid", track_id=1, frame_number=123)

        assert result == "A02"

    def test_fallback_picks_the_latest_preceding_segment(self):
        rows = [
            _segment_row(track_id="1", start_frame="0", end_frame="50", actor_id="A01"),
            _segment_row(track_id="1", start_frame="60", end_frame="90", actor_id="A02"),
        ]

        result = generate_review.resolve_actor(rows, video_id="vid", track_id=1, frame_number=200)

        assert result == "A02"

    def test_no_fallback_when_a_segment_exactly_covers_the_frame(self):
        """정확히 덮는 segment가 non-actor라도 그 판정을 그대로 존중하고 대체하지 않는다."""
        rows = [
            _segment_row(
                track_id="5", start_frame="98", end_frame="123", actor_id="",
                notes="reviewed non-actor track",
            ),
            _segment_row(track_id="5", start_frame="133", end_frame="151", actor_id="A02"),
        ]

        result = generate_review.resolve_actor(rows, video_id="vid", track_id=5, frame_number=123)

        assert result == ""

    def test_no_fallback_when_only_later_segments_exist(self):
        rows = [_segment_row(track_id="1", start_frame="100", end_frame="150", actor_id="A01")]

        result = generate_review.resolve_actor(rows, video_id="vid", track_id=1, frame_number=10)

        assert result is None


class TestRelatedSwitches:
    def _switch_row(self, **overrides):
        row = {
            "run_id": "r",
            "switch_id": "sw1",
            "video_id": "vid",
            "actor_id": "A01",
            "from_track_id": "1",
            "to_track_id": "2",
            "switch_frame": "50",
            "review_status": "reviewed",
            "notes": "",
        }
        row.update(overrides)
        return row

    def test_matches_by_video_and_actor(self):
        rows = [self._switch_row()]

        result = generate_review.related_switches(
            rows, video_id="vid", actor_ids=["A01", ""], event_frame=100
        )

        assert result == ["sw1"]

    def test_empty_when_no_actor_ids(self):
        rows = [self._switch_row()]

        result = generate_review.related_switches(
            rows, video_id="vid", actor_ids=["", ""], event_frame=100
        )

        assert result == []

    def test_ignores_other_video(self):
        rows = [self._switch_row(video_id="other")]

        result = generate_review.related_switches(
            rows, video_id="vid", actor_ids=["A01"], event_frame=100
        )

        assert result == []

    def test_excludes_switches_that_happen_after_the_event(self):
        """낙상 후 회복해 걸어 나가며 생긴 switch를 원인으로 착각하지 않는다."""
        rows = [self._switch_row(switch_frame="145")]

        result = generate_review.related_switches(
            rows, video_id="vid", actor_ids=["A01"], event_frame=98
        )

        assert result == []

    def test_includes_switch_at_exactly_the_event_frame(self):
        rows = [self._switch_row(switch_frame="98")]

        result = generate_review.related_switches(
            rows, video_id="vid", actor_ids=["A01"], event_frame=98
        )

        assert result == ["sw1"]


class TestClassifyErrorType:
    def test_no_fall_event_is_false_alarm(self):
        result = generate_review.classify_error_type(
            label="no_fall",
            event_index=0,
            late_detection=False,
            victim_actor_id="A01",
            expected_victim_actor_id="",
            contact_occurred="false",
            predicted_cause_actor_id=None,
            expected_cause_actor_id="",
        )

        assert result == "false_alarm"

    def test_second_event_is_duplicate(self):
        result = generate_review.classify_error_type(
            label="fall",
            event_index=1,
            late_detection=False,
            victim_actor_id="A01",
            expected_victim_actor_id="A01",
            contact_occurred="false",
            predicted_cause_actor_id=None,
            expected_cause_actor_id="",
        )

        assert result == "duplicate_fall"

    def test_late_detection_wins_over_cause_check(self):
        result = generate_review.classify_error_type(
            label="fall",
            event_index=0,
            late_detection=True,
            victim_actor_id="A01",
            expected_victim_actor_id="A01",
            contact_occurred="true",
            predicted_cause_actor_id="A02",
            expected_cause_actor_id="A02",
        )

        assert result == "late_fall"

    def test_victim_mismatch(self):
        result = generate_review.classify_error_type(
            label="fall",
            event_index=0,
            late_detection=False,
            victim_actor_id="A02",
            expected_victim_actor_id="A01",
            contact_occurred="false",
            predicted_cause_actor_id=None,
            expected_cause_actor_id="",
        )

        assert result == "victim_mismatch"

    def test_victim_resolved_to_non_actor_track_is_a_mismatch_not_missed_cause(self):
        """확정된 낙상의 victim track이 non-actor로 판정됐으면 cause 문제로 내려가지 않는다."""
        result = generate_review.classify_error_type(
            label="fall",
            event_index=0,
            late_detection=False,
            victim_actor_id="",
            expected_victim_actor_id="A01",
            contact_occurred="true",
            predicted_cause_actor_id="A02",
            expected_cause_actor_id="A02",
        )

        assert result == "victim_mismatch"

    def test_victim_not_found_at_all_is_a_mismatch(self):
        result = generate_review.classify_error_type(
            label="fall",
            event_index=0,
            late_detection=False,
            victim_actor_id=None,
            expected_victim_actor_id="A01",
            contact_occurred="false",
            predicted_cause_actor_id=None,
            expected_cause_actor_id="",
        )

        assert result == "victim_mismatch"

    def test_missed_cause_when_contact_occurred_but_no_prediction(self):
        result = generate_review.classify_error_type(
            label="fall",
            event_index=0,
            late_detection=False,
            victim_actor_id="A01",
            expected_victim_actor_id="A01",
            contact_occurred="true",
            predicted_cause_actor_id=None,
            expected_cause_actor_id="A02",
        )

        assert result == "missed_cause"

    def test_false_attribution_when_predicted_cause_is_wrong_actor(self):
        result = generate_review.classify_error_type(
            label="fall",
            event_index=0,
            late_detection=False,
            victim_actor_id="A01",
            expected_victim_actor_id="A01",
            contact_occurred="true",
            predicted_cause_actor_id="A01",
            expected_cause_actor_id="A02",
        )

        assert result == "false_attribution"

    def test_correct_contact_attribution_is_none(self):
        result = generate_review.classify_error_type(
            label="fall",
            event_index=0,
            late_detection=False,
            victim_actor_id="A01",
            expected_victim_actor_id="A01",
            contact_occurred="true",
            predicted_cause_actor_id="A02",
            expected_cause_actor_id="A02",
        )

        assert result == "none"

    def test_solo_fall_with_no_predicted_cause_is_none(self):
        result = generate_review.classify_error_type(
            label="fall",
            event_index=0,
            late_detection=False,
            victim_actor_id="A01",
            expected_victim_actor_id="A01",
            contact_occurred="false",
            predicted_cause_actor_id=None,
            expected_cause_actor_id="",
        )

        assert result == "none"

    def test_solo_fall_with_spurious_predicted_cause_is_false_attribution(self):
        result = generate_review.classify_error_type(
            label="fall",
            event_index=0,
            late_detection=False,
            victim_actor_id="A01",
            expected_victim_actor_id="A01",
            contact_occurred="false",
            predicted_cause_actor_id="A02",
            expected_cause_actor_id="",
        )

        assert result == "false_attribution"


class TestBuildRows:
    @staticmethod
    def _annotation(label: str) -> dict[str, str]:
        return {
            "label": label,
            "victim_actor_id": "A01" if label == "fall" else "",
            "contact_occurred": "false",
            "cause_actor_id": "",
        }

    def test_no_fall_without_event_creates_true_negative_coverage_row(self):
        rows = generate_review.build_rows(
            run_id="run_test",
            replay_results=[{"video_id": "vid", "events": []}],
            official_videos_by_id={"vid": {"late_detection": False}},
            annotation_by_video={"vid": self._annotation("no_fall")},
            segment_rows=[],
            switch_rows=[],
        )

        assert len(rows) == 1
        assert rows[0]["event_error_type"] == "true_negative"
        assert rows[0]["event_frame"] == ""
        assert rows[0]["id_switch_relation"] == "none"

    def test_no_fall_event_creates_false_alarm_row(self):
        rows = generate_review.build_rows(
            run_id="run_test",
            replay_results=[
                {
                    "video_id": "vid",
                    "events": [
                        {
                            "frame_number": 10,
                            "track_id": 1,
                            "cause": None,
                        }
                    ],
                }
            ],
            official_videos_by_id={"vid": {"late_detection": False}},
            annotation_by_video={"vid": self._annotation("no_fall")},
            segment_rows=[_segment_row()],
            switch_rows=[],
        )

        assert len(rows) == 1
        assert rows[0]["event_error_type"] == "false_alarm"
        assert rows[0]["event_frame"] == "10"
