from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from core.db import get_db, _get_db_prod, _get_db_local

auth_bp = Blueprint("auth", __name__)

@auth_bp.route("/")
def index():
    if "user_id" not in session:
        return redirect(url_for("auth.user_login"))
    if "env" not in session:
        return redirect(url_for("auth.env_login"))
    return redirect(url_for("dashboard.dashboard"))

@auth_bp.route("/user-login")
def user_login():
    try:
        conn = get_db()
        users = conn.execute("SELECT * FROM BOA.COR.[User] ORDER BY username").fetchall()
        conn.close()
    except RuntimeError as exc:
        flash(str(exc), "error")
        users = []
    return render_template("auth/user_login.html", users=users)

@auth_bp.route("/set-user", methods=["POST"])
def set_user():
    user_id = request.form.get("user_id")
    if not user_id:
        return redirect(url_for("auth.user_login"))

    try:
        conn = get_db()
        user = conn.execute("SELECT * FROM BOA.COR.[User] WHERE id = ?", (user_id,)).fetchone()
        conn.close()
    except RuntimeError:
        return redirect(url_for("auth.user_login"))

    if user:
        session["user_id"] = user["id"]
        session["username"] = user["username"]
        try:
            session["surname"] = user["surname"] or ""
            session["lang"] = user["default_language"] if user["default_language"] is not None else 0
            session["theme"] = user["default_theme"] if user.get("default_theme") else "dark"
        except Exception:
            # Fallback if columns don't exist during transition
            session["surname"] = ""
            session["lang"] = 0
            session["theme"] = "dark"
            
        return redirect(url_for("auth.env_login"))
    return redirect(url_for("auth.user_login"))

@auth_bp.route("/env-login")
def env_login():
    return render_template("auth/env_login.html")

@auth_bp.route("/set-env", methods=["POST"])
def set_env():
    env = request.form.get("env", "local")
    if env not in ("local", "prod"):
        env = "local"

    if env == "prod":
        try:
            conn = _get_db_prod()
            conn.close()
        except RuntimeError as exc:
            flash(str(exc), "error")
            return redirect(url_for("auth.env_login"))
    else:
        try:
            conn = _get_db_local()
            conn.close()
        except RuntimeError as exc:
            flash(str(exc), "error")
            return redirect(url_for("auth.env_login"))

    session["env"] = env
    return redirect(url_for("dashboard.dashboard"))

@auth_bp.route("/disconnect")
def disconnect():
    session.pop("env", None)
    session.pop("user_id", None)
    session.pop("username", None)
    session.pop("surname", None)
    session.pop("lang", None)
    return redirect(url_for("auth.user_login"))

@auth_bp.route("/set_language/<int:lang_id>")
def set_language(lang_id):
    if lang_id in (1, 2):
        session["lang"] = lang_id
        user_id = session.get("user_id")
        if user_id:
            conn = get_db()
            conn.execute("UPDATE BOA.COR.[User] SET default_language = ? WHERE id = ?", (lang_id, user_id))
            conn.commit()
            conn.close()
    return redirect(request.referrer or url_for("dashboard.dashboard"))

@auth_bp.route("/set_theme/<theme>")
def set_theme(theme):
    if theme in ("dark", "light"):
        session["theme"] = theme
        user_id = session.get("user_id")
        if user_id:
            try:
                conn = get_db()
                conn.execute("UPDATE BOA.COR.[User] SET default_theme = ? WHERE id = ?", (theme, user_id))
                conn.commit()
                conn.close()
            except Exception:
                pass # Ignore if column doesn't exist yet
    return redirect(request.referrer or url_for("dashboard.dashboard"))
