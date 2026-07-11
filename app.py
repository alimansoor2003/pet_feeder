"""
app.py - PawSense Smart Pet Feeder Web Application

Public marketing site (landing, signup, login) + a private per-user
dashboard. Auth lives in auth.py; this file just wires routes,
sessions, and per-user file paths together.
""" 
from dotenv import load_dotenv
load_dotenv()
import json
import os
from datetime import datetime
from functools import wraps

from flask import Flask, flash, redirect, render_template, request, session, url_for
from werkzeug.utils import secure_filename

import auth
import input_adapter
from pipeline import pipeline

APP_ROOT = os.path.dirname(os.path.abspath(__file__))
ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png"}

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-secret-key-change-in-production")

# ============================================================================
# HELPERS
# ============================================================================

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def current_user():
    """Return the logged-in user's dict, or None."""
    user_id = session.get("user_id")
    if not user_id:
        return None
    return auth.get_user_by_id(user_id)


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user():
            flash("Please log in to continue.", "error")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


def load_database(path):
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def save_database(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def load_feeding_log(path):
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def parse_events_log(log_path):
    events = []
    if os.path.exists(log_path):
        try:
            with open(log_path, "r") as f:
                for line in f.readlines()[-50:]:
                    if line.strip():
                        events.append(line.strip())
        except Exception:
            pass
    return events


def extract_pet_name(msg):
    import re
    match = re.search(r"'([^']+)'", msg)
    return match.group(1) if match else "Unknown"


def count_today_feedings(feeding_log_path):
    from datetime import date
    today = str(date.today())
    feeding_log = load_feeding_log(feeding_log_path)
    count = 0
    for pet_feedings in feeding_log.values():
        for feeding in pet_feedings:
            if feeding.get("date") == today:
                count += 1
    return count


# ============================================================================
# PUBLIC MARKETING ROUTES
# ============================================================================

@app.route("/")
def landing():
    """Public marketing homepage: mission, product, how it works."""
    return render_template("landing.html")


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if current_user():
        return redirect(url_for("home"))

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")

        user, error = auth.create_user(name, email, password)
        if error:
            flash(error, "error")
            return redirect(url_for("signup"))

        session["user_id"] = user["id"]
        flash(f"Welcome, {user['name']}! Your account is ready.")
        return redirect(url_for("home"))

    return render_template("signup.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user():
        return redirect(url_for("home"))

    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")

        user, error = auth.verify_login(email, password)
        if error:
            flash(error, "error")
            return redirect(url_for("login"))

        session["user_id"] = user["id"]
        flash(f"Welcome back, {user['name']}!")
        return redirect(url_for("home"))

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.pop("user_id", None)
    flash("You've been logged out.")
    return redirect(url_for("landing"))


# ============================================================================
# PRIVATE DASHBOARD ROUTES (login required)
# ============================================================================

@app.route("/app")
@login_required
def home():
    """Per-user dashboard."""
    user = current_user()
    paths = auth.user_paths(user["id"])

    pets_db = load_database(paths["database"])
    events = parse_events_log(os.path.join(paths["dir"], "events.log"))

    recent_events = []
    for event in events:
        try:
            import re
            match = re.search(r"\[(.*?)\] (.*)", event)
            if match:
                timestamp, msg = match.groups()
                is_allowed = "ALLOWED" in msg
                pet_name = extract_pet_name(msg)
                recent_events.append({
                    "timestamp": timestamp,
                    "pet": pet_name,
                    "action": "allow_feeding" if is_allowed else "deny",
                    "time": timestamp.split("T")[1][:5] if "T" in timestamp else "—",
                })
        except Exception:
            pass

    feedings_today = count_today_feedings(paths["feeding_log"])
    detections_today = len(recent_events)

    return render_template(
        "index.html",
        pets=pets_db,
        pet_count=len(pets_db),
        detections_today=detections_today,
        feedings_today=feedings_today,
        pending_alerts=0,
        recent_events=recent_events[-10:],
        user=user,
    )


@app.route("/app/register", methods=["GET", "POST"])
@login_required
def register():
    user = current_user()
    paths = auth.user_paths(user["id"])

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        image_file = request.files.get("image")

        if not name or not image_file or image_file.filename == "":
            flash("Pet name and image are both required.", "error")
            return redirect(url_for("register"))

        if not allowed_file(image_file.filename):
            flash("Only .jpg, .jpeg, .png images are allowed.", "error")
            return redirect(url_for("register"))

        filename = secure_filename(f"{name.lower()}_{image_file.filename}")
        save_path = os.path.join(paths["uploads"], filename)
        image_file.save(save_path)

        database = load_database(paths["database"])
        database[name] = {
            "image": os.path.relpath(save_path, APP_ROOT),
            "registered": str(datetime.now()),
            "last_detected": "Never",
            "last_fed": "Never",
        }
        save_database(paths["database"], database)

        flash(f"✓ Registered '{name}' successfully! Ready to detect.")
        return redirect(url_for("home"))

    return render_template("register.html")


@app.route("/app/detect", methods=["GET", "POST"])
@login_required
def detect():
    user = current_user()
    paths = auth.user_paths(user["id"])

    if request.method == "POST":
        image_file = request.files.get("frame")
        if not image_file or image_file.filename == "":
            flash("Please upload an image.", "error")
            return redirect(url_for("detect"))

        try:
            image = input_adapter.normalize_input(image_file)
            result = pipeline(
                image,
                database_path=paths["database"],
                log_path=os.path.join(paths["dir"], "events.log"),
            )
            
            # Update pet's last_detected and last_fed timestamps
            if result.get("pet") != "Unknown":
                pet_name = result.get("pet")
                database = load_database(paths["database"])
                if pet_name in database:
                    database[pet_name]["last_detected"] = datetime.now().strftime("%I:%M %p")
                    if result.get("action") == "allow_feeding":
                        database[pet_name]["last_fed"] = datetime.now().strftime("%I:%M %p")
                    save_database(paths["database"], database)
            
            return render_template("detect.html", result=result)
        except Exception as e:
            flash(f"Error: {str(e)}", "error")
            return redirect(url_for("detect"))

    return render_template("detect.html", result=None)


@app.route("/app/pet/<name>")
@login_required
def pet_profile(name):
    user = current_user()
    paths = auth.user_paths(user["id"])

    pets_db = load_database(paths["database"])
    if name not in pets_db:
        flash(f"Pet '{name}' not found.", "error")
        return redirect(url_for("home"))

    pet_info = pets_db[name]
    feeding_log = load_feeding_log(paths["feeding_log"])
    pet_feedings = feeding_log.get(name, [])

    return render_template(
        "pet_profile.html",
        name=name,
        pet=pet_info,
        feedings=pet_feedings[-50:],
        total_feedings=len(pet_feedings),
        image_path=pet_info.get("image"),
    )


@app.route("/app/stats")
@login_required
def stats():
    user = current_user()
    paths = auth.user_paths(user["id"])

    pets_db = load_database(paths["database"])
    events = parse_events_log(os.path.join(paths["dir"], "events.log"))

    events_by_pet = {}
    for event in events:
        try:
            import re
            match = re.search(r"\[(.*?)\] (.*)", event)
            if match:
                timestamp, msg = match.groups()
                pet_name = extract_pet_name(msg)
                events_by_pet.setdefault(pet_name, [])
                is_fed = "ALLOWED" in msg
                events_by_pet[pet_name].append({
                    "timestamp": timestamp,
                    "is_fed": is_fed,
                    "msg": msg,
                })
        except Exception:
            pass

    total_events = sum(len(v) for v in events_by_pet.values())
    total_feedings = sum(len([x for x in v if x["is_fed"]]) for v in events_by_pet.values())

    return render_template(
        "stats.html",
        pets=pets_db,
        events_by_pet=events_by_pet,
        total_events=total_events,
        total_feedings=total_feedings,
    )


@app.route("/app/debug-match", methods=["GET", "POST"])
@login_required
def debug_match():
    user = current_user()
    paths = auth.user_paths(user["id"])
    scores = {}

    if request.method == "POST":
        image_file = request.files.get("frame")
        if not image_file:
            flash("Please upload an image.", "error")
            return redirect(url_for("debug_match"))

        try:
            image = input_adapter.normalize_input(image_file)
            from identifier import Identifier

            identifier = Identifier(database_path=paths["database"])
            query_vector = identifier.embed(image)
            database = identifier._load_database()

            for name, info in database.items():
                pet_vector = identifier._get_pet_embedding(name, info["image"])
                if pet_vector is None:
                    scores[name] = "ERROR: image not found"
                    continue
                score = identifier._cosine_similarity(query_vector, pet_vector)
                scores[name] = round(score, 3)
        except Exception as e:
            flash(f"Error: {str(e)}", "error")

    return render_template("debug.html", scores=scores, threshold=0.75)


# ============================================================================
# ERROR HANDLERS
# ============================================================================

@app.errorhandler(404)
def not_found(error):
    return redirect(url_for("landing"))


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("🐾 PawSense — Smart Pet Feeder")
    print("=" * 60)
    print("✓ Starting Flask server...")
    print("✓ Marketing site: http://localhost:5000")
    print("✓ Dashboard (after login): http://localhost:5000/app")
    print("=" * 60 + "\n")
    app.run(debug=True, host="0.0.0.0", port=5000)
