import uuid
from datetime import date
from pathlib import Path

from flask import (
    Blueprint,
    current_app,
    flash,
    g,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for,
)
from werkzeug.utils import secure_filename

from .audit import audit
from .db import execute, query, utcnow
from .security import login_required, roles_required
from .validators import academic_year, load_holiday_dates, page_number, parse_date, validate_leave, working_days
from .workflow import cancel_request, create_leave_request, finalize_completed, respond_to_request

bp = Blueprint("student", __name__, url_prefix="/student")

ALLOWED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png"}
MAX_ATTACHMENT_BYTES = 5 * 1024 * 1024


def _ensure_student_balances(student_id):
    year = academic_year(date.today())
    active_types = query("SELECT id FROM leave_types WHERE active = 1")
    for lt in active_types:
        row = query(
            "SELECT id FROM leave_balances WHERE student_id = ? AND leave_type_id = ? AND academic_year = ?",
            (student_id, lt["id"], year),
            one=True,
        )
        if not row:
            execute(
                """INSERT INTO leave_balances (student_id, leave_type_id, academic_year, allocated, used, remaining)
                   VALUES (?, ?, ?, 5, 0, 5)""",
                (student_id, lt["id"], year),
            )



def _save_attachment(file):
    if not file or not file.filename:
        return None, None
    name = secure_filename(file.filename)
    ext = Path(name).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        return None, "Attachments must be PDF, JPG or PNG files."
    if file.content_length and file.content_length > MAX_ATTACHMENT_BYTES:
        return None, "Attachment must be 5 MB or smaller."
    upload_dir = Path(current_app.config["UPLOAD_FOLDER"])
    upload_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4().hex}{ext}"
    file.save(upload_dir / filename)
    if (upload_dir / filename).stat().st_size > MAX_ATTACHMENT_BYTES:
        (upload_dir / filename).unlink(missing_ok=True)
        return None, "Attachment must be 5 MB or smaller."
    return filename, None


@bp.route("/")
@roles_required("student")
def dashboard():
    finalize_completed()
    student_id = g.user["id"]
    status = request.args.get("status", "")
    leave_type = request.args.get("type", "")
    date_from = request.args.get("from", "")
    date_to = request.args.get("to", "")
    page = page_number(request.args.get("page"))

    where = ["r.student_id = ?"]
    args = [student_id]
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
    total = query(f"SELECT COUNT(*) AS n FROM leave_requests r WHERE {clause}", args, one=True)["n"]
    rows = query(
        f"""SELECT r.*, t.name AS leave_type_name, t.requires_document
            FROM leave_requests r JOIN leave_types t ON t.id = r.leave_type_id
            WHERE {clause}
            ORDER BY r.created_at DESC
            LIMIT ? OFFSET ?""",
        (*args, per_page, (page - 1) * per_page),
    )
    holidays = load_holiday_dates(query)
    requests = [
        {**dict(row), "days": working_days(parse_date(row["start_date"]), parse_date(row["end_date"]), holidays)}
        for row in rows
    ]
    stats = {
        s["status"]: s["n"]
        for s in query(
            "SELECT status, COUNT(*) AS n FROM leave_requests WHERE student_id = ? GROUP BY status",
            (student_id,),
        )
    }
    _ensure_student_balances(student_id)
    balances = query(
        """SELECT b.*, t.name AS leave_type_name FROM leave_balances b
           JOIN leave_types t ON t.id = b.leave_type_id
           WHERE b.student_id = ? ORDER BY t.name""",
        (student_id,),
    )
    leave_types = query("SELECT * FROM leave_types WHERE active = 1 ORDER BY name")
    return render_template(
        "student/dashboard.html",
        requests=requests,
        stats=stats,
        balances=balances,
        leave_types=leave_types,
        page=page,
        total=total,
        per_page=per_page,
        filters={"status": status, "type": leave_type, "from": date_from, "to": date_to},
    )


@bp.route("/new", methods=["GET", "POST"])
@roles_required("student")
def new_request():
    leave_types = query("SELECT * FROM leave_types WHERE active = 1 ORDER BY name")
    if request.method == "POST":
        leave_type = query(
            "SELECT * FROM leave_types WHERE id = ? AND active = 1",
            (request.form.get("leave_type_id") or 0,),
            one=True,
        )
        attachment_file = request.files.get("attachment")
        has_attachment = bool(attachment_file and attachment_file.filename)
        data, errors = validate_leave(
            student_id=g.user["id"],
            leave_type=leave_type,
            start_raw=request.form.get("start_date"),
            end_raw=request.form.get("end_date"),
            reason=request.form.get("reason"),
            contact=request.form.get("contact_info"),
            attachment_file=attachment_file,
            has_attachment=has_attachment,
            query=query,
        )
        if not errors and has_attachment:
            filename, err = _save_attachment(attachment_file)
            if err:
                errors.append(err)
            elif filename:
                data["attachment"] = filename

        if errors:
            for err in errors:
                flash(err, "danger")
            return render_template(
                "student/form.html",
                leave_types=leave_types,
                form=request.form,
                today=date.today().isoformat(),
            )

        request_id, request_no = create_leave_request(
            student=g.user,
            leave_type=leave_type,
            data=data,
            attachment_path=data.get("attachment"),
        )
        audit(g.user["id"], "request_created", "leave_requests", request_id, {"request_no": request_no})
        flash(f"Leave request {request_no} submitted ({data['days']} working day(s)).", "success")
        return redirect(url_for("student.detail", request_id=request_id))
    return render_template("student/form.html", leave_types=leave_types, form={}, today=date.today().isoformat())


def _get_own_request(request_id):
    row = query(
        """SELECT r.*, t.name AS leave_type_name, t.requires_document, t.description AS leave_type_description,
                  s.name AS student_name, s.roll_no, s.email AS student_email,
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
    if row is None or row["student_id"] != g.user["id"]:
        return None
    return row


@bp.route("/requests/<int:request_id>")
@roles_required("student")
def detail(request_id):
    row = _get_own_request(request_id)
    if row is None:
        return render_template("errors/404.html"), 404
    timeline = query(
        """SELECT a.*, u.name AS reviewer_name, u.role AS reviewer_role
           FROM approvals a JOIN users u ON u.id = a.reviewer_id
           WHERE a.request_id = ? ORDER BY a.action_time, a.id""",
        (request_id,),
    )
    return render_template("student/detail.html", leave=row, timeline=timeline)


@bp.route("/requests/<int:request_id>/cancel", methods=["POST"])
@roles_required("student")
def cancel(request_id):
    row = _get_own_request(request_id)
    if row is None:
        return render_template("errors/404.html"), 404
    status, message = cancel_request(request_row=row, student=g.user)
    if status is None:
        flash(message, "danger")
    else:
        audit(g.user["id"], "request_cancelled", "leave_requests", request_id)
        flash(message, "info")
    return redirect(url_for("student.detail", request_id=request_id))


@bp.route("/requests/<int:request_id>/respond", methods=["POST"])
@roles_required("student")
def respond(request_id):
    row = _get_own_request(request_id)
    if row is None:
        return render_template("errors/404.html"), 404
    status, message = respond_to_request(
        request_row=row, student=g.user, response=request.form.get("response")
    )
    if status is None:
        flash(message, "danger")
    else:
        audit(g.user["id"], "response_submitted", "leave_requests", request_id)
        flash(message, "success")
    return redirect(url_for("student.detail", request_id=request_id))


@bp.route("/balances")
@roles_required("student")
def balances():
    _ensure_student_balances(g.user["id"])
    rows = query(
        """SELECT b.*, t.name AS leave_type_name, t.description
           FROM leave_balances b JOIN leave_types t ON t.id = b.leave_type_id
           WHERE b.student_id = ? ORDER BY t.name""",
        (g.user["id"],),
    )
    return render_template("student/balances.html", balances=rows, year=academic_year(date.today()))


@bp.route("/attachments/<int:request_id>")
@roles_required("student")
def attachment(request_id):
    row = _get_own_request(request_id)
    if row is None or not row["attachment_path"]:
        return render_template("errors/404.html"), 404
    return send_from_directory(current_app.config["UPLOAD_FOLDER"], row["attachment_path"], as_attachment=True)
