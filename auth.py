"""
auth.py
-------
Single responsibility: user accounts.

Stores users in users.json:
{
  "alice@example.com": {
      "id": "u_3f2c...",
      "name": "Alice",
      "email": "alice@example.com",
      "password_hash": "...",
      "created": "2026-06-23T10:00:00"
  }
}

Each user gets their own data folder: data/<user_id>/
  data/<user_id>/database.json      (their pets)
  data/<user_id>/feeding_log.json   (their feeding history)
  data/<user_id>/uploads/           (their pet photos)

This keeps every signed-up user's pets completely separate, while
detector.py / identifier.py / decision.py / pipeline.py stay
untouched — they just get handed a different file path per request.
"""

import json
import os
import secrets
from datetime import datetime

from werkzeug.security import check_password_hash, generate_password_hash

APP_ROOT = os.path.dirname(os.path.abspath(__file__))
USERS_PATH = os.path.join(APP_ROOT, "users.json")
DATA_ROOT = os.path.join(APP_ROOT, "data")

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


def create_user(name: str, email: str, password: str):
    """
    Returns (user_dict, error_message). error_message is None on success.
    """
    email = email.strip().lower()
    if not name or not email or not password:
        return None, "Name, email, and password are all required."
    if len(password) < 6:
        return None, "Password must be at least 6 characters."

    users = _load_users()
    if email in users:
        return None, "An account with that email already exists."

    user_id = "u_" + secrets.token_hex(8)
    user = {
        "id": user_id,
        "name": name.strip(),
        "email": email,
        "password_hash": generate_password_hash(password),
        "created": datetime.now().isoformat(),
    }
    users[email] = user
    _save_users(users)

    # Set up this user's private data folder + empty pet database/log
    user_dir = _user_data_dir(user_id)
    with open(os.path.join(user_dir, "database.json"), "w") as f:
        json.dump({}, f)
    with open(os.path.join(user_dir, "feeding_log.json"), "w") as f:
        json.dump({}, f)

    return user, None


def verify_login(email: str, password: str):
    """
    Returns (user_dict, error_message). error_message is None on success.
    """
    email = email.strip().lower()
    users = _load_users()
    user = users.get(email)
    if not user or not check_password_hash(user["password_hash"], password):
        return None, "Incorrect email or password."
    return user, None


def get_user_by_id(user_id: str):
    users = _load_users()
    for user in users.values():
        if user["id"] == user_id:
            return user
    return None


def user_paths(user_id: str) -> dict:
    """Returns the file paths this user's pipeline/app code should use."""
    user_dir = _user_data_dir(user_id)
    return {
        "dir": user_dir,
        "database": os.path.join(user_dir, "database.json"),
        "feeding_log": os.path.join(user_dir, "feeding_log.json"),
        "uploads": os.path.join(user_dir, "uploads"),
    }