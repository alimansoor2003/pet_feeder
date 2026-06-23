"""
pipeline.py
-----------
The single, input-agnostic pipeline:

    image -> pipeline(image)

app.py (and, later, a camera-polling loop) calls this and nothing
else. This file wires detector.py -> identifier.py -> decision.py
together, but contains no detection or matching logic itself —
that separation is the point.
"""

from PIL import Image

import decision
from detector import YoloDetector
from identifier import Identifier

# YOLO is stateless across users, so one shared singleton is fine.
# Loading weights is expensive, so build once at import time.
_detector = YoloDetector()

# Identifier holds a small embedding cache keyed by (name, mtime), which is
# safe to share across users since database paths differ per user — but to
# keep things simple and correct we build one per call using the user's own
# database path. This costs a fresh ResNet forward pass per pet on each
# request; fine for MVP scale.
_identifier_cache: dict = {}


def _get_identifier(database_path: str) -> Identifier:
    if database_path not in _identifier_cache:
        _identifier_cache[database_path] = Identifier(database_path=database_path)
    return _identifier_cache[database_path]


def pipeline(image: Image.Image, database_path: str = "database.json", log_path: str = "events.log") -> dict:
    """
    Run the full detect -> identify -> decide pipeline on a single image.

    Works identically whether `image` originated from a web upload (NOW),
    a video frame, or a camera stream (FUTURE) — by the time it reaches
    here it is always a PIL.Image (see input_adapter.py). No branching
    on input type happens anywhere in this function.

    `database_path` and `log_path` let each signed-up user's pipeline run
    against their own pets and their own event log, without detector.py,
    identifier.py, or decision.py needing to know about users at all.
    """
    label, crop, det_conf = _detector.detect(image)

    if label == "none":
        result = decision.ignore(reason="no_animal_detected", log_path=log_path)
        return {"animal": "none", **result}

    identifier = _get_identifier(database_path)
    pet_name, match_score = identifier.match(crop)

    if pet_name is None:
        result = decision.ignore(reason="unknown_animal", confidence=match_score, log_path=log_path)
        return {"animal": label, "pet": "Unknown", "score": round(match_score, 2), **result}

    result = decision.decide(pet_name, match_score, log_path=log_path)
    return {"animal": label, "pet": pet_name, "score": round(match_score, 2), **result}