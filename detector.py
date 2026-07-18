"""
detector.py
-----------
Single responsibility: run YOLO object detection and report whether
a dog or cat is present in a given image.
 
This module knows NOTHING about pet identity, the database, or the web
layer. It only answers: "is there a dog/cat in this image, and if so,
where exactly?" Everything else (matching, feeding decisions, web
routes) lives in other files.
"""

from typing import Optional, Tuple

from PIL import Image
from ultralytics import YOLO

# COCO class ids used by the pretrained yolov8n model
DOG_CLASS_ID = 16
CAT_CLASS_ID = 15

# MVP device rule: everything stays on CPU. Never mix CPU/CUDA tensors.
DEVICE = "cpu"


class YoloDetector:
    def __init__(self, weights: str = "yolov8n.pt", conf_threshold: float = 0.4):
        self.model = YOLO(weights)
        self.model.to(DEVICE)
        self.conf_threshold = conf_threshold

    def detect(self, image: Image.Image) -> Tuple[str, Optional[Image.Image], float]:
        """
        Run detection on a single PIL image.

        Returns:
            label:      "dog" | "cat" | "none"
            crop:       PIL.Image of the detected animal (highest-confidence
                        box), or None if nothing was detected
            confidence: detection confidence in [0, 1], 0.0 if none
        """
        results = self.model.predict(
            source=image,
            device=DEVICE,
            conf=self.conf_threshold,
            classes=[DOG_CLASS_ID, CAT_CLASS_ID],
            verbose=False,
        )

        best_label = "none"
        best_conf = 0.0
        best_box = None

        for result in results:
            boxes = result.boxes
            if boxes is None:
                continue
            for box in boxes:
                cls_id = int(box.cls[0])
                conf = float(box.conf[0])
                if conf < self.conf_threshold or conf <= best_conf:
                    continue
                best_conf = conf
                best_box = box.xyxy[0].tolist()
                best_label = "dog" if cls_id == DOG_CLASS_ID else "cat"

        if best_label == "none" or best_box is None:
            return "none", None, 0.0

        crop = image.crop(tuple(map(int, best_box)))
        return best_label, crop, best_conf
