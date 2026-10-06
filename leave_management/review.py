from flask import Blueprint, current_app, flash, g, redirect, render_template, request, url_for

from .audit import audit
from .db import query
from .security import roles_required
from .validators import parse_date
from .workflow import apply_decision, finalize_completed

bp = Blueprint("review", __name__, url_prefix="/review")

REVIEW_ROLES = ("faculty", "hod", "admin")


def _visible_requests():
    """Requests the current reviewer may see: own department (admin sees all)."""
    if g.user["role"] == "admin":
        return "1=1", []
    return "s.department_id = ?", [g.user["department_id"]]


def _load_request(request_id):
    row = query(
        """SELECT r.*, t.name AS leave_type_name, t.requires_document, t.hod_required,
                  s.name AS student_name, s.roll_no, s.email AS student_email, s.department_id,
                  d.name AS department_name, b.name AS branch_name
           FROM leave_requests r
           JOIN leave_types t ON t.id = r.leave_type_id
           JOIN users s ON s.id = r.student_id
           LEFT JOIN departments d ON d.id = s.department_id
           LEFT JOIN branches b ON b.id = s.branch_id
           WHERE r.id = ?""",
        (request_id,),
        one=True,
    )
    if row is None:
        return None
    dept_clause, dept_args = _visible_requests()
    if not query(f"SELECT 1 FROM users s WHERE s.id = ? AND {dept_clause}", (row["student_id"], *dept_args), one=True):
        return None
    return row


def _allowed_levels():
    if g.user["role"] == "faculty":
        return (1,)
    return (1, 2)


@bp.route("/")
@roles_required(*REVIEW_ROLES)
def dashboard():
    finalize_completed()
    status = request.args.get("status", "")
    leave_type = request.args.get("type", "")
    date_from = request.args.get("from", "")
    date_to = request.args.get("to", "")
    page = max(int(request.args.get("page", 1) or 1), 1)

    dept_clause, dept_args = _visible_requests()
    where = [dept_clause]
    args = list(dept_args)
    if g.user["role"] == "faculty":
        where.append("(r.current_level = 1 OR r.status != 'Pending')")
    elif g.user["role"] == "hod":
        where.append("(r.current_level = 2 OR r.status != 'Pending')")
    if status:
        where.append("r.status = ?")
        args.append(status)
    if leave_type:
        where.append("r.leave_type_id = ?")
        args.append(int(leave_type))
    if parse_date(date_from):
        where.append("r.end_date >= ?")
        args.append(date_from)
    if parse_date(date_to):
        where.append("r.start_date <= ?")
        args.append(date_to)
    clause = " AND ".join(where)

    per_page = current_app.config["PER_PAGE"]
    total = query(f"SELECT COUNT(*) AS n FROM leave_requests r JOIN users s ON s.id = r.student_id WHERE {clause}", args, one=True)["n"]
    rows = query(
        f"""SELECT r.*, t.name AS leave_type_name, s.name AS student_name, s.roll_no,
                  d.name AS department_name, b.name AS branch_name
           FROM leave_requests r
           JOIN users s ON s.id = r.student_id
           JOIN leave_types t ON t.id = r.leave_type_id
           LEFT JOIN departments d ON d.id = s.department_id
           LEFT JOIN branches b ON b.id = s.branch_id
           WHERE {clause}
           ORDER BY CASE WHEN r.status = 'Pending' THEN 0 ELSE 1 END, r.created_at DESC
           LIMIT ? OFFSET ?""",
        (*args, per_page, (page - 1) * per_page),
    )
    queue = query(
        f"""SELECT COUNT(*) AS n FROM leave_requests r JOIN users s ON s.id = r.student_id
            WHERE {dept_clause} AND r.status IN ('Pending', 'More Information Required')
              AND {'r.current_level = 1' if g.user['role'] == 'faculty' else ('r.current_level = 2' if g.user['role'] == 'hod' else '1=1')}""",
        dept_args,
        one=True,
    )["n"]
    leave_types = query("SELECT * FROM leave_types ORDER BY name")
    return render_template(
        "review/dashboard.html",
        requests=rows,
        queue_count=queue,
        leave_types=leave_types,
        page=page,
        total=total,
        per_page=per_page,
        filters={"status": status, "type": leave_type, "from": date_from, "to": date_to},
    )


@bp.route("/requests/<int:request_id>")
@roles_required(*REVIEW_ROLES)
def detail(request_id):
    leave = _load_request(request_id)
    if leave is None:
        return render_template("errors/404.html"), 404
    timeline = query(
        """SELECT a.*, u.name AS reviewer_name, u.role AS reviewer_role
           FROM approvals a JOIN users u ON u.id = a.reviewer_id
           WHERE a.request_id = ? ORDER BY a.action_time, a.id""",
        (request_id,),
    )
    can_decide = (
        leave["status"] in ("Pending", "More Information Required")
        and leave["current_level"] in _allowed_levels()
    )
    return render_template("review/detail.html", leave=leave, timeline=timeline, can_decide=can_decide)


@bp.route("/requests/<int:request_id>/decision", methods=["POST"])
@roles_required(*REVIEW_ROLES)
def decision(request_id):
    leave = _load_request(request_id)
    if leave is None:
        return render_template("errors/404.html"), 404
    if leave["status"] not in ("Pending", "More Information Required"):
        flash("This request has already been decided.", "warning")
        return redirect(url_for("review.detail", request_id=request_id))
    if leave["current_level"] not in _allowed_levels():
        flash("This request is not at your approval level.", "danger")
        return redirect(url_for("review.detail", request_id=request_id))

    action = request.form.get("action")
    remarks = request.form.get("remarks") or ""
    status, message = apply_decision(request_row=leave, reviewer=g.user, action=action, remarks=remarks)
    if status is None:
        flash(message, "danger")
    else:
        audit(
            g.user["id"],
            f"request_{action}",
            "leave_requests",
            request_id,
            {"request_no": leave["request_no"], "status": status, "remarks": remarks},
        )
        flash(f"{leave['request_no']}: {message}", "success" if status == "Approved" else "info")
    return redirect(url_for("review.detail", request_id=request_id))
