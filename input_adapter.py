"""
input_adapter.py
-----------------
Implements the INPUT ABSTRACTION RULE from the spec:

    image        -> pipeline(image)      (NOW)
    video frame  -> pipeline(image)       (FUTURE)
    camera frame -> pipeline(image)       (FUTURE)

No matter where a frame comes from, it is converted to a PIL.Image
*before* it touches the pipeline. detector.py, identifier.py, and
decision.py never need to know or care about the original source —
that's the whole point of this file existing.
"""

import io
from typing import Union

import numpy as np
from PIL import Image


def from_uploaded_file(file_storage) -> Image.Image:
    """NOW: convert a Flask-uploaded image file into a PIL.Image."""
    return Image.open(io.BytesIO(file_storage.read())).convert("RGB")


def from_video_frame(frame: np.ndarray) -> Image.Image:
    """
    FUTURE: convert a single decoded video frame (e.g. from OpenCV,
    shape HxWx3 ndarray, typically BGR) into a PIL.Image.

    Not wired into app.py yet — included so the abstraction is provable
    today: when video support is added, only this function's caller
    changes. pipeline.py, detector.py, identifier.py stay untouched.
    """
    if frame.ndim == 3 and frame.shape[-1] == 3:
        frame = frame[:, :, ::-1]  # assume BGR -> RGB (OpenCV convention)
    return Image.fromarray(frame).convert("RGB")


def from_camera_stream(frame: np.ndarray) -> Image.Image:
    """FUTURE: identical contract to from_video_frame — a live camera
    is just another source of ndarray frames."""
    return from_video_frame(frame)


def normalize_input(source: Union["FileStorage", np.ndarray]) -> Image.Image:  # noqa: F821
    """
    Single entry point used by app.py (and, later, a camera-polling
    loop). Detects the incoming type and routes it to the right
    adapter, but always returns a PIL.Image — this is what keeps
    pipeline.py unchanged no matter the input source.
    """
    if isinstance(source, np.ndarray):
        return from_video_frame(source)
    return from_uploaded_file(source)
