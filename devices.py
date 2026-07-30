"""
devices.py
----------
Single responsibility: feeder hardware records + the ESP32 integration
contract. Each user has exactly one device (MVP: one feeder per household),
stored in the `devices` table:

  device_id       "dev_a1b2c3d4e5f6"
  api_key         ESP32 sends this in the X-API-Key header
  status          "offline" | "online"
  food_level      percent, 0-100
  last_connection timestamp of last heartbeat/data push, or NULL
  pending_feed    set True when user clicks "Feed Now";
                   ESP32 polls for this and clears it via /api/device/<id>/ack
  feeding_schedule free-text schedule the user set on /user/feed

ESP32 integration contract (polling, not websockets — simplest for an
ESP32 to implement reliably over wifi):

  ESP32 -> POST /api/device/<id>/heartbeat   (every N seconds, proves it's alive)
  ESP32 -> POST /api/device/<id>/data        (food_level reading, etc.)
  ESP32 -> GET  /api/device/<id>/commands    (poll: "should I feed right now?")
  ESP32 -> POST /api/device/<id>/ack         (confirms it executed a feed command)

All four require header:  X-API-Key: <device's api_key>

This file only manages device state. The actual HTTP routes living in
routes/api_routes.py call into these functions — keeping the "what is a
device" logic separate from "how HTTP requests are handled".

Device heartbeats/commands/acks and manual "Feed Now" clicks are also
recorded as kind="device" rows in event_logs, replacing the old
per-user device_events.log text file.
"""

import secrets
from datetime import datetime, timedelta

import db

DEVICE_OFFLINE_AFTER_MINUTES = 10


def _log_event(user_id: str, kind: str, message: str) -> None:
    with db.get_conn() as conn:
        conn.execute(
            "INSERT INTO event_logs (user_id, kind, message) VALUES (%s, %s, %s)",
            (user_id, kind, message),
        )


def _row_to_device(row) -> dict:
    device = dict(row)
    if device.get("last_connection") is not None:
        device["last_connection"] = device["last_connection"].isoformat()
    return device


def create_default_device(user_id: str) -> dict:
    """Called once at signup so every new user has a feeder record ready
    to receive ESP32 traffic immediately, even before hardware is set up."""
    device_id = "dev_" + secrets.token_hex(6)
    api_key = secrets.token_hex(16)
    with db.get_conn() as conn:
        row = conn.execute(
            """
            INSERT INTO devices (device_id, user_id, api_key, status, food_level,
                                  last_connection, pending_feed, provisioned, feeding_schedule)
            VALUES (%s, %s, %s, 'offline', 100, NULL, FALSE, FALSE, NULL)
            ON CONFLICT (user_id) DO UPDATE SET
                device_id = EXCLUDED.device_id,
                api_key = EXCLUDED.api_key,
                status = 'offline',
                food_level = 100,
                last_connection = NULL,
                pending_feed = FALSE,
                provisioned = FALSE
            RETURNING *
            """,
            (device_id, user_id, api_key),
        ).fetchone()
    return _row_to_device(row)


def _with_computed_status(device: dict) -> dict:
    """A device only counts as 'online' if it's heartbeated recently —
    this is computed at read time rather than trusted from storage, so a
    feeder that silently dies still shows as offline after the timeout."""
    device = dict(device)
    if device.get("last_connection"):
        try:
            last = datetime.fromisoformat(device["last_connection"])
            now = datetime.now(last.tzinfo) if last.tzinfo else datetime.now()
            if now - last > timedelta(minutes=DEVICE_OFFLINE_AFTER_MINUTES):
                device["status"] = "offline"
        except Exception:
            pass
    else:
        device["status"] = "offline"
    return device


def get_device(user_id: str) -> dict:
    with db.get_conn() as conn:
        row = conn.execute("SELECT * FROM devices WHERE user_id = %s", (user_id,)).fetchone()
    device = _row_to_device(row) if row else create_default_device(user_id)
    return _with_computed_status(device)


def find_device_by_id(device_id: str):
    """
    Looks up which user owns a device_id. Used by the ESP32 API routes,
    which only know their own device_id + api_key (not which user owns
    them).

    Returns (user_id, device_dict) or (None, None).
    """
    with db.get_conn() as conn:
        row = conn.execute("SELECT * FROM devices WHERE device_id = %s", (device_id,)).fetchone()
    if not row:
        return None, None
    device = _row_to_device(row)
    return device["user_id"], _with_computed_status(device)


def verify_api_key(device: dict, provided_key: str) -> bool:
    return bool(device) and device.get("api_key") == provided_key


def record_heartbeat(user_id: str) -> dict:
    with db.get_conn() as conn:
        row = conn.execute(
            "UPDATE devices SET status = 'online', last_connection = now() WHERE user_id = %s RETURNING *",
            (user_id,),
        ).fetchone()
    _log_event(user_id, "device", "Heartbeat received — device online")
    return _row_to_device(row)


def record_sensor_data(user_id: str, food_level=None) -> dict:
    with db.get_conn() as conn:
        if food_level is not None:
            clamped = max(0, min(100, int(food_level)))
            row = conn.execute(
                """
                UPDATE devices SET status = 'online', last_connection = now(), food_level = %s
                WHERE user_id = %s RETURNING *
                """,
                (clamped, user_id),
            ).fetchone()
        else:
            row = conn.execute(
                "UPDATE devices SET status = 'online', last_connection = now() WHERE user_id = %s RETURNING *",
                (user_id,),
            ).fetchone()
    device = _row_to_device(row)
    _log_event(user_id, "device", f"Sensor data received — food_level={device.get('food_level')}%")
    return device


def queue_feed_command(user_id: str) -> None:
    """Called when the user clicks 'Feed Now' in the dashboard."""
    with db.get_conn() as conn:
        conn.execute("UPDATE devices SET pending_feed = TRUE WHERE user_id = %s", (user_id,))
    _log_event(user_id, "device", "Manual feed command queued by user")


def pop_pending_feed(user_id: str) -> bool:
    """ESP32 polls this. Returns True exactly once per queued command,
    then clears the flag immediately so it isn't fed twice if it polls
    again before sending /ack."""
    with db.get_conn() as conn:
        row = conn.execute(
            """
            UPDATE devices SET pending_feed = FALSE
            WHERE user_id = %s AND pending_feed = TRUE
            RETURNING device_id
            """,
            (user_id,),
        ).fetchone()
    return row is not None


def acknowledge_feed(user_id: str) -> None:
    _log_event(user_id, "device", "Feed command executed and acknowledged by device")


def set_feeding_schedule(user_id: str, schedule: str) -> None:
    with db.get_conn() as conn:
        conn.execute("UPDATE devices SET feeding_schedule = %s WHERE user_id = %s", (schedule, user_id))


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
#      account — their device record takes on the provisioned identity, so
#      the ESP32's API calls resolve to them from that moment on.
#   3. A feeder can only be claimed while unclaimed. Someone who reads the
#      sticker of an already-connected feeder cannot hijack it.


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
    device_id = "dev_" + secrets.token_hex(6)
    setup_key = _format_setup_key(secrets.token_hex(6))
    with db.get_conn() as conn:
        row = conn.execute(
            """
            INSERT INTO provisioned_devices (device_id, setup_key)
            VALUES (%s, %s)
            RETURNING *
            """,
            (device_id, setup_key),
        ).fetchone()
    return dict(row)


def list_provisioned() -> list:
    """For the admin Devices page: every minted device, newest first."""
    with db.get_conn() as conn:
        rows = conn.execute(
            """
            SELECT p.*, u.email AS owner_email
            FROM provisioned_devices p
            LEFT JOIN users u ON u.id = p.claimed_by
            ORDER BY p.created_at DESC
            """
        ).fetchall()
    results = []
    for row in rows:
        entry = dict(row)
        if entry.get("created_at") is not None:
            entry["created_at"] = entry["created_at"].isoformat(timespec="seconds")
        if entry.get("claimed_at") is not None:
            entry["claimed_at"] = entry["claimed_at"].isoformat(timespec="seconds")
        results.append(entry)
    return results


def claim_device(user_id: str, device_id: str, setup_key: str):
    """
    Customer action: bind the feeder on the sticker to this account.
    Returns (device_dict, error_message) — error_message is None on success.
    """
    device_id = device_id.strip().lower()
    setup_key = normalize_setup_key(setup_key)

    with db.get_conn() as conn:
        entry = conn.execute(
            "SELECT * FROM provisioned_devices WHERE device_id = %s", (device_id,)
        ).fetchone()
        # Same message for "no such device" and "wrong key", so the form can't
        # be used to probe which IDs exist.
        if entry is None or entry["setup_key"] != setup_key:
            return None, "Device ID and Setup Key don't match. Check the sticker on your feeder and try again."
        if entry["claimed_by"] and entry["claimed_by"] != user_id:
            return None, "This feeder is already connected to another account. Disconnect it there first, or contact support."

        conn.execute(
            "UPDATE provisioned_devices SET claimed_by = %s, claimed_at = now() WHERE device_id = %s",
            (user_id, device_id),
        )

        # The user's device record takes on the provisioned identity. The
        # setup key doubles as the API key the ESP32 sends in X-API-Key.
        # Any existing device row for this user is replaced, but its
        # feeding_schedule (if any) carries over.
        old = conn.execute("SELECT feeding_schedule FROM devices WHERE user_id = %s", (user_id,)).fetchone()
        old_schedule = old["feeding_schedule"] if old else None

        row = conn.execute(
            """
            INSERT INTO devices (device_id, user_id, api_key, status, food_level,
                                  last_connection, pending_feed, provisioned, feeding_schedule)
            VALUES (%s, %s, %s, 'offline', 100, NULL, FALSE, TRUE, %s)
            ON CONFLICT (user_id) DO UPDATE SET
                device_id = EXCLUDED.device_id,
                api_key = EXCLUDED.api_key,
                status = 'offline',
                food_level = 100,
                last_connection = NULL,
                pending_feed = FALSE,
                provisioned = TRUE
            RETURNING *
            """,
            (entry["device_id"], user_id, entry["setup_key"], old_schedule),
        ).fetchone()

    return _row_to_device(row), None


def unclaim_device(user_id: str) -> None:
    """Customer action: disconnect their feeder. Frees the registry entry
    so the sticker can be used to claim it again (e.g. after reselling),
    and gives the account a fresh placeholder device record. Every user
    already has a device row from signup, so create_default_device()'s
    ON CONFLICT path fires here — it resets identity/status/food_level
    but leaves feeding_schedule untouched."""
    with db.get_conn() as conn:
        current = conn.execute("SELECT device_id FROM devices WHERE user_id = %s", (user_id,)).fetchone()
        if current:
            conn.execute(
                """
                UPDATE provisioned_devices SET claimed_by = NULL, claimed_at = NULL
                WHERE device_id = %s AND claimed_by = %s
                """,
                (current["device_id"], user_id),
            )

    create_default_device(user_id)


def list_all_devices() -> list:
    """For admin views: every device across every user."""
    with db.get_conn() as conn:
        rows = conn.execute(
            """
            SELECT d.*, u.email AS owner_email, u.name AS owner_name
            FROM devices d
            JOIN users u ON u.id = d.user_id
            ORDER BY u.created_at ASC
            """
        ).fetchall()

    results = []
    for row in rows:
        device = _with_computed_status(_row_to_device(row))
        results.append({
            "device_id": device.get("device_id"),
            "owner_email": device.get("owner_email"),
            "owner_name": device.get("owner_name"),
            "status": device.get("status"),
            "food_level": device.get("food_level"),
            "last_connection": device.get("last_connection") or "Never",
        })
    return results
