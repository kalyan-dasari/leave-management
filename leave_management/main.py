from flask import Blueprint, flash, g, redirect, render_template, request, url_for

from .db import execute, query
from .security import login_required, redirect_by_role

bp = Blueprint("main", __name__)


@bp.route("/")
def dashboard():
    if g.user is None:
        try:
            leave_types = query("SELECT * FROM leave_types WHERE active = 1 ORDER BY id")
            counts = {
                "total": (query("SELECT COUNT(*) AS c FROM leave_requests")[0]["c"]),
                "approved": (query("SELECT COUNT(*) AS c FROM leave_requests WHERE status IN ('Approved', 'Completed')")[0]["c"]),
                "pending": (query("SELECT COUNT(*) AS c FROM leave_requests WHERE status = 'Pending'")[0]["c"]),
                "depts": (query("SELECT COUNT(*) AS c FROM departments WHERE active = 1")[0]["c"]),
            }
        except Exception:
            leave_types = []
            counts = {"total": 0, "approved": 0, "pending": 0, "depts": 0}
        return render_template("index.html", leave_types=leave_types, stats=counts)
    return redirect(redirect_by_role(g.user["role"]))


@bp.route("/track", methods=["GET", "POST"])
def track():
    req_query = request.values.get("q", "").strip()
    leave_data = None
    timeline = []
    error = None
    if req_query:
        results = query(
            """SELECT r.*, u.name AS student_name, u.roll_no, u.email,
                      d.name AS dept_name, b.name AS branch_name, t.name AS leave_type_name
               FROM leave_requests r
               JOIN users u ON u.id = r.student_id
               LEFT JOIN departments d ON d.id = u.department_id
               LEFT JOIN branches b ON b.id = u.branch_id
               JOIN leave_types t ON t.id = r.leave_type_id
               WHERE UPPER(r.request_no) = UPPER(?) OR LOWER(u.email) = LOWER(?) OR UPPER(u.roll_no) = UPPER(?)
               ORDER BY r.created_at DESC LIMIT 1""",
            (req_query, req_query, req_query),
        )
        if results:
            leave_data = results[0]
            timeline = query(
                """SELECT a.*, u.name AS reviewer_name, u.role AS reviewer_role
                   FROM approvals a
                   JOIN users u ON u.id = a.reviewer_id
                   WHERE a.request_id = ?
                   ORDER BY a.action_at ASC""",
                (leave_data["id"],),
            )
        else:
            error = f"No leave request found matching '{req_query}'. Please check your Request Number (e.g. REQ-...) or Student Roll Number."
    return render_template("track.html", q=req_query, leave=leave_data, timeline=timeline, error=error)



@bp.route("/notifications")
@login_required
def notifications():
    rows = query(
        """SELECT n.*, r.request_no FROM notifications n
           LEFT JOIN leave_requests r ON r.id = n.request_id
           WHERE n.recipient_id = ? AND n.channel = 'in_app'
           ORDER BY n.sent_at DESC, n.id DESC LIMIT 200""",
        (g.user["id"],),
    )
    return render_template("notifications.html", notifications=rows)


@bp.route("/notifications/read", methods=["POST"])
@login_required
def mark_all_read():
    execute("UPDATE notifications SET is_read = 1 WHERE recipient_id = ? AND channel = 'in_app'", (g.user["id"],))
    flash("All notifications marked as read.", "info")
    return redirect(url_for("main.notifications"))


@bp.route("/notifications/<int:notif_id>/read", methods=["POST"])
@login_required
def mark_read(notif_id):
    execute(
        "UPDATE notifications SET is_read = 1 WHERE id = ? AND recipient_id = ?",
        (notif_id, g.user["id"]),
    )
    target = request.form.get("next") or url_for("main.notifications")
    if not target.startswith("/") or target.startswith("//"):
        target = url_for("main.notifications")
    return redirect(target)
