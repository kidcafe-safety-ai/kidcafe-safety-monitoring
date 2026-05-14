# src/main.py

import cv2
from src.detection.yolo_detector import YOLODetector


def main():

    print("KidCafe Safety AI")

    detector = YOLODetector()

    cap = cv2.VideoCapture("data/videos/sample.mp4")
    frame_number = 0

    while True:

        ret, frame = cap.read()

        if not ret:
            break

        # YOLO Detection
        result = detector.detect(
            frame,
            frame_number,
            "sample.mp4"
        )

        # 임시 시각화 (bbox만)
        for t in result.tracks:

            x1, y1, x2, y2 = map(int, t.bbox)

            cv2.rectangle(
                frame,
                (x1, y1),
                (x2, y2),
                (0, 255, 0),
                2
            )

            cv2.putText(
                frame,
                "PERSON",
                (x1, y1 - 10),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (0, 255, 0),
                2
            )

        cv2.imshow("Monitor", frame)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

        frame_number += 1

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":

    main()