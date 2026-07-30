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
# safe to share across users since each Identifier only ever looks at one
# user's pets — but to keep things simple and correct we build one per call
# using the user's own id. This costs a fresh ResNet forward pass per pet on
# each request; fine for MVP scale.
_identifier_cache: dict = {}


def _get_identifier(user_id: str) -> Identifier:
    if user_id not in _identifier_cache:
        _identifier_cache[user_id] = Identifier(user_id=user_id)
    return _identifier_cache[user_id]


def pipeline(image: Image.Image, user_id: str) -> dict:
    """
    Run the full detect -> identify -> decide pipeline on a single image.

    Works identically whether `image` originated from a web upload (NOW),
    a video frame, or a camera stream (FUTURE) — by the time it reaches
    here it is always a PIL.Image (see input_adapter.py). No branching
    on input type happens anywhere in this function.

    `user_id` lets each signed-up user's pipeline run against their own
    pets and their own event history, without detector.py, identifier.py,
    or decision.py needing to know anything beyond that id.
    """
    label, crop, det_conf = _detector.detect(image)

    if label == "none":
        result = decision.ignore(reason="no_animal_detected", user_id=user_id)
        return {"animal": "none", **result}

    identifier = _get_identifier(user_id)
    pet_name, match_score = identifier.match(crop)

    if pet_name is None:
        result = decision.ignore(reason="unknown_animal", confidence=match_score, user_id=user_id)
        return {"animal": label, "pet": "Unknown", "score": round(match_score, 2), **result}

    result = decision.decide(pet_name, match_score, user_id=user_id)
    return {"animal": label, "pet": pet_name, "score": round(match_score, 2), **result}