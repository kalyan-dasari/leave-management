import secrets
from datetime import datetime

from .db import execute, query, utcnow
from .notify import notify, notify_many

REVIEWABLE_STATUSES = ("Draft", "Pending", "More Information Required", "Cancelled")


def reviewers_for(department_id, role=None, level=None):
    """Active reviewers of a department. level 1 -> faculty (+hod), level 2 -> hod."""
    if role == "hod":
        sql = "SELECT id, name, email FROM users WHERE role = 'hod' AND department_id = ? AND active = 1"
    else:
        sql = "SELECT id, name, email FROM users WHERE role IN ('faculty', 'hod') AND department_id = ? AND active = 1"
    return query(sql, (department_id,))


def student_department(student_id):
    row = query("SELECT department_id FROM users WHERE id = ?", (student_id,), one=True)
    return row["department_id"] if row else None


def finalize_completed():
    """Move approved leaves whose end date has passed to Completed."""
    execute(
        "UPDATE leave_requests SET status = 'Completed', updated_at = ? WHERE status = 'Approved' AND end_date < date('now')",
        (utcnow(),),
    )


def new_request_no() -> str:
    return f"LR-{datetime.now():%Y%m%d}-{secrets.token_hex(2).upper()}"


def create_leave_request(*, student, leave_type, data, attachment_path=None):
    """Insert a Pending request and notify the department reviewers."""
    now = utcnow()
    cur = execute(
        """INSERT INTO leave_requests
           (request_no, student_id, leave_type_id, start_date, end_date, reason,
            contact_info, attachment_path, status, current_level, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'Pending', 1, ?, ?)""",
        (
            new_request_no(),
            student["id"],
            leave_type["id"],
            data["start_date"],
            data["end_date"],
            data["reason"],
            data["contact"],
            attachment_path,
            now,
            now,
        ),
    )
    request_id = cur.lastrowid
    request_no = query("SELECT request_no FROM leave_requests WHERE id = ?", (request_id,), one=True)["request_no"]

    recipients = [r["id"] for r in reviewers_for(student_department(student["id"]))]
    notify_many(
        recipients,
        f"New leave request {request_no} from {student['name']} ({data['start_date']} to {data['end_date']}).",
        request_id=request_id,
        subject=f"New leave request {request_no}",
        email_body=(
            f"A new leave request has been submitted.\n\n"
            f"Request: {request_no}\nStudent: {student['name']}\n"
            f"Dates: {data['start_date']} to {data['end_date']}\nReason: {data['reason']}"
        ),
    )
    notify(
        student["id"],
        f"Your leave request {request_no} has been submitted and is pending review.",
        request_id=request_id,
        subject=f"Leave request {request_no} submitted",
    )
    return request_id, request_no


def _insert_approval(request_id, reviewer_id, action, remarks, level):
    execute(
        "INSERT INTO approvals (request_id, reviewer_id, action, remarks, level, action_time) VALUES (?, ?, ?, ?, ?, ?)",
        (request_id, reviewer_id, action, remarks or "", level, utcnow()),
    )


def _deduct_balance(request_row, days):
    year = _year_of(request_row["start_date"])
    execute(
        """UPDATE leave_balances SET used = used + ?, remaining = remaining - ?
           WHERE student_id = ? AND leave_type_id = ? AND academic_year = ?""",
        (days, days, request_row["student_id"], request_row["leave_type_id"], year),
    )


def _year_of(start_date: str) -> str:
    from datetime import date as _date
    from .validators import academic_year

    return academic_year(_date.fromisoformat(start_date))


def request_days(request_row) -> int:
    from datetime import date as _date
    from .validators import working_days, load_holiday_dates

    holidays = load_holiday_dates(query)
    return working_days(
        _date.fromisoformat(request_row["start_date"]),
        _date.fromisoformat(request_row["end_date"]),
        holidays,
    )


def apply_decision(*, request_row, reviewer, action, remarks=""):
    """Apply approve / reject / request_info. Returns (status, message)."""
    level = request_row["current_level"]
    remarks = (remarks or "").strip()
    request_no = request_row["request_no"]
    student_id = request_row["student_id"]

    if action == "reject":
        if not remarks:
            return None, "A rejection reason is required."
        _insert_approval(request_row["id"], reviewer["id"], "Rejected", remarks, level)
        execute(
            "UPDATE leave_requests SET status = 'Rejected', updated_at = ? WHERE id = ?",
            (utcnow(), request_row["id"]),
        )
        notify(
            student_id,
            f"Your leave request {request_no} was rejected: {remarks}",
            request_id=request_row["id"],
            subject=f"Leave request {request_no} rejected",
        )
        return "Rejected", "Request rejected."

    if action == "request_info":
        _insert_approval(request_row["id"], reviewer["id"], "Requested Information", remarks, level)
        execute(
            "UPDATE leave_requests SET status = 'More Information Required', updated_at = ? WHERE id = ?",
            (utcnow(), request_row["id"]),
        )
        notify(
            student_id,
            f"More information is required for leave request {request_no}: {remarks or 'please clarify your request.'}",
            request_id=request_row["id"],
            subject=f"Information required for {request_no}",
        )
        return "More Information Required", "More information requested from the student."

    if action != "approve":
        return None, "Unknown action."

    leave_type = query("SELECT * FROM leave_types WHERE id = ?", (request_row["leave_type_id"],), one=True)
    if level == 1 and leave_type["hod_required"]:
        hod = query(
            "SELECT id FROM users WHERE role = 'hod' AND department_id = (SELECT department_id FROM users WHERE id = ?) AND active = 1",
            (student_id,),
            one=True,
        )
        if hod is not None:
            _insert_approval(request_row["id"], reviewer["id"], "Recommended", remarks, level)
            execute(
                "UPDATE leave_requests SET current_level = 2, updated_at = ? WHERE id = ?",
                (utcnow(), request_row["id"]),
            )
            notify(
                student_id,
                f"Leave request {request_no} was recommended by {reviewer['name']} and forwarded to the Head of Department.",
                request_id=request_row["id"],
                subject=f"Leave request {request_no} forwarded to HOD",
            )
            notify(
                hod["id"],
                f"Leave request {request_no} awaits your final approval (level 2).",
                request_id=request_row["id"],
                subject=f"Leave request {request_no} needs HOD approval",
            )
            return "Pending", "Recommended and forwarded to the Head of Department."

    _insert_approval(request_row["id"], reviewer["id"], "Approved", remarks, level)
    execute(
        "UPDATE leave_requests SET status = 'Approved', updated_at = ? WHERE id = ?",
        (utcnow(), request_row["id"]),
    )
    _deduct_balance(request_row, request_days(request_row))
    notify(
        student_id,
        f"Your leave request {request_no} has been approved{': ' + remarks if remarks else '.'}",
        request_id=request_row["id"],
        subject=f"Leave request {request_no} approved",
    )
    return "Approved", "Request approved."


def cancel_request(*, request_row, student):
    if request_row["student_id"] != student["id"]:
        return None, "Not allowed."
    if request_row["status"] not in ("Draft", "Pending", "More Information Required"):
        return None, "Only pending requests can be cancelled."
    execute(
        "UPDATE leave_requests SET status = 'Cancelled', updated_at = ? WHERE id = ?",
        (utcnow(), request_row["id"]),
    )
    reviewers = student_department(student["id"])
    for r in reviewers_for(reviewers):
        notify(
            r["id"],
            f"Leave request {request_row['request_no']} from {student['name']} was cancelled by the student.",
            request_id=request_row["id"],
        )
    return "Cancelled", "Request cancelled."


def respond_to_request(*, request_row, student, response):
    response = (response or "").strip()
    if len(response) < 5:
        return None, "Please provide a meaningful response."
    if request_row["status"] != "More Information Required":
        return None, "This request is not awaiting information."
    _insert_approval(request_row["id"], student["id"], "Response", response, request_row["current_level"])
    execute(
        "UPDATE leave_requests SET status = 'Pending', updated_at = ? WHERE id = ?",
        (utcnow(), request_row["id"]),
    )
    reviewers = reviewers_for(student_department(student["id"]))
    notify_many(
        [r["id"] for r in reviewers],
        f"Student {student['name']} responded to {request_row['request_no']}: {response}",
        request_id=request_row["id"],
        subject=f"Response on leave request {request_row['request_no']}",
    )
    return "Pending", "Response submitted."
