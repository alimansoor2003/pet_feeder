"""
devices.py
----------
Single responsibility: feeder hardware records + the ESP32 integration
contract.

Each user has exactly one device.json (MVP: one feeder per household):
{
  "device_id": "dev_a1b2c3d4e5f6",
  "api_key": "...",              <- ESP32 sends this in the X-API-Key header
  "status": "offline" | "online",
  "food_level": 100,              <- percent, 0-100
  "last_connection": null,        <- ISO timestamp of last heartbeat/data push
  "pending_feed": false           <- set True when user clicks "Feed Now";
                                      ESP32 polls for this and clears it
                                      via /api/device/<id>/ack
}

ESP32 integration contract (polling, not websockets — simplest for an
ESP32 to implement reliably over wifi):

  ESP32 -> POST /api/device/<id>/heartbeat   (every N seconds, proves it's alive)
  ESP32 -> POST /api/device/<id>/data        (food_level reading, etc.)
  ESP32 -> GET  /api/device/<id>/commands    (poll: "should I feed right now?")
  ESP32 -> POST /api/device/<id>/ack         (confirms it executed a feed command)

All four require header:  X-API-Key: <device's api_key>

This file only manages the JSON state. The actual HTTP routes living in
routes/api_routes.py call into these functions — keeping the "what is a
device" logic separate from "how HTTP requests are handled".
"""

import json
import os
import secrets
from datetime import datetime, timedelta

DEVICE_OFFLINE_AFTER_MINUTES = 10


def _load(path: str) -> dict:
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def _save(path: str, data: dict) -> None:
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def _log_device_event(log_path: str, message: str) -> None:
    timestamp = datetime.now().isoformat(timespec="seconds")
    with open(log_path, "a") as f:
        f.write(f"[{timestamp}] {message}\n")


def create_default_device(device_path: str) -> dict:
    """Called once at signup so every new user has a feeder record ready
    to receive ESP32 traffic immediately, even before hardware is set up."""
    device = {
        "device_id": "dev_" + secrets.token_hex(6),
        "api_key": secrets.token_hex(16),
        "status": "offline",
        "food_level": 100,
        "last_connection": None,
        "pending_feed": False,
    }
    _save(device_path, device)
    return device


def get_device(device_path: str) -> dict:
    device = _load(device_path)
    if not device:
        device = create_default_device(device_path)
    return _with_computed_status(device)


def _with_computed_status(device: dict) -> dict:
    """A device only counts as 'online' if it's heartbeated recently —
    this is computed at read time rather than trusted from storage, so a
    feeder that silently dies still shows as offline after the timeout."""
    device = dict(device)
    if device.get("last_connection"):
        try:
            last = datetime.fromisoformat(device["last_connection"])
            if datetime.now() - last > timedelta(minutes=DEVICE_OFFLINE_AFTER_MINUTES):
                device["status"] = "offline"
        except Exception:
            pass
    else:
        device["status"] = "offline"
    return device


def find_device_by_id(device_id: str):
    """
    Scans every user's device.json for a matching device_id. Used by the
    ESP32 API routes, which only know their own device_id + api_key (not
    which user owns them). Fine at MVP scale; would move to a real index
    (e.g. SQLite) if this needs to scale past a few hundred devices.

    Returns (user_id, device_dict, device_path) or (None, None, None).
    """
    import auth
    for user in auth.list_all_users():
        paths = auth.user_paths(user["id"])
        device = _load(paths["device"])
        if device.get("device_id") == device_id:
            return user["id"], device, paths["device"]
    return None, None, None


def verify_api_key(device: dict, provided_key: str) -> bool:
    return bool(device) and device.get("api_key") == provided_key


def record_heartbeat(device_path: str, log_path: str) -> dict:
    device = _load(device_path)
    device["status"] = "online"
    device["last_connection"] = datetime.now().isoformat()
    _save(device_path, device)
    _log_device_event(log_path, "Heartbeat received — device online")
    return device


def record_sensor_data(device_path: str, log_path: str, food_level=None) -> dict:
    device = _load(device_path)
    device["status"] = "online"
    device["last_connection"] = datetime.now().isoformat()
    if food_level is not None:
        device["food_level"] = max(0, min(100, int(food_level)))
    _save(device_path, device)
    _log_device_event(log_path, f"Sensor data received — food_level={device.get('food_level')}%")
    return device


def queue_feed_command(device_path: str, log_path: str) -> None:
    """Called when the user clicks 'Feed Now' in the dashboard."""
    device = _load(device_path)
    device["pending_feed"] = True
    _save(device_path, device)
    _log_device_event(log_path, "Manual feed command queued by user")


def pop_pending_feed(device_path: str) -> bool:
    """ESP32 polls this. Returns True exactly once per queued command,
    then clears the flag immediately so it isn't fed twice if it polls
    again before sending /ack."""
    device = _load(device_path)
    pending = device.get("pending_feed", False)
    if pending:
        device["pending_feed"] = False
        _save(device_path, device)
    return pending


def acknowledge_feed(device_path: str, log_path: str) -> None:
    _log_device_event(log_path, "Feed command executed and acknowledged by device")


def list_all_devices() -> list:
    """For admin views: every device across every user."""
    import auth
    results = []
    for user in auth.list_all_users():
        paths = auth.user_paths(user["id"])
        device = get_device(paths["device"])
        results.append({
            "device_id": device.get("device_id"),
            "owner_email": user["email"],
            "owner_name": user["name"],
            "status": device.get("status"),
            "food_level": device.get("food_level"),
            "last_connection": device.get("last_connection") or "Never",
        })
    return results
