# src/tracking/bytetrack_wrapper.py

from ultralytics import YOLO
from src.common.types import Track, TrackingResult
from datetime import datetime, timezone

class ByteTracker:
    def __init__(self):
        # YOLO 자체 tracker 사용 (ByteTrack 내장)
        self.model = YOLO("yolov8n.pt")

    def update(self, frame, frame_number: int, video_source: str) -> TrackingResult:

        results = self.model.track(
            frame,
            persist=True,
            classes=[0],
            verbose=False
        )

        tracks = []

        if results[0].boxes is not None:
            for box in results[0].boxes:

                x1, y1, x2, y2 = box.xyxy[0].tolist()

                cx = (x1 + x2) / 2
                cy = y2

                # ultralytics tracking ID
                track_id = int(box.id.item()) if box.id is not None else -1

                tracks.append(Track(
                    track_id=track_id,
                    bbox=[x1, y1, x2, y2],
                    foot_point=[cx, cy],
                    confidence=float(box.conf)
                ))

        return TrackingResult(
            frame_number=frame_number,
            timestamp=datetime.now(timezone.utc).isoformat(),
            video_source=video_source,
            tracks=tracks
        )