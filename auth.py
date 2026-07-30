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

Users, pets, devices, and event history all live in Postgres (see db.py).
The one thing still stored on local disk is each user's own uploaded pet
photos, under data/<user_id>/uploads/ — deleting a user's account removes
that folder as well as their database rows.
"""

import os
import secrets
import shutil
from functools import wraps

from flask import abort, flash, redirect, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

import db

APP_ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_ROOT = os.path.join(APP_ROOT, "data")

VALID_ROLES = ("user", "admin")

os.makedirs(DATA_ROOT, exist_ok=True)


def _row_to_user(row) -> dict:
    """Templates/routes expect created_at as an ISO string (how it always
    looked coming out of users.json) — Postgres hands back a datetime."""
    user = dict(row)
    if user.get("created_at") is not None:
        user["created_at"] = user["created_at"].isoformat()
    return user


def _user_data_dir(user_id: str) -> str:
    """Only pet photo uploads live on local disk now; everything else
    (users, pets, devices, event history) is in Postgres."""
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

    user_id = "u_" + secrets.token_hex(8)
    password_hash = generate_password_hash(password)

    with db.get_conn() as conn:
        exists = conn.execute("SELECT 1 FROM users WHERE email = %s", (email,)).fetchone()
        if exists:
            return None, "An account with that email already exists."

        row = conn.execute(
            """
            INSERT INTO users (id, email, name, password_hash, role, status)
            VALUES (%s, %s, %s, %s, %s, 'active')
            RETURNING id, email, name, password_hash, role, status, created_at
            """,
            (user_id, email, name.strip(), password_hash, role),
        ).fetchone()

    _user_data_dir(user_id)
    return _row_to_user(row), None


def verify_login(email: str, password: str):
    """
    Returns (user_dict, error_message). error_message is None on success.

    A blocked account fails login even with the correct password — the
    message is intentionally specific ("blocked", not "incorrect
    password") since there's no security reason to hide block status
    from the account owner; they need to know to contact support.
    """
    email = email.strip().lower()
    with db.get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE email = %s", (email,)).fetchone()

    if not row or not check_password_hash(row["password_hash"], password):
        return None, "Incorrect email or password."
    if row["status"] == "blocked":
        return None, "Your account has been blocked. Please contact support for more information."
    return _row_to_user(row), None


def get_user_by_id(user_id: str):
    with db.get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = %s", (user_id,)).fetchone()
    return _row_to_user(row) if row else None


def get_user_by_email(email: str):
    email = email.strip().lower()
    with db.get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE email = %s", (email,)).fetchone()
    return _row_to_user(row) if row else None


def list_all_users() -> list:
    """For admin views: every user, sorted by signup date."""
    with db.get_conn() as conn:
        rows = conn.execute("SELECT * FROM users ORDER BY created_at ASC").fetchall()
    return [_row_to_user(r) for r in rows]


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

    with db.get_conn() as conn:
        result = conn.execute("UPDATE users SET status = 'blocked' WHERE email = %s", (email,))
        if result.rowcount == 0:
            return False, "User not found."
    return True, None


def unblock_user(email: str) -> tuple:
    email = email.strip().lower()
    with db.get_conn() as conn:
        result = conn.execute("UPDATE users SET status = 'active' WHERE email = %s", (email,))
        if result.rowcount == 0:
            return False, "User not found."
    return True, None


def delete_user(email: str, acting_admin_email: str = None) -> tuple:
    """
    Permanently removes the account AND all their data (pets, device,
    event history via ON DELETE CASCADE, plus their uploaded photos on
    disk). This is destructive and irreversible — the route calling this
    should always confirm with the admin first.
    """
    email = email.strip().lower()
    if acting_admin_email and email == acting_admin_email.strip().lower():
        return False, "You can't delete your own account."

    with db.get_conn() as conn:
        row = conn.execute("SELECT id FROM users WHERE email = %s", (email,)).fetchone()
        if not row:
            return False, "User not found."
        user_id = row["id"]
        conn.execute("DELETE FROM users WHERE email = %s", (email,))

    user_dir = os.path.join(DATA_ROOT, user_id)
    if os.path.exists(user_dir):
        shutil.rmtree(user_dir)

    return True, None


def user_paths(user_id: str) -> dict:
    """Local-disk paths this user's pages/pipeline should read and write —
    just the uploads folder now; everything else lives in Postgres."""
    user_dir = _user_data_dir(user_id)
    return {
        "dir": user_dir,
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
