"""
routes/user_routes.py
-----------------------
Everything a pet owner sees, under /user/*. Every route is wrapped in
auth.login_required — no role check needed beyond "is logged in", since
admins have their own separate blueprint and never need these pages.
"""

import os
import re
from datetime import datetime, date

from flask import Blueprint, flash, redirect, render_template, request, url_for
from werkzeug.utils import secure_filename

import auth
import devices
import pets
from input_adapter import normalize_input
from pipeline import pipeline

bp = Blueprint("user", __name__, url_prefix="/user")

APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png"}


def _allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def _load_feeding_log(path):
    import json
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def _parse_events_log(log_path):
    events = []
    if os.path.exists(log_path):
        try:
            with open(log_path, "r") as f:
                for line in f.readlines()[-100:]:
                    if line.strip():
                        events.append(line.strip())
        except Exception:
            pass
    return events


def _extract_pet_name(msg):
    match = re.search(r"'([^']+)'", msg)
    return match.group(1) if match else "Unknown"


def _count_today_feedings(feeding_log_path):
    today = str(date.today())
    feeding_log = _load_feeding_log(feeding_log_path)
    count = 0
    for pet_feedings in feeding_log.values():
        for feeding in pet_feedings:
            if feeding.get("date") == today:
                count += 1
    return count


# ============================================================================
# 1. Dashboard Overview — /user/dashboard
# ============================================================================

@bp.route("/dashboard")
@auth.login_required
def dashboard():
    user = auth.current_user()
    paths = auth.user_paths(user["id"])

    pets_db = pets.load_database(paths["database"])
    device = devices.get_device(paths["device"])
    events = _parse_events_log(paths["events_log"])

    recent_events = []
    for event in events:
        m = re.search(r"\[(.*?)\] (.*)", event)
        if m:
            timestamp, msg = m.groups()
            recent_events.append({
                "timestamp": timestamp,
                "pet": _extract_pet_name(msg),
                "action": "allow_feeding" if "Recognized" in msg else "deny",
                "time": timestamp.split("T")[1][:5] if "T" in timestamp else "—",
            })

    return render_template(
        "user/dashboard.html",
        user=user,
        pets=pets_db,
        pet_count=len(pets_db),
        device=device,
        feedings_today=_count_today_feedings(paths["feeding_log"]),
        detections_today=len(recent_events),
        recent_events=recent_events[-8:],
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

        pets.add_pet(paths["database"], name, rel_path, pet_type, age, weight, feeding_amount)
        flash(f"✓ Registered '{name}' successfully!")
        return redirect(url_for("user.pets_page"))

    pets_db = pets.load_database(paths["database"])
    return render_template("user/pets.html", pets=pets_db)


@bp.route("/pets/<name>/edit", methods=["GET", "POST"])
@auth.login_required
def edit_pet(name):
    user = auth.current_user()
    paths = auth.user_paths(user["id"])
    pets_db = pets.load_database(paths["database"])

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

        pets.update_pet(paths["database"], name, pet_type, age, weight, feeding_amount, rel_path)
        flash(f"✓ Updated '{name}'.")
        return redirect(url_for("user.pets_page"))

    return render_template("user/pet_edit.html", name=name, pet=pets_db[name])


@bp.route("/pets/<name>/delete", methods=["POST"])
@auth.login_required
def delete_pet(name):
    user = auth.current_user()
    paths = auth.user_paths(user["id"])
    if pets.delete_pet(paths["database"], name):
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
    paths = auth.user_paths(user["id"])

    if request.method == "POST":
        action = request.form.get("action")
        if action == "manual_feed":
            devices.queue_feed_command(paths["device"], paths["device_events_log"])
            flash("✓ Feed command sent to your feeder — it will dispense shortly.")
        elif action == "update_schedule":
            # Schedule storage is intentionally simple for the MVP: stored
            # as plain text on the device record. Swap for a real
            # schedule model when recurring multi-pet schedules are needed.
            import json
            device = devices.get_device(paths["device"])
            device["feeding_schedule"] = request.form.get("schedule", "").strip()
            with open(paths["device"], "w") as f:
                json.dump(device, f, indent=2)
            flash("✓ Feeding schedule updated.")
        return redirect(url_for("user.feed_page"))

    device = devices.get_device(paths["device"])
    pets_db = pets.load_database(paths["database"])
    return render_template("user/feed.html", device=device, pets=pets_db)


# ============================================================================
# 4. AI Recognition — /user/ai
# ============================================================================

@bp.route("/ai", methods=["GET", "POST"])
@auth.login_required
def ai_page():
    user = auth.current_user()
    paths = auth.user_paths(user["id"])
    device = devices.get_device(paths["device"])
    result = None

    if request.method == "POST":
        image_file = request.files.get("frame")
        if not image_file or image_file.filename == "":
            flash("Please upload an image.", "error")
            return redirect(url_for("user.ai_page"))

        try:
            image = normalize_input(image_file)
            result = pipeline(
                image,
                database_path=paths["database"],
                log_path=paths["events_log"],
            )
            if result.get("pet") and result.get("pet") != "Unknown":
                pets.mark_detected(
                    paths["database"],
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
    paths = auth.user_paths(user["id"])
    events = _parse_events_log(paths["events_log"])

    parsed = []
    for event in events:
        m = re.search(r"\[(.*?)\] (.*)", event)
        if m:
            timestamp, msg = m.groups()
            if "no_animal_detected" in msg:
                continue
            if "Recognized" in msg:
                kind = "feeding"
                pet_name = _extract_pet_name(msg)
            else:
                kind = "unknown"
                pet_name = None
            parsed.append({
                "timestamp": timestamp,
                "message": msg,
                "kind": kind,
                "pet": pet_name,
                "time": timestamp.split("T")[1][:8] if "T" in timestamp else "—",
            })

    parsed.sort(key=lambda e: e["timestamp"], reverse=True)
    return {"events": parsed[:10]}


# ============================================================================
# 5. History — /user/history
# ============================================================================

@bp.route("/history")
@auth.login_required
def history_page():
    user = auth.current_user()
    paths = auth.user_paths(user["id"])

    events = _parse_events_log(paths["events_log"])
    device_events = _parse_events_log(paths["device_events_log"])

    parsed_events = []
    for event in events:
        m = re.search(r"\[(.*?)\] (.*)", event)
        if m:
            timestamp, msg = m.groups()
            # History is for things worth reviewing later: a pet being fed,
            # or an animal showing up that wasn't recognized. Empty-frame
            # "no animal detected" events fire constantly (every detection
            # cycle with nothing in view) and would drown out everything
            # else, so they're deliberately excluded here.
            if "no_animal_detected" in msg:
                continue
            kind = "feeding" if "Recognized" in msg else "detection"
            parsed_events.append({"timestamp": timestamp, "message": msg, "kind": kind})

    parsed_device_events = []
    for event in device_events:
        m = re.search(r"\[(.*?)\] (.*)", event)
        if m:
            timestamp, msg = m.groups()
            parsed_device_events.append({"timestamp": timestamp, "message": msg, "kind": "device"})

    combined = sorted(parsed_events + parsed_device_events, key=lambda e: e["timestamp"], reverse=True)
    return render_template("user/history.html", events=combined[:100])


# ============================================================================
# 6. Device — /user/device
# ============================================================================

@bp.route("/device")
@auth.login_required
def device_page():
    user = auth.current_user()
    paths = auth.user_paths(user["id"])
    device = devices.get_device(paths["device"])
    device_events = _parse_events_log(paths["device_events_log"])
    return render_template("user/device.html", device=device, device_events=device_events[-20:])
