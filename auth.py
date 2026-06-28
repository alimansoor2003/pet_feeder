"""
auth.py
-------
User accounts + role-based access control (RBAC) + user blocking/deleting.

Two roles only: "user" (pet owner) and "admin" (system manager).
Web signup ALWAYS creates role="user" — there is no form field for role
anywhere in the UI. The only way to create an admin is the create_admin.py
CLI script, which calls create_user(..., role="admin") directly. This is
intentional: privilege escalation must never be reachable from a public form.

Every user has a status field: "active" or "blocked".
- Blocked users cannot log in and get kicked from existing sessions.
- Blocked accounts keep all their data (pets, photos, history).
- Admins can unblock or permanently delete accounts.

Stores users in users.json:
{
  "alice@example.com": {
      "id": "u_3f2c...",
      "name": "Alice",
      "email": "alice@example.com",
      "password_hash": "...",
      "role": "user",
      "status": "active",
      "created_at": "2026-06-23T10:00:00"
  }
}

Each user gets their own data folder: data/<user_id>/
  data/<user_id>/database.json       (their pets)
  data/<user_id>/feeding_log.json    (their feeding history)
  data/<user_id>/device.json         (their feeder hardware record)
  data/<user_id>/events.log          (detection/feeding events)
  data/<user_id>/device_events.log   (device heartbeats/commands)
  data/<user_id>/uploads/            (pet photos)
"""

import json
import os
import secrets
import shutil
from datetime import datetime
from functools import wraps

from flask import abort, flash, redirect, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

APP_ROOT = os.path.dirname(os.path.abspath(__file__))
USERS_PATH = os.path.join(APP_ROOT, "users.json")
DATA_ROOT = os.path.join(APP_ROOT, "data")

VALID_ROLES = ("user", "admin")

os.makedirs(DATA_ROOT, exist_ok=True)

if not os.path.exists(USERS_PATH):
    with open(USERS_PATH, "w") as f:
        json.dump({}, f)


def _load_users() -> dict:
    with open(USERS_PATH, "r") as f:
        return json.load(f)


def _save_users(users: dict) -> None:
    with open(USERS_PATH, "w") as f:
        json.dump(users, f, indent=2)


def _user_data_dir(user_id: str) -> str:
    path = os.path.join(DATA_ROOT, user_id)
    os.makedirs(os.path.join(path, "uploads"), exist_ok=True)
    return path


def create_user(name: str, email: str, password: str, role: str = "user"):
    """
    Returns (user_dict, error_message). error_message is None on success.

    `role` defaults to "user" and is NEVER taken from web form input —
    only create_admin.py calls this with role="admin".

    Every new account starts with status="active". Admins can later set
    status="blocked" via block_user() — blocked accounts keep all their
    data but cannot log in or use an existing session.
    """
    email = email.strip().lower()
    if not name or not email or not password:
        return None, "Name, email, and password are all required."
    if len(password) < 6:
        return None, "Password must be at least 6 characters."
    if role not in VALID_ROLES:
        role = "user"

    users = _load_users()
    if email in users:
        return None, "An account with that email already exists."

    user_id = "u_" + secrets.token_hex(8)
    user = {
        "id": user_id,
        "name": name.strip(),
        "email": email,
        "password_hash": generate_password_hash(password),
        "role": role,
        "status": "active",
        "created_at": datetime.now().isoformat(),
    }
    users[email] = user
    _save_users(users)

    user_dir = _user_data_dir(user_id)
    with open(os.path.join(user_dir, "database.json"), "w") as f:
        json.dump({}, f)
    with open(os.path.join(user_dir, "feeding_log.json"), "w") as f:
        json.dump({}, f)

    return user, None


def verify_login(email: str, password: str):
    """
    Returns (user_dict, error_message). error_message is None on success.

    A blocked account fails login even with the correct password — the
    message is intentionally specific ("blocked", not "incorrect
    password") since there's no security reason to hide block status
    from the account owner; they need to know to contact support.
    """
    email = email.strip().lower()
    users = _load_users()
    user = users.get(email)
    if not user or not check_password_hash(user["password_hash"], password):
        return None, "Incorrect email or password."
    if user.get("status", "active") == "blocked":
        return None, "Your account has been blocked. Please contact support for more information."
    return user, None


def get_user_by_id(user_id: str):
    users = _load_users()
    for user in users.values():
        if user["id"] == user_id:
            return user
    return None


def list_all_users() -> list:
    """For admin views: every user, sorted by signup date."""
    users = _load_users()
    return sorted(users.values(), key=lambda u: u.get("created_at", ""))


def block_user(email: str, acting_admin_email: str = None) -> tuple:
    """
    Sets status="blocked". Their account, pets, and history are untouched —
    only login access is revoked. Returns (success: bool, error_message).

    acting_admin_email is checked so an admin can never block their own
    account from the UI and lock themselves out by accident.
    """
    email = email.strip().lower()
    if acting_admin_email and email == acting_admin_email.strip().lower():
        return False, "You can't block your own account."

    users = _load_users()
    if email not in users:
        return False, "User not found."
    users[email]["status"] = "blocked"
    _save_users(users)
    return True, None


def unblock_user(email: str) -> tuple:
    email = email.strip().lower()
    users = _load_users()
    if email not in users:
        return False, "User not found."
    users[email]["status"] = "active"
    _save_users(users)
    return True, None


def delete_user(email: str, acting_admin_email: str = None) -> tuple:
    """
    Permanently removes the account AND all their data (pets, photos,
    logs, device record). This is destructive and irreversible — the
    route calling this should always confirm with the admin first.
    """
    email = email.strip().lower()
    if acting_admin_email and email == acting_admin_email.strip().lower():
        return False, "You can't delete your own account."

    users = _load_users()
    if email not in users:
        return False, "User not found."

    user = users.pop(email)
    _save_users(users)

    user_dir = os.path.join(DATA_ROOT, user["id"])
    if os.path.exists(user_dir):
        shutil.rmtree(user_dir)

    return True, None


def user_paths(user_id: str) -> dict:
    """File paths this user's pages/pipeline should read and write."""
    user_dir = _user_data_dir(user_id)
    return {
        "dir": user_dir,
        "database": os.path.join(user_dir, "database.json"),
        "feeding_log": os.path.join(user_dir, "feeding_log.json"),
        "device": os.path.join(user_dir, "device.json"),
        "events_log": os.path.join(user_dir, "events.log"),
        "device_events_log": os.path.join(user_dir, "device_events.log"),
        "uploads": os.path.join(user_dir, "uploads"),
    }


# ============================================================================
# RBAC helpers
# ============================================================================

def current_user():
    """Return the logged-in user's dict, or None."""
    user_id = session.get("user_id")
    if not user_id:
        return None
    return get_user_by_id(user_id)


def login_required(view):
    """
    Any logged-in user (either role) may access — but a session belonging
    to a now-blocked account is killed here too, not just at login. This
    matters: an admin clicking "Block" should take effect immediately,
    even if that user already has an open browser tab logged in.
    """
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user()
        if not user:
            flash("Please log in to continue.", "error")
            return redirect(url_for("auth.login"))
        if user.get("status", "active") == "blocked":
            session.pop("user_id", None)
            flash("Your account has been blocked. Please contact support for more information.", "error")
            return redirect(url_for("auth.login"))
        return view(*args, **kwargs)
    return wrapped


def role_required(role: str):
    """Restrict a route to a specific role. Wrong role -> 403, not logged in -> login."""
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            user = current_user()
            if not user:
                flash("Please log in to continue.", "error")
                return redirect(url_for("auth.login"))
            if user.get("status", "active") == "blocked":
                session.pop("user_id", None)
                flash("Your account has been blocked. Please contact support for more information.", "error")
                return redirect(url_for("auth.login"))
            if user.get("role") != role:
                abort(403)
            return view(*args, **kwargs)
        return wrapped
    return decorator