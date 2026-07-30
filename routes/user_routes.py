"""
routes/user_routes.py
-----------------------
Everything a pet owner sees, under /user/*. Every route is wrapped in
auth.login_required — no role check needed beyond "is logged in", since
admins have their own separate blueprint and never need these pages.
"""

import os
import re

from flask import Blueprint, abort, flash, redirect, render_template, request, send_file, url_for
from werkzeug.utils import secure_filename

import auth
import devices
import events
import pets
from input_adapter import normalize_input
from pipeline import pipeline

bp = Blueprint("user", __name__, url_prefix="/user")

APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png"}


def _allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


@bp.route("/pet-photo/<filename>")
@auth.login_required
def pet_photo(filename):
    """
    Serves a pet photo the logged-in user uploaded.

    Uploaded photos live in each user's PRIVATE data folder
    (data/u_xxx/uploads/), which Flask's normal static handler does not
    expose — that's why pet images previously fell back to the paw-print
    placeholder everywhere. This route serves them safely:

    - login_required: you must be signed in.
    - We only ever look inside THE CURRENT USER's own uploads folder, so
      one user can never request another user's photos by guessing a name.
    - secure_filename + the "must stay inside the uploads dir" check block
      path-traversal attempts (e.g. ../../users.json).
    """
    user = auth.current_user()
    paths = auth.user_paths(user["id"])
    uploads_dir = os.path.abspath(paths["uploads"])

    safe_name = secure_filename(filename)
    full_path = os.path.abspath(os.path.join(uploads_dir, safe_name))

    # Reject anything that escaped the uploads directory, or doesn't exist.
    if not full_path.startswith(uploads_dir + os.sep) or not os.path.isfile(full_path):
        abort(404)

    return send_file(full_path)


def _extract_pet_name(msg):
    match = re.search(r"'([^']+)'", msg)
    return match.group(1) if match else "Unknown"


# ============================================================================
# 1. Dashboard Overview — /user/dashboard
# ============================================================================

@bp.route("/dashboard")
@auth.login_required
def dashboard():
    user = auth.current_user()

    pets_db = pets.load_database(user["id"])
    device = devices.get_device(user["id"])
    # newest-first from the DB
    recent_ai_events = events.recent_for_user(user["id"], kind="ai", limit=100)

    recent_events = []
    for event in recent_ai_events:
        recent_events.append({
            "timestamp": event["timestamp"],
            "pet": _extract_pet_name(event["message"]),
            "action": "allow_feeding" if "Recognized" in event["message"] else "deny",
            "time": event["timestamp"].split("T")[1][:5] if "T" in event["timestamp"] else "—",
        })

    # The template does `recent_events | reverse` to put the newest on top,
    # so what we hand it here needs to be oldest-first (like the last 8
    # lines of an append-only log used to be) — flip our newest-first list.
    latest_8_oldest_first = list(reversed(recent_events[:8]))

    return render_template(
        "user/dashboard.html",
        user=user,
        pets=pets_db,
        pet_count=len(pets_db),
        device=device,
        feedings_today=events.count_recognized_today_for_user(user["id"]),
        detections_today=len(recent_events),
        recent_events=latest_8_oldest_first,
    )


# ============================================================================
# 2. Pet Management — /user/pets
# ============================================================================

@bp.route("/pets", methods=["GET", "POST"])
@auth.login_required
def pets_page():
    user = auth.current_user()
    paths = auth.user_paths(user["id"])

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        pet_type = request.form.get("type", "Dog")
        age = request.form.get("age", "")
        weight = request.form.get("weight", "")
        feeding_amount = request.form.get("feeding_amount", "")
        image_file = request.files.get("image")

        if not name or not image_file or image_file.filename == "":
            flash("Pet name and photo are both required.", "error")
            return redirect(url_for("user.pets_page"))

        if not _allowed_file(image_file.filename):
            flash("Only .jpg, .jpeg, .png images are allowed.", "error")
            return redirect(url_for("user.pets_page"))

        filename = secure_filename(f"{name.lower()}_{image_file.filename}")
        save_path = os.path.join(paths["uploads"], filename)
        image_file.save(save_path)
        rel_path = os.path.relpath(save_path, APP_ROOT)

        pets.add_pet(user["id"], name, rel_path, pet_type, age, weight, feeding_amount)
        flash(f"✓ Registered '{name}' successfully!")
        return redirect(url_for("user.pets_page"))

    pets_db = pets.load_database(user["id"])
    return render_template("user/pets.html", pets=pets_db)


@bp.route("/pets/<name>/edit", methods=["GET", "POST"])
@auth.login_required
def edit_pet(name):
    user = auth.current_user()
    paths = auth.user_paths(user["id"])
    pets_db = pets.load_database(user["id"])

    if name not in pets_db:
        flash(f"Pet '{name}' not found.", "error")
        return redirect(url_for("user.pets_page"))

    if request.method == "POST":
        pet_type = request.form.get("type", "Dog")
        age = request.form.get("age", "")
        weight = request.form.get("weight", "")
        feeding_amount = request.form.get("feeding_amount", "")

        rel_path = None
        image_file = request.files.get("image")
        if image_file and image_file.filename and _allowed_file(image_file.filename):
            filename = secure_filename(f"{name.lower()}_{image_file.filename}")
            save_path = os.path.join(paths["uploads"], filename)
            image_file.save(save_path)
            rel_path = os.path.relpath(save_path, APP_ROOT)

        pets.update_pet(user["id"], name, pet_type, age, weight, feeding_amount, rel_path)
        flash(f"✓ Updated '{name}'.")
        return redirect(url_for("user.pets_page"))

    return render_template("user/pet_edit.html", name=name, pet=pets_db[name])


@bp.route("/pets/<name>/delete", methods=["POST"])
@auth.login_required
def delete_pet(name):
    user = auth.current_user()
    if pets.delete_pet(user["id"], name):
        flash(f"'{name}' was removed.")
    else:
        flash(f"Pet '{name}' not found.", "error")
    return redirect(url_for("user.pets_page"))


# ============================================================================
# 3. Feeding Management — /user/feed
# ============================================================================

@bp.route("/feed", methods=["GET", "POST"])
@auth.login_required
def feed_page():
    user = auth.current_user()

    if request.method == "POST":
        action = request.form.get("action")
        if action == "manual_feed":
            devices.queue_feed_command(user["id"])
            flash("✓ Feed command sent to your feeder — it will dispense shortly.")
        elif action == "update_schedule":
            # Schedule storage is intentionally simple for the MVP: stored
            # as plain text on the device record. Swap for a real
            # schedule model when recurring multi-pet schedules are needed.
            devices.set_feeding_schedule(user["id"], request.form.get("schedule", "").strip())
            flash("✓ Feeding schedule updated.")
        return redirect(url_for("user.feed_page"))

    device = devices.get_device(user["id"])
    pets_db = pets.load_database(user["id"])
    return render_template("user/feed.html", device=device, pets=pets_db)


# ============================================================================
# 4. AI Recognition — /user/ai
# ============================================================================

@bp.route("/ai", methods=["GET", "POST"])
@auth.login_required
def ai_page():
    user = auth.current_user()
    device = devices.get_device(user["id"])
    result = None

    if request.method == "POST":
        image_file = request.files.get("frame")
        if not image_file or image_file.filename == "":
            flash("Please upload an image.", "error")
            return redirect(url_for("user.ai_page"))

        try:
            image = normalize_input(image_file)
            result = pipeline(image, user_id=user["id"])
            if result.get("pet") and result.get("pet") != "Unknown":
                pets.mark_detected(
                    user["id"],
                    result["pet"],
                    fed=(result.get("action") == "allow_feeding"),
                )
        except Exception as e:
            flash(f"Error: {str(e)}", "error")

    return render_template("user/ai.html", result=result, device=device)


@bp.route("/ai/latest")
@auth.login_required
def ai_latest():
    """
    Polled by the AI Recognition page's JS every few seconds to show what
    the LIVE webcam stream (webcam_watcher.py) has been detecting — as
    opposed to the one-off "Run Detection" upload test above it, which
    only fires when the user manually submits an image.

    Returns the most recent non-empty-frame events (same filtering as the
    History page) so the live feed doesn't spam "no animal in frame"
    every few seconds.
    """
    user = auth.current_user()
    recent_ai_events = events.recent_for_user(user["id"], kind="ai", limit=100)

    parsed = []
    for event in recent_ai_events:
        msg = event["message"]
        if "no_animal_detected" in msg:
            continue
        if "Recognized" in msg:
            kind = "feeding"
            pet_name = _extract_pet_name(msg)
        else:
            kind = "unknown"
            pet_name = None
        timestamp = event["timestamp"]
        parsed.append({
            "timestamp": timestamp,
            "message": msg,
            "kind": kind,
            "pet": pet_name,
            "time": timestamp.split("T")[1][:8] if "T" in timestamp else "—",
        })

    return {"events": parsed[:10]}


# ============================================================================
# 5. History — /user/history
# ============================================================================

@bp.route("/history")
@auth.login_required
def history_page():
    user = auth.current_user()

    ai_events = events.recent_for_user(user["id"], kind="ai", limit=100)
    device_events = events.recent_for_user(user["id"], kind="device", limit=100)

    parsed_events = []
    for event in ai_events:
        # History is for things worth reviewing later: a pet being fed,
        # or an animal showing up that wasn't recognized. Empty-frame
        # "no animal detected" events fire constantly (every detection
        # cycle with nothing in view) and would drown out everything
        # else, so they're deliberately excluded here.
        if "no_animal_detected" in event["message"]:
            continue
        kind = "feeding" if "Recognized" in event["message"] else "detection"
        parsed_events.append({"timestamp": event["timestamp"], "message": event["message"], "kind": kind})

    parsed_device_events = [
        {"timestamp": event["timestamp"], "message": event["message"], "kind": "device"}
        for event in device_events
    ]

    combined = sorted(parsed_events + parsed_device_events, key=lambda e: e["timestamp"], reverse=True)
    return render_template("user/history.html", events=combined[:100])


# ============================================================================
# 6. Device — /user/device
# ============================================================================

@bp.route("/device")
@auth.login_required
def device_page():
    user = auth.current_user()
    device = devices.get_device(user["id"])
    device_events = events.recent_for_user(user["id"], kind="device", limit=20)
    return render_template("user/device.html", device=device, device_events=device_events)


@bp.route("/device/connect", methods=["POST"])
@auth.login_required
def connect_device():
    """Claim a physical feeder using the Device ID + Setup Key printed on
    the sticker on the unit. No admin involvement needed."""
    user = auth.current_user()

    device_id = request.form.get("device_id", "").strip()
    setup_key = request.form.get("setup_key", "").strip()
    if not device_id or not setup_key:
        flash("Both the Device ID and the Setup Key from the sticker are required.", "error")
        return redirect(url_for("user.device_page"))

    device, error = devices.claim_device(user["id"], device_id, setup_key)
    if error:
        flash(error, "error")
    else:
        flash(f"✓ Feeder {device['device_id']} is now connected to your account!")
    return redirect(url_for("user.device_page"))


@bp.route("/device/disconnect", methods=["POST"])
@auth.login_required
def disconnect_device():
    user = auth.current_user()
    devices.unclaim_device(user["id"])
    flash("Feeder disconnected. You can reconnect it any time with the sticker on the device.")
    return redirect(url_for("user.device_page"))
