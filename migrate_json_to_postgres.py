"""
migrate_json_to_postgres.py
----------------------------
One-time import: reads the OLD file-based storage (users.json,
data/<user_id>/database.json, data/<user_id>/device.json,
data/provisioned_devices.json, and the per-user *.log files) and loads
it into Postgres via db.py.

Run this once, after setting DATABASE_URL, before you stop trusting the
JSON files:

    python migrate_json_to_postgres.py

Safe to re-run: users/pets/devices/provisioned_devices are upserted by
their natural key, and event-log import is skipped for any user who
already has event_logs rows (so re-running won't duplicate history).

This replaces migrate_add_roles.py, which was itself a one-time patch
for the JSON-file era.
"""

import json
import os
import re
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()

import db

APP_ROOT = os.path.dirname(os.path.abspath(__file__))
USERS_PATH = os.path.join(APP_ROOT, "users.json")
DATA_ROOT = os.path.join(APP_ROOT, "data")
REGISTRY_PATH = os.path.join(DATA_ROOT, "provisioned_devices.json")

LOG_LINE_RE = re.compile(r"^\[(.*?)\]\s*(.*)$")


def _load_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path, "r") as f:
        return json.load(f)


def _parse_timestamp(raw: str):
    try:
        return datetime.fromisoformat(raw)
    except Exception:
        return None


def migrate_users(conn) -> dict:
    """Returns {email: user_id} for every user imported (or already present)."""
    users = _load_json(USERS_PATH, {})
    email_to_id = {}
    for email, u in users.items():
        user_id = u["id"]
        created_at = u.get("created_at") or u.get("created")
        conn.execute(
            """
            INSERT INTO users (id, email, name, password_hash, role, status, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, COALESCE(%s, now()))
            ON CONFLICT (id) DO NOTHING
            """,
            (
                user_id,
                email.strip().lower(),
                u.get("name", ""),
                u["password_hash"],
                u.get("role", "user"),
                u.get("status", "active"),
                created_at,
            ),
        )
        email_to_id[email] = user_id
    print(f"OK: Users: {len(email_to_id)} imported (or already present)")
    return email_to_id


def migrate_pets(conn, user_ids: list) -> int:
    total = 0
    for user_id in user_ids:
        pets_path = os.path.join(DATA_ROOT, user_id, "database.json")
        pets = _load_json(pets_path, {})
        for name, info in pets.items():
            conn.execute(
                """
                INSERT INTO pets (user_id, name, image, type, age, weight, feeding_amount,
                                   registered, last_detected, last_fed)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (user_id, name) DO NOTHING
                """,
                (
                    user_id,
                    name,
                    info.get("image"),
                    info.get("type"),
                    str(info.get("age")) if info.get("age") is not None else None,
                    str(info.get("weight")) if info.get("weight") is not None else None,
                    str(info.get("feeding_amount")) if info.get("feeding_amount") is not None else None,
                    info.get("registered"),
                    info.get("last_detected"),
                    info.get("last_fed"),
                ),
            )
            total += 1
    print(f"OK: Pets: {total} imported (or already present)")
    return total


def migrate_devices(conn, user_ids: list) -> int:
    total = 0
    for user_id in user_ids:
        device_path = os.path.join(DATA_ROOT, user_id, "device.json")
        device = _load_json(device_path, None)
        if not device:
            continue
        conn.execute(
            """
            INSERT INTO devices (device_id, user_id, api_key, status, food_level,
                                  last_connection, pending_feed, provisioned, feeding_schedule)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (user_id) DO NOTHING
            """,
            (
                device["device_id"],
                user_id,
                device["api_key"],
                device.get("status", "offline"),
                device.get("food_level", 100),
                _parse_timestamp(device["last_connection"]) if device.get("last_connection") else None,
                bool(device.get("pending_feed", False)),
                bool(device.get("provisioned", False)),
                device.get("feeding_schedule"),
            ),
        )
        total += 1
    print(f"OK: Devices: {total} imported (or already present)")
    return total


def migrate_provisioned_devices(conn) -> int:
    registry = _load_json(REGISTRY_PATH, {})
    total = 0
    for device_id, entry in registry.items():
        conn.execute(
            """
            INSERT INTO provisioned_devices (device_id, setup_key, created_at, claimed_by, claimed_at)
            VALUES (%s, %s, COALESCE(%s, now()), %s, %s)
            ON CONFLICT (device_id) DO NOTHING
            """,
            (
                device_id,
                entry["setup_key"],
                _parse_timestamp(entry.get("created_at", "")),
                entry.get("claimed_by"),
                _parse_timestamp(entry["claimed_at"]) if entry.get("claimed_at") else None,
            ),
        )
        total += 1
    print(f"OK: Provisioned devices: {total} imported (or already present)")
    return total


def _import_log_file(conn, user_id: str, log_path: str, kind: str) -> int:
    if not os.path.exists(log_path):
        return 0
    count = 0
    with open(log_path, "r") as f:
        for line in f:
            m = LOG_LINE_RE.match(line.strip())
            if not m:
                continue
            timestamp_raw, message = m.groups()
            timestamp = _parse_timestamp(timestamp_raw)
            conn.execute(
                "INSERT INTO event_logs (user_id, kind, message, created_at) VALUES (%s, %s, %s, COALESCE(%s, now()))",
                (user_id, kind, message, timestamp),
            )
            count += 1
    return count


def migrate_event_logs(conn, user_ids: list) -> int:
    total = 0
    for user_id in user_ids:
        existing = conn.execute(
            "SELECT 1 FROM event_logs WHERE user_id = %s LIMIT 1", (user_id,)
        ).fetchone()
        if existing:
            continue  # already migrated (or has fresh history) — don't duplicate
        user_dir = os.path.join(DATA_ROOT, user_id)
        total += _import_log_file(conn, user_id, os.path.join(user_dir, "events.log"), "ai")
        total += _import_log_file(conn, user_id, os.path.join(user_dir, "device_events.log"), "device")
    print(f"OK: Event log lines: {total} imported")
    return total


def main():
    db.init_db()
    with db.get_conn() as conn:
        email_to_id = migrate_users(conn)
        user_ids = list(email_to_id.values())
        migrate_pets(conn, user_ids)
        migrate_devices(conn, user_ids)
        migrate_provisioned_devices(conn)
        migrate_event_logs(conn, user_ids)
    print("\nDone. Verify the data in Postgres, then you can remove users.json, "
          "data/*/database.json, data/*/device.json, data/provisioned_devices.json, "
          "and the *.log files - they're no longer read by the app.")


if __name__ == "__main__":
    main()
