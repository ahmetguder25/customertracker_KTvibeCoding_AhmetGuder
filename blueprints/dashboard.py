from flask import Blueprint, render_template, redirect, url_for, session

dashboard_bp = Blueprint("dashboard", __name__)

@dashboard_bp.route("/app")
def dashboard():
    return render_template(
        "dashboard/dashboard.html",
        active_env=session.get("env", "local"),
    )

@dashboard_bp.route("/dashboard")
def dashboard_redirect():
    return redirect(url_for("dashboard.dashboard"))
