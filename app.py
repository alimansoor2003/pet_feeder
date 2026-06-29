"""
app.py - PawSense Smart Pet Feeder

App factory only. All real route logic lives in routes/*.py, organized
by who's allowed to use them:
  routes/auth_routes.py   - shared login/signup/logout
  routes/user_routes.py   - pet-owner pages,  /user/*    (role: user or admin, just needs login)
  routes/admin_routes.py  - platform management, /admin/* (role: admin only)
  routes/api_routes.py    - ESP32 hardware contract, /api/device/*  (device API key, not a user login)
"""

from flask import Flask, redirect, render_template, url_for

app = Flask(__name__)
app.secret_key = "dev-secret-key-change-in-production"  # replace before real deployment

from routes.auth_routes import bp as auth_bp
from routes.user_routes import bp as user_bp
from routes.admin_routes import bp as admin_bp
from routes.api_routes import bp as api_bp

app.register_blueprint(auth_bp)
app.register_blueprint(user_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(api_bp)


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
    app.run(debug=True, host="0.0.0.0", port=5000)
