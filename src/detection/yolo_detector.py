# src/detection/yolo_detector.py
from ultralytics import YOLO
from src.common.types import Track, TrackingResult
from datetime import datetime, timezone

class YOLODetector:
    def __init__(self, model_path: str = "yolov8n.pt", conf: float = 0.5):
        self.model = YOLO(model_path)
        self.conf = conf

    def detect(self, frame, frame_number: int, video_source: str) -> TrackingResult:
        results = self.model(frame, conf=self.conf, classes=[0])  # person only
        
        tracks = []
        for r in results[0].boxes:
            x1, y1, x2, y2 = r.xyxy[0].tolist()
            cx = (x1 + x2) / 2
            tracks.append(Track(
                track_id=0,              # ByteTrack 붙기 전 임시값
                bbox=[x1, y1, x2, y2],
                foot_point=[cx, y2],      # 발끝
                confidence=float(r.conf),
            ))
        
        return TrackingResult(
            frame_number=frame_number,
            timestamp=datetime.now(timezone.utc).isoformat(),
            video_source=video_source,
            tracks=tracks,
        )