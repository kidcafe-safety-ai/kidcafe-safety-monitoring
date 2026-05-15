"""파이프라인 통합 테스트."""
import os
import pytest

from src.main import run_pipeline


class TestPipeline:
    @pytest.mark.skipif(
        not os.path.exists("data/videos/test.mp4"),
        reason="테스트 영상 없음",
    )
    def test_pipeline_runs_on_real_video(self):
        """실제 영상 처음 60 프레임 처리해서 에러 없는지."""
        run_pipeline(
            video_path="data/videos/test.mp4",
            zones_path="data/zones/sample.json",
            output_path="outputs/test_events.jsonl",
            frames_limit=60,
            show=False,
        )
        assert True