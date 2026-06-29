"""
routes/api_routes.py
-----------------------
Endpoints the ESP32 (or any feeder hardware) calls directly — no browser
session involved, no cookies. Every request authenticates with a per-device
API key sent as a header, not a user login.

ESP32 firmware integration contract:

  POST /api/device/<device_id>/heartbeat
      Headers: X-API-Key: <device api key>
      Call this every ~30-60s so the dashboard knows the feeder is alive.
      -> 200 {"status": "ok"}

  POST /api/device/<device_id>/data
      Headers: X-API-Key: <device api key>
      Body (JSON): {"food_level": 73}
      Push a sensor reading (e.g. from a load cell or IR level sensor).
      -> 200 {"status": "ok", "food_level": 73}

  GET  /api/device/<device_id>/commands
      Headers: X-API-Key: <device api key>
      Poll this every few seconds. If the user clicked "Feed Now" in the
      dashboard since your last poll, you'll get {"feed": true} exactly once.
      -> 200 {"feed": true | false}

  POST /api/device/<device_id>/ack
      Headers: X-API-Key: <device api key>
      Call this after physically dispensing food, to log the event.
      -> 200 {"status": "ok"}

All four return 401 if the API key is missing or wrong, and 404 if the
device_id doesn't exist anywhere in the system.
"""

from flask import Blueprint, jsonify, request

import devices

bp = Blueprint("api", __name__, url_prefix="/api/device")


def _authenticate(device_id):
    """Returns (user_id, device, device_path) or (None, None, None) with
    the appropriate HTTP status already decided by the caller."""
    user_id, device, device_path = devices.find_device_by_id(device_id)
    if device is None:
        return None, None, None, 404

    api_key = request.headers.get("X-API-Key", "")
    if not devices.verify_api_key(device, api_key):
        return None, None, None, 401

    return user_id, device, device_path, 200


@bp.route("/<device_id>/heartbeat", methods=["POST"])
def heartbeat(device_id):
    import auth
    user_id, device, device_path, status = _authenticate(device_id)
    if status != 200:
        return jsonify({"error": "unauthorized" if status == 401 else "not found"}), status

    paths = auth.user_paths(user_id)
    devices.record_heartbeat(device_path, paths["device_events_log"])
    return jsonify({"status": "ok"})


@bp.route("/<device_id>/data", methods=["POST"])
def push_data(device_id):
    import auth
    user_id, device, device_path, status = _authenticate(device_id)
    if status != 200:
        return jsonify({"error": "unauthorized" if status == 401 else "not found"}), status

    payload = request.get_json(silent=True) or {}
    food_level = payload.get("food_level")

    paths = auth.user_paths(user_id)
    updated = devices.record_sensor_data(device_path, paths["device_events_log"], food_level=food_level)
    return jsonify({"status": "ok", "food_level": updated.get("food_level")})


@bp.route("/<device_id>/commands", methods=["GET"])
def get_commands(device_id):
    user_id, device, device_path, status = _authenticate(device_id)
    if status != 200:
        return jsonify({"error": "unauthorized" if status == 401 else "not found"}), status

    should_feed = devices.pop_pending_feed(device_path)
    return jsonify({"feed": should_feed})


@bp.route("/<device_id>/ack", methods=["POST"])
def acknowledge(device_id):
    import auth
    user_id, device, device_path, status = _authenticate(device_id)
    if status != 200:
        return jsonify({"error": "unauthorized" if status == 401 else "not found"}), status

    paths = auth.user_paths(user_id)
    devices.acknowledge_feed(device_path, paths["device_events_log"])
    return jsonify({"status": "ok"})
