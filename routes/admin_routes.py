"""
routes/admin_routes.py
-------------------------
Platform management, under /admin/*. Every single route here is wrapped
in auth.role_required("admin") — a logged-in "user" role hitting any of
these URLs gets a 403, not a redirect, so it's unambiguous that this is
an access-control boundary and not a navigation nudge.
"""

from flask import Blueprint, flash, redirect, render_template, url_for

import auth
import devices
import events
import pets

bp = Blueprint("admin", __name__, url_prefix="/admin")


def _count_user_pets(user_id):
    return len(pets.load_database(user_id))


# ============================================================================
# 1. Overview — /admin/dashboard
# ============================================================================

@bp.route("/dashboard")
@auth.role_required("admin")
def dashboard():
    users = auth.list_all_users()
    total_pets = sum(_count_user_pets(u["id"]) for u in users)
    all_devices = devices.list_all_devices()
    connected_devices = sum(1 for d in all_devices if d["status"] == "online")
    total_feedings = sum(events.count_recognized_for_user(u["id"]) for u in users)

    return render_template(
        "admin/dashboard.html",
        user_count=len(users),
        pet_count=total_pets,
        device_count=len(all_devices),
        connected_device_count=connected_devices,
        feeding_count=total_feedings,
    )


# ============================================================================
# 2. Users Management — /admin/users
# ============================================================================

@bp.route("/users")
@auth.role_required("admin")
def users_page():
    current = auth.current_user()
    users = auth.list_all_users()
    rows = []
    for u in users:
        device = devices.get_device(u["id"])
        rows.append({
            "name": u["name"],
            "email": u["email"],
            "role": u.get("role", "user"),
            "status": u.get("status", "active"),
            "created_at": u.get("created_at", ""),
            "pet_count": _count_user_pets(u["id"]),
            "device_id": device.get("device_id"),
            "device_status": device.get("status"),
            "is_self": (u["email"] == current["email"]),
        })
    return render_template("admin/users.html", rows=rows)


@bp.route("/users/<email>/block", methods=["POST"])
@auth.role_required("admin")
def block_user(email):
    current = auth.current_user()
    success, error = auth.block_user(email, acting_admin_email=current["email"])
    if error:
        flash(error, "error")
    else:
        flash(f"{email} has been blocked.")
    return redirect(url_for("admin.users_page"))


@bp.route("/users/<email>/unblock", methods=["POST"])
@auth.role_required("admin")
def unblock_user(email):
    success, error = auth.unblock_user(email)
    if error:
        flash(error, "error")
    else:
        flash(f"{email} has been unblocked.")
    return redirect(url_for("admin.users_page"))


@bp.route("/users/<email>/delete", methods=["POST"])
@auth.role_required("admin")
def delete_user(email):
    current = auth.current_user()
    success, error = auth.delete_user(email, acting_admin_email=current["email"])
    if error:
        flash(error, "error")
    else:
        flash(f"{email} and all their data have been permanently removed.")
    return redirect(url_for("admin.users_page"))


# ============================================================================
# 3. Devices Management — /admin/devices
# ============================================================================

@bp.route("/devices")
@auth.role_required("admin")
def devices_page():
    return render_template(
        "admin/devices.html",
        devices=devices.list_all_devices(),
        provisioned=devices.list_provisioned(),
    )


@bp.route("/devices/provision", methods=["POST"])
@auth.role_required("admin")
def provision_device():
    """Factory step: mint a Device ID + Setup Key pair for a new feeder.
    Print both on the unit's sticker and flash them into its ESP32
    (the Setup Key is sent as the X-API-Key header)."""
    entry = devices.provision_device()
    flash(f"✓ New feeder provisioned — print this on the sticker: "
          f"Device ID {entry['device_id']} · Setup Key {entry['setup_key']}")
    return redirect(url_for("admin.devices_page"))


# ============================================================================
# 4. AI Analytics — /admin/analytics
# ============================================================================

@bp.route("/analytics")
@auth.role_required("admin")
def analytics_page():
    total_recognized, total_ignored = events.recognition_totals()
    total = total_recognized + total_ignored
    recognition_rate = round((total_recognized / total) * 100, 1) if total else 0

    return render_template(
        "admin/analytics.html",
        total_recognized=total_recognized,
        total_ignored=total_ignored,
        recognition_rate=recognition_rate,
    )


# ============================================================================
# 5. System Logs — /admin/logs
# ============================================================================

@bp.route("/logs")
@auth.role_required("admin")
def logs_page():
    return render_template("admin/logs.html", logs=events.recent_across_all_users(limit=150))
