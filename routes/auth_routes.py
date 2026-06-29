"""
routes/auth_routes.py
----------------------
/login, /signup, /logout — the single authentication system shared by
both roles. The ONLY branch point for role is right after a successful
login: user -> /user/dashboard, admin -> /admin/dashboard.

Signup never accepts a role field from the form — auth.create_user()
always defaults to role="user" unless called by create_admin.py.
"""

import os

from flask import Blueprint, flash, redirect, render_template, request, session, url_for

import auth
import devices

bp = Blueprint("auth", __name__)


@bp.route("/signup", methods=["GET", "POST"])
def signup():
    if auth.current_user():
        return redirect(url_for("auth.post_login_redirect"))

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")

        # role is intentionally NEVER read from request.form here.
        user, error = auth.create_user(name, email, password)
        if error:
            flash(error, "error")
            return redirect(url_for("auth.signup"))

        paths = auth.user_paths(user["id"])
        devices.create_default_device(paths["device"])

        session["user_id"] = user["id"]
        flash(f"Welcome, {user['name']}! Your account is ready.")
        return redirect(url_for("user.dashboard"))

    return render_template("signup.html")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if auth.current_user():
        return redirect(url_for("auth.post_login_redirect"))

    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")

        user, error = auth.verify_login(email, password)
        if error:
            flash(error, "error")
            return redirect(url_for("auth.login"))

        session["user_id"] = user["id"]
        flash(f"Welcome back, {user['name']}!")
        return redirect(url_for("auth.post_login_redirect"))

    return render_template("login.html")


@bp.route("/logout")
def logout():
    session.pop("user_id", None)
    flash("You've been logged out.")
    return redirect(url_for("landing"))


@bp.route("/post-login-redirect")
def post_login_redirect():
    """Single place that implements the role -> dashboard rule, so both
    /login and any future SSO callback route stay consistent."""
    user = auth.current_user()
    if not user:
        return redirect(url_for("auth.login"))
    if user.get("role") == "admin":
        return redirect(url_for("admin.dashboard"))
    return redirect(url_for("user.dashboard"))
