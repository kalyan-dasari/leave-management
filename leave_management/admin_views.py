import csv
import io

from flask import Blueprint, Response, flash, g, redirect, render_template, request, url_for
from werkzeug.security import generate_password_hash

from .audit import audit
from .db import execute, query, utcnow
from .security import roles_required
from .validators import page_number

bp = Blueprint("admin", __name__, url_prefix="/admin")


@bp.route("/")
@roles_required("admin")
def dashboard():
    counts = {
        s["status"]: s["n"]
        for s in query("SELECT status, COUNT(*) AS n FROM leave_requests GROUP BY status")
    }
    users_by_role = {r["role"]: r["n"] for r in query("SELECT role, COUNT(*) AS n FROM users GROUP BY role")}
    dept_activity = query(
        """SELECT d.name AS department_name, COUNT(r.id) AS requests,
                  SUM(CASE WHEN r.status = 'Pending' THEN 1 ELSE 0 END) AS pending
           FROM departments d
           LEFT JOIN users s ON s.department_id = d.id
           LEFT JOIN leave_requests r ON r.student_id = s.id
           GROUP BY d.id ORDER BY d.name"""
    )
    approval_time = query(
        """SELECT AVG((julianday(a.action_time) - julianday(r.created_at)) * 24 * 60) AS minutes
           FROM approvals a JOIN leave_requests r ON r.id = a.request_id
           WHERE a.action IN ('Approved', 'Rejected') AND r.current_level IN (1, 2)""",
        one=True,
    )
    outstanding = query(
        "SELECT COUNT(*) AS n FROM leave_requests WHERE status IN ('Pending', 'More Information Required')",
        one=True,
    )["n"]
    return render_template(
        "admin/dashboard.html",
        counts=counts,
        users_by_role=users_by_role,
        dept_activity=dept_activity,
        avg_minutes=round(approval_time["minutes"], 1) if approval_time and approval_time["minutes"] else None,
        outstanding=outstanding,
    )


# ---------- users ----------

def _user_form_values():
    return {
        "name": (request.form.get("name") or "").strip(),
        "roll_no": (request.form.get("roll_no") or "").strip(),
        "email": (request.form.get("email") or "").strip().lower(),
        "role": request.form.get("role") or "student",
        "department_id": request.form.get("department_id") or None,
        "branch_id": request.form.get("branch_id") or None,
        "password": request.form.get("password") or "",
    }


@bp.route("/users", methods=["GET", "POST"])
@roles_required("admin")
def users():
    if request.method == "POST":
        values = _user_form_values()
        errors = []
        if len(values["name"]) < 3:
            errors.append("Name must be at least 3 characters.")
        if "@" not in values["email"]:
            errors.append("A valid email is required.")
        if len(values["password"]) < 8:
            errors.append("Password must be at least 8 characters.")
        if values["role"] not in ("student", "faculty", "hod", "admin"):
            errors.append("Invalid role.")
        if values["role"] in ("student", "faculty", "hod") and not values["department_id"]:
            errors.append("Department is required for this role.")
        if query("SELECT id FROM users WHERE email = ?", (values["email"],), one=True):
            errors.append("Email already in use.")
        if errors:
            for err in errors:
                flash(err, "danger")
        else:
            cur = execute(
                """INSERT INTO users (name, roll_no, email, password_hash, role, department_id, branch_id, active, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)""",
                (
                    values["name"],
                    values["roll_no"],
                    values["email"],
                    generate_password_hash(values["password"]),
                    values["role"],
                    values["department_id"],
                    values["branch_id"],
                    utcnow(),
                ),
            )
            audit(g.user["id"], "user_created", "users", cur.lastrowid, {"email": values["email"], "role": values["role"]})
            flash(f"User {values['name']} created.", "success")
        return redirect(url_for("admin.users"))

    rows = query(
        """SELECT u.*, d.name AS department_name, b.name AS branch_name
           FROM users u
           LEFT JOIN departments d ON d.id = u.department_id
           LEFT JOIN branches b ON b.id = u.branch_id
           ORDER BY u.active DESC, u.role, u.name"""
    )
    departments = query("SELECT * FROM departments WHERE active = 1 ORDER BY name")
    branches = query("SELECT * FROM branches WHERE active = 1 ORDER BY name")
    return render_template("admin/users.html", users=rows, departments=departments, branches=branches)


@bp.route("/users/<int:user_id>/toggle", methods=["POST"])
@roles_required("admin")
def toggle_user(user_id):
    if user_id == g.user["id"]:
        flash("You cannot deactivate your own account.", "danger")
        return redirect(url_for("admin.users"))
    row = query("SELECT * FROM users WHERE id = ?", (user_id,), one=True)
    if row is None:
        return render_template("errors/404.html"), 404
    execute("UPDATE users SET active = ? WHERE id = ?", (0 if row["active"] else 1, user_id))
    audit(g.user["id"], "user_toggled", "users", user_id, {"active": not bool(row["active"])})
    flash(f"{row['name']} {'activated' if not row['active'] else 'deactivated'}.", "info")
    return redirect(url_for("admin.users"))


# ---------- departments / branches ----------

@bp.route("/departments", methods=["GET", "POST"])
@roles_required("admin")
def departments():
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        code = (request.form.get("code") or "").strip().upper()
        if not name or not code:
            flash("Name and code are required.", "danger")
        elif query("SELECT id FROM departments WHERE code = ?", (code,), one=True):
            flash("Department code already exists.", "danger")
        else:
            cur = execute("INSERT INTO departments (name, code, active) VALUES (?, ?, 1)", (name, code))
            audit(g.user["id"], "department_created", "departments", cur.lastrowid, {"name": name})
            flash("Department created.", "success")
        return redirect(url_for("admin.departments"))

    rows = query(
        """SELECT d.*, (SELECT COUNT(*) FROM users u WHERE u.department_id = d.id) AS members
           FROM departments d ORDER BY d.name"""
    )
    return render_template("admin/departments.html", departments=rows)


@bp.route("/departments/<int:dept_id>/toggle", methods=["POST"])
@roles_required("admin")
def toggle_department(dept_id):
    row = query("SELECT * FROM departments WHERE id = ?", (dept_id,), one=True)
    if row is None:
        return render_template("errors/404.html"), 404
    execute("UPDATE departments SET active = ? WHERE id = ?", (0 if row["active"] else 1, dept_id))
    audit(g.user["id"], "department_toggled", "departments", dept_id)
    return redirect(url_for("admin.departments"))


@bp.route("/branches", methods=["GET", "POST"])
@roles_required("admin")
def branches():
    departments = query("SELECT * FROM departments WHERE active = 1 ORDER BY name")
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        code = (request.form.get("code") or "").strip().upper()
        department_id = request.form.get("department_id") or None
        if not name or not code or not department_id:
            flash("Name, code and department are required.", "danger")
        elif query("SELECT id FROM branches WHERE code = ?", (code,), one=True):
            flash("Branch code already exists.", "danger")
        else:
            cur = execute(
                "INSERT INTO branches (department_id, name, code, active) VALUES (?, ?, ?, 1)",
                (department_id, name, code),
            )
            audit(g.user["id"], "branch_created", "branches", cur.lastrowid, {"name": name})
            flash("Branch created.", "success")
        return redirect(url_for("admin.branches"))

    rows = query(
        """SELECT b.*, d.name AS department_name FROM branches b
           JOIN departments d ON d.id = b.department_id ORDER BY d.name, b.name"""
    )
    return render_template("admin/branches.html", branches=rows, departments=departments)


@bp.route("/branches/<int:branch_id>/toggle", methods=["POST"])
@roles_required("admin")
def toggle_branch(branch_id):
    row = query("SELECT * FROM branches WHERE id = ?", (branch_id,), one=True)
    if row is None:
        return render_template("errors/404.html"), 404
    execute("UPDATE branches SET active = ? WHERE id = ?", (0 if row["active"] else 1, branch_id))
    audit(g.user["id"], "branch_toggled", "branches", branch_id)
    return redirect(url_for("admin.branches"))


# ---------- leave types ----------

@bp.route("/leave-types", methods=["GET", "POST"])
@roles_required("admin")
def leave_types():
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        description = (request.form.get("description") or "").strip()
        try:
            max_days = max(1, int(request.form.get("max_days") or 10))
        except ValueError:
            max_days = 10
        requires_document = 1 if request.form.get("requires_document") else 0
        hod_required = 1 if request.form.get("hod_required") else 0
        if not name:
            flash("Leave type name is required.", "danger")
        elif query("SELECT id FROM leave_types WHERE name = ?", (name,), one=True):
            flash("Leave type already exists.", "danger")
        else:
            cur = execute(
                """INSERT INTO leave_types (name, description, max_days, requires_document, hod_required, active)
                   VALUES (?, ?, ?, ?, ?, 1)""",
                (name, description, max_days, requires_document, hod_required),
            )
            audit(g.user["id"], "leave_type_created", "leave_types", cur.lastrowid, {"name": name})
            flash("Leave type created.", "success")
        return redirect(url_for("admin.leave_types"))

    rows = query(
        """SELECT t.*, (SELECT COUNT(*) FROM leave_requests r WHERE r.leave_type_id = t.id) AS requests
           FROM leave_types t ORDER BY t.name"""
    )
    return render_template("admin/leave_types.html", leave_types=rows)


@bp.route("/leave-types/<int:type_id>/toggle", methods=["POST"])
@roles_required("admin")
def toggle_leave_type(type_id):
    row = query("SELECT * FROM leave_types WHERE id = ?", (type_id,), one=True)
    if row is None:
        return render_template("errors/404.html"), 404
    execute("UPDATE leave_types SET active = ? WHERE id = ?", (0 if row["active"] else 1, type_id))
    audit(g.user["id"], "leave_type_toggled", "leave_types", type_id)
    return redirect(url_for("admin.leave_types"))


# ---------- holidays ----------

@bp.route("/holidays", methods=["GET", "POST"])
@roles_required("admin")
def holidays():
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        day = request.form.get("date") or ""
        if not name or not day:
            flash("Name and date are required.", "danger")
        elif query("SELECT id FROM holidays WHERE date = ?", (day,), one=True):
            flash("A holiday already exists on that date.", "danger")
        else:
            cur = execute("INSERT INTO holidays (name, date) VALUES (?, ?)", (name, day))
            audit(g.user["id"], "holiday_created", "holidays", cur.lastrowid, {"name": name, "date": day})
            flash("Holiday added.", "success")
        return redirect(url_for("admin.holidays"))
    rows = query("SELECT * FROM holidays ORDER BY date")
    return render_template("admin/holidays.html", holidays=rows)


@bp.route("/holidays/<int:holiday_id>/delete", methods=["POST"])
@roles_required("admin")
def delete_holiday(holiday_id):
    execute("DELETE FROM holidays WHERE id = ?", (holiday_id,))
    audit(g.user["id"], "holiday_deleted", "holidays", holiday_id)
    flash("Holiday removed.", "info")
    return redirect(url_for("admin.holidays"))


# ---------- reports & audit ----------

REPORTS = {
    "requests": (
        ["request_no", "student", "department", "leave_type", "start_date", "end_date", "status", "level", "created_at"],
        """SELECT r.request_no, s.name, COALESCE(d.name, ''), t.name, r.start_date, r.end_date, r.status, r.current_level, r.created_at
           FROM leave_requests r
           JOIN users s ON s.id = r.student_id
           JOIN leave_types t ON t.id = r.leave_type_id
           LEFT JOIN departments d ON d.id = s.department_id
           ORDER BY r.created_at DESC""",
    ),
    "usage": (
        ["student", "department", "leave_type", "requests", "approved_days"],
        """SELECT s.name, COALESCE(d.name, ''), t.name, COUNT(r.id),
                  COALESCE(SUM(CASE WHEN r.status IN ('Approved', 'Completed')
                      THEN CAST(julianday(r.end_date) - julianday(r.start_date) + 1 AS INT) ELSE 0 END), 0)
           FROM leave_requests r
           JOIN users s ON s.id = r.student_id
           JOIN leave_types t ON t.id = r.leave_type_id
           LEFT JOIN departments d ON d.id = s.department_id
           GROUP BY s.id, t.id ORDER BY s.name""",
    ),
    "outstanding": (
        ["request_no", "student", "department", "leave_type", "start_date", "end_date", "status", "level", "age_days"],
        """SELECT r.request_no, s.name, COALESCE(d.name, ''), t.name, r.start_date, r.end_date, r.status, r.current_level,
                  CAST(julianday('now') - julianday(r.created_at) AS INT)
           FROM leave_requests r
           JOIN users s ON s.id = r.student_id
           JOIN leave_types t ON t.id = r.leave_type_id
           LEFT JOIN departments d ON d.id = s.department_id
           WHERE r.status IN ('Pending', 'More Information Required')
           ORDER BY r.created_at""",
    ),
}


@bp.route("/reports")
@roles_required("admin")
def reports():
    kind = request.args.get("kind", "requests")
    if kind not in REPORTS:
        kind = "requests"
    headers, sql = REPORTS[kind]
    rows = query(sql)
    return render_template("admin/reports.html", kind=kind, headers=headers, rows=rows, report_kinds=list(REPORTS))


@bp.route("/reports/export")
@roles_required("admin")
def export_csv():
    kind = request.args.get("kind", "requests")
    if kind not in REPORTS:
        kind = "requests"
    headers, sql = REPORTS[kind]
    rows = query(sql)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(headers)
    for row in rows:
        writer.writerow([row[i] for i in range(len(headers))])
    audit(g.user["id"], "report_exported", "reports", None, {"kind": kind})
    return Response(
        buf.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=leave_{kind}.csv"},
    )


@bp.route("/audit")
@roles_required("admin")
def audit_logs():
    page = page_number(request.args.get("page"))
    per_page = 25
    total = query("SELECT COUNT(*) AS n FROM audit_logs", one=True)["n"]
    rows = query(
        """SELECT a.*, u.name AS user_name, u.email AS user_email
           FROM audit_logs a LEFT JOIN users u ON u.id = a.user_id
           ORDER BY a.created_at DESC, a.id DESC LIMIT ? OFFSET ?""",
        (per_page, (page - 1) * per_page),
    )
    return render_template("admin/audit.html", logs=rows, page=page, total=total, per_page=per_page)
