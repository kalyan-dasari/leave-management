from flask import Blueprint, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from .audit import audit
from .db import execute, query, utcnow
from .security import redirect_by_role

bp = Blueprint("auth", __name__)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(redirect_by_role(g.user["role"]))
    if request.method == "POST":
        email = (request.form.get("email") or "").strip()
        password = request.form.get("password") or ""
        user = query("SELECT * FROM users WHERE email = ?", (email,), one=True)
        if user and check_password_hash(user["password_hash"], password) and user["active"]:
            session.clear()
            session["user_id"] = user["id"]
            audit(user["id"], "login", "users", user["id"])
            flash(f"Welcome back, {user['name']}.", "success")
            nxt = request.args.get("next")
            if nxt and nxt.startswith("/") and not nxt.startswith("//"):
                return redirect(nxt)
            return redirect(redirect_by_role(user["role"]))
        audit(None, "login_failed", "users", user["id"] if user else None, {"email": email})
        flash("Invalid email or password.", "danger")
    return render_template("auth/login.html")


@bp.route("/register", methods=["GET", "POST"])
def register():
    if g.user:
        return redirect(redirect_by_role(g.user["role"]))
    departments = query("SELECT * FROM departments WHERE active = 1 ORDER BY name")
    branches = query("SELECT * FROM branches WHERE active = 1 ORDER BY name")
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        roll_no = (request.form.get("roll_no") or "").strip()
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        confirm = request.form.get("confirm") or ""
        department_id = request.form.get("department_id") or None
        branch_id = request.form.get("branch_id") or None

        errors = []
        if len(name) < 3:
            errors.append("Name must be at least 3 characters.")
        if not roll_no:
            errors.append("Roll number is required.")
        if "@" not in email:
            errors.append("A valid email address is required.")
        if len(password) < 8:
            errors.append("Password must be at least 8 characters.")
        if password != confirm:
            errors.append("Passwords do not match.")
        if not department_id:
            errors.append("Please select a department.")
        if query("SELECT id FROM users WHERE email = ?", (email,), one=True):
            errors.append("An account with this email already exists.")

        if errors:
            for err in errors:
                flash(err, "danger")
            return render_template("auth/register.html", departments=departments, branches=branches, form=request.form)

        cur = execute(
            """INSERT INTO users (name, roll_no, email, password_hash, role, department_id, branch_id, active, created_at)
               VALUES (?, ?, ?, ?, 'student', ?, ?, 1, ?)""",
            (name, roll_no, email, generate_password_hash(password), department_id, branch_id, utcnow()),
        )
        student_id = cur.lastrowid
        audit(student_id, "register", "users", student_id)

        # Allocate 5 days of leave balance per registration for all active leave types
        from datetime import date
        from .validators import academic_year
        year = academic_year(date.today())
        active_types = query("SELECT id FROM leave_types WHERE active = 1")
        for lt in active_types:
            execute(
                """INSERT INTO leave_balances (student_id, leave_type_id, academic_year, allocated, used, remaining)
                   VALUES (?, ?, ?, 5, 0, 5)""",
                (student_id, lt["id"], year),
            )

        flash("Account created with 5 days allocated leave balances. Please sign in.", "success")
        return redirect(url_for("auth.login"))
    return render_template("auth/register.html", departments=departments, branches=branches, form={})


@bp.route("/logout", methods=["POST"])
def logout():
    user_id = session.get("user_id")
    if user_id:
        audit(user_id, "logout", "users", user_id)
    session.clear()
    flash("You have been signed out.", "info")
    return redirect(url_for("auth.login"))
