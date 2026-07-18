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

# Global registry of factory-provisioned feeders (the "sticker" pool).
# Lives in data/ so it's never committed to git — it holds setup keys.
APP_ROOT = os.path.dirname(os.path.abspath(__file__))
REGISTRY_PATH = os.path.join(APP_ROOT, "data", "provisioned_devices.json")


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


# ============================================================================
# Factory provisioning + sticker-based claiming
# ============================================================================
#
# Business flow for real hardware:
#   1. Admin clicks "Provision new device" -> a Device ID + Setup Key pair
#      is minted here and shown once for printing on the unit's sticker.
#      The same pair is flashed into the ESP32 firmware (the Setup Key IS
#      the device's X-API-Key).
#   2. The customer signs up, goes to their Device page, and types the two
#      values from the sticker. claim_device() binds that feeder to their
#      account — their device.json takes on the provisioned identity, so
#      the ESP32's API calls resolve to them from that moment on.
#   3. A feeder can only be claimed while unclaimed. Someone who reads the
#      sticker of an already-connected feeder cannot hijack it.


def _load_registry() -> dict:
    try:
        with open(REGISTRY_PATH, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_registry(registry: dict) -> None:
    os.makedirs(os.path.dirname(REGISTRY_PATH), exist_ok=True)
    with open(REGISTRY_PATH, "w") as f:
        json.dump(registry, f, indent=2)


def _format_setup_key(raw_hex: str) -> str:
    """Sticker-friendly: uppercase hex in groups of 4, e.g. A1B2-C3D4-E5F6."""
    raw_hex = raw_hex.upper()
    return "-".join(raw_hex[i:i + 4] for i in range(0, len(raw_hex), 4))


def normalize_setup_key(typed: str) -> str:
    """Forgives how customers type the sticker key: spaces, missing dashes,
    lowercase all become the canonical A1B2-C3D4-E5F6 form."""
    cleaned = "".join(c for c in typed.upper() if c.isalnum())
    return _format_setup_key(cleaned)


def provision_device() -> dict:
    """Admin action: mint a new factory device for sticker printing."""
    registry = _load_registry()
    entry = {
        "device_id": "dev_" + secrets.token_hex(6),
        "setup_key": _format_setup_key(secrets.token_hex(6)),
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "claimed_by": None,
        "claimed_at": None,
    }
    registry[entry["device_id"]] = entry
    _save_registry(registry)
    return entry


def list_provisioned() -> list:
    """For the admin Devices page: every minted device, newest first."""
    import auth
    rows = []
    for entry in _load_registry().values():
        owner = auth.get_user_by_id(entry["claimed_by"]) if entry["claimed_by"] else None
        rows.append({**entry, "owner_email": owner["email"] if owner else None})
    return sorted(rows, key=lambda e: e["created_at"], reverse=True)


def claim_device(user_id: str, device_path: str, device_id: str, setup_key: str):
    """
    Customer action: bind the feeder on the sticker to this account.
    Returns (device_dict, error_message) — error_message is None on success.
    """
    device_id = device_id.strip().lower()
    setup_key = normalize_setup_key(setup_key)

    registry = _load_registry()
    entry = registry.get(device_id)
    # Same message for "no such device" and "wrong key", so the form can't
    # be used to probe which IDs exist.
    if entry is None or entry["setup_key"] != setup_key:
        return None, "Device ID and Setup Key don't match. Check the sticker on your feeder and try again."
    if entry["claimed_by"] and entry["claimed_by"] != user_id:
        return None, "This feeder is already connected to another account. Disconnect it there first, or contact support."

    entry["claimed_by"] = user_id
    entry["claimed_at"] = datetime.now().isoformat(timespec="seconds")
    _save_registry(registry)

    # The user's device record takes on the provisioned identity. The
    # setup key doubles as the API key the ESP32 sends in X-API-Key.
    old = _load(device_path)
    device = {
        "device_id": entry["device_id"],
        "api_key": entry["setup_key"],
        "provisioned": True,
        "status": "offline",
        "food_level": 100,
        "last_connection": None,
        "pending_feed": False,
    }
    if old.get("feeding_schedule"):
        device["feeding_schedule"] = old["feeding_schedule"]
    _save(device_path, device)
    return device, None


def unclaim_device(user_id: str, device_path: str) -> None:
    """Customer action: disconnect their feeder. Frees the registry entry
    so the sticker can be used to claim it again (e.g. after reselling),
    and gives the account a fresh placeholder device record."""
    device = _load(device_path)
    registry = _load_registry()
    entry = registry.get(device.get("device_id"))
    if entry and entry["claimed_by"] == user_id:
        entry["claimed_by"] = None
        entry["claimed_at"] = None
        _save_registry(registry)

    schedule = device.get("feeding_schedule")
    fresh = create_default_device(device_path)
    if schedule:
        fresh["feeding_schedule"] = schedule
        _save(device_path, fresh)


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
