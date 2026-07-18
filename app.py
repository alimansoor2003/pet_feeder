"""
app.py - PawSense Smart Pet Feeder
 
App factory only. All real route logic lives in routes/*.py, organized
by who's allowed to use them:
  routes/auth_routes.py   - shared login/signup/logout
  routes/user_routes.py   - pet-owner pages,  /user/*    (role: user or admin, just needs login)
  routes/admin_routes.py  - platform management, /admin/* (role: admin only)
  routes/api_routes.py    - ESP32 hardware contract, /api/device/*  (device API key, not a user login)
"""

import os

from flask import Flask, redirect, render_template, url_for

app = Flask(__name__)
# Session-signing key. Production MUST set the SECRET_KEY environment
# variable — the fallback below is only for local development, and
# anyone who knows it can forge login sessions.
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-production")

from routes.auth_routes import bp as auth_bp
from routes.user_routes import bp as user_bp
from routes.admin_routes import bp as admin_bp
from routes.api_routes import bp as api_bp

app.register_blueprint(auth_bp)
app.register_blueprint(user_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(api_bp)


@app.context_processor
def inject_current_user():
    """
    Make the logged-in user available to EVERY template as `user`.

    The shared user-area sidebar (templates/user/_nav.html) shows the
    account name/avatar on every page, but only some routes passed
    user= explicitly — pages like My Pets rendered a '?' avatar. A
    context processor fills the gap app-wide. Routes that already pass
    user= explicitly are unaffected: explicit render_template kwargs
    take precedence over context-processor values.
    """
    import auth
    return {"user": auth.current_user()}


@app.route("/")
def landing():
    """Public marketing homepage: mission, product, how it works."""
    return render_template("landing.html")


@app.errorhandler(403)
def forbidden(error):
    return render_template("403.html"), 403


@app.errorhandler(404)
def not_found(error):
    return redirect(url_for("landing"))


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("🐾 PawSense — Smart Pet Feeder")
    print("=" * 60)
    print("✓ Marketing site:      http://localhost:5000")
    print("✓ User dashboard:      http://localhost:5000/user/dashboard")
    print("✓ Admin dashboard:     http://localhost:5000/admin/dashboard")
    print("✓ ESP32 API base:      http://localhost:5000/api/device/<device_id>/...")
    print("=" * 60 + "\n")
    # Debug mode (auto-reload + in-browser debugger) is opt-in via
    # FLASK_DEBUG=1. Never enable it on a deployed server: the Werkzeug
    # debugger lets anyone who reaches the page run arbitrary code.
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    if not debug:
        print("  (dev tip: set FLASK_DEBUG=1 for auto-reload)")
    app.run(debug=debug, host="0.0.0.0", port=5000)
