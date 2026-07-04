"""
webcam_watcher.py
-------------------
Temporary stand-in for the ESP32 camera while it's being replaced.

Runs alongside `python app.py` as a SEPARATE process on your laptop.

Does two things at once, in two threads:

1. CAPTURE THREAD (background): continuously grabs frames from your
   webcam as fast as the camera allows, and keeps the most recent one
   in memory. Every CAPTURE_INTERVAL_SECONDS, it also runs that frame
   through the exact same AI pipeline the ESP32 would have used
   (pipeline.py -> detector -> identifier -> decision). If the result
   is "allow_feeding", it queues a feed command directly via
   devices.queue_feed_command() — the SAME function the Flask
   /user/feed "Feed Now" button calls.

2. STREAMING SERVER (main thread): a tiny Flask app on port 5001 that
   serves the latest frame as a live MJPEG video stream at
   /video_feed. The main PawSense app's AI Recognition page
   (templates/user/ai.html) embeds this as a live preview <img> tag,
   so you can see exactly what the AI is looking at in real time.

The ESP32 doesn't need any camera code for this to work — it already
polls GET /api/device/<id>/commands every 5 seconds and will pick up
the feed command exactly like it would have if it detected the pet
itself. Nothing about the ESP32 firmware's networking/command/ack flow
changes. Only the "who took the picture" step moves to the laptop.

When the ESP32 camera hardware is replaced, you can stop running this
script and go back to letting the ESP32 do its own detection via the
/api/device/<id>/detect endpoint — no other code changes needed.

Usage:
    python webcam_watcher.py your-email@example.com
"""

import sys
import threading
import time
from datetime import datetime

import cv2
from flask import Flask, Response
from PIL import Image

import auth
import devices
from pipeline import pipeline

CAPTURE_INTERVAL_SECONDS = 10
CAMERA_INDEX = 0  # 0 is almost always the built-in laptop webcam
STREAM_PORT = 5001

# Shared between the capture thread and the streaming server.
# _frame_lock protects _latest_jpeg from being read while it's being written.
_frame_lock = threading.Lock()
_latest_jpeg: bytes | None = None

stream_app = Flask(__name__)


def get_user_by_email(email: str):
    users = auth._load_users()
    return users.get(email.strip().lower())


def capture_loop(paths: dict):
    """
    Runs forever in a background thread. Grabs frames continuously (so the
    live preview stays smooth) and runs the AI pipeline only every
    CAPTURE_INTERVAL_SECONDS (so the ML models aren't run on every single
    frame, which would be slow and pointless).
    """
    global _latest_jpeg

    cap = cv2.VideoCapture(CAMERA_INDEX)
    if not cap.isOpened():
        print(f"✗ Could not open webcam at index {CAMERA_INDEX}.")
        print("  Try changing CAMERA_INDEX in this file if you have multiple cameras.")
        return

    last_detection_time = 0.0

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                print("✗ Failed to read frame from webcam, retrying...")
                time.sleep(1)
                continue

            # Update the live preview on every frame we can grab
            ok_encode, jpeg_bytes = cv2.imencode(".jpg", frame)
            if ok_encode:
                with _frame_lock:
                    _latest_jpeg = jpeg_bytes.tobytes()

            # Run the (slower) AI pipeline only every CAPTURE_INTERVAL_SECONDS,
            # so the live stream above stays smooth in between.
            now = time.time()
            if now - last_detection_time >= CAPTURE_INTERVAL_SECONDS:
                last_detection_time = now
                run_detection(frame, paths)

    finally:
        cap.release()


def run_detection(frame, paths: dict):
    """One AI pipeline pass on a single already-captured frame."""
    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    image = Image.fromarray(rgb_frame)

    result = pipeline(image, database_path=paths["database"], log_path=paths["events_log"])

    timestamp = datetime.now().strftime("%H:%M:%S")
    if result.get("pet") and result["pet"] != "Unknown":
        print(f"[{timestamp}] Detected: {result['pet']} (score {result['score']}) -> {result['action']}")
        if result["action"] == "allow_feeding":
            devices.queue_feed_command(paths["device"], paths["device_events_log"])
            print(f"[{timestamp}] -> Feed command queued. ESP32 will pick it up on its next poll.")
    elif result.get("animal") == "none":
        print(f"[{timestamp}] No animal in frame.")
    else:
        print(f"[{timestamp}] Animal detected but not recognized (score {result.get('score')}).")


def _generate_mjpeg():
    """Yields the latest frame repeatedly as a multipart JPEG stream —
    the standard format browsers understand for live camera previews
    without needing WebRTC or any extra JS library."""
    while True:
        with _frame_lock:
            frame_bytes = _latest_jpeg
        if frame_bytes is not None:
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n" + frame_bytes + b"\r\n"
            )
        time.sleep(0.05)  # ~20 fps cap, gentle on CPU


@stream_app.route("/video_feed")
def video_feed():
    return Response(_generate_mjpeg(), mimetype="multipart/x-mixed-replace; boundary=frame")


@stream_app.route("/status")
def status():
    with _frame_lock:
        has_frame = _latest_jpeg is not None
    return {"streaming": has_frame}


def main():
    if len(sys.argv) < 2:
        print("Usage: python webcam_watcher.py your-email@example.com")
        sys.exit(1)

    email = sys.argv[1]
    user = get_user_by_email(email)
    if not user:
        print(f"✗ No account found for '{email}'. Sign up at /signup first.")
        sys.exit(1)

    paths = auth.user_paths(user["id"])
    print(f"✓ Watching webcam for user: {user['name']} ({user['email']})")
    print(f"  Running AI detection every {CAPTURE_INTERVAL_SECONDS}s from camera index {CAMERA_INDEX}")
    print(f"  Live preview available at: http://localhost:{STREAM_PORT}/video_feed")
    print("  Press Ctrl+C to stop.\n")

    capture_thread = threading.Thread(target=capture_loop, args=(paths,), daemon=True)
    capture_thread.start()

    # Flask's dev server logging is noisy for a simple video stream — quiet it down
    import logging
    logging.getLogger("werkzeug").setLevel(logging.ERROR)

    stream_app.run(host="0.0.0.0", port=STREAM_PORT, debug=False, threaded=True)


if __name__ == "__main__":
    main()
