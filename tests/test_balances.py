from datetime import date, timedelta

from leave_management.validators import academic_year, working_days

from .conftest import create_request, db_fetch, next_weekday


def get_balance(app, email, type_name, year):
    rows = db_fetch(
        app,
        """SELECT b.* FROM leave_balances b
           JOIN users u ON u.id = b.student_id
           JOIN leave_types t ON t.id = b.leave_type_id
           WHERE u.email = ? AND t.name = ? AND b.academic_year = ?""",
        (email, type_name, year),
    )
    return dict(rows[0]) if rows else None


def ensure_balance(app, email, type_name, year, allocated=12):
    existing = get_balance(app, email, type_name, year)
    if existing:
        return existing
    from leave_management.db import execute

    with app.app_context():
        execute(
            """INSERT INTO leave_balances (student_id, leave_type_id, academic_year, allocated, used, remaining)
               SELECT id, (SELECT id FROM leave_types WHERE name = ?), ?, ?, 0, ?
               FROM users WHERE email = ?""",
            (type_name, year, allocated, allocated, email),
        )
    return get_balance(app, email, type_name, year)


def test_working_days_excludes_weekend():
    monday = next_weekday()
    assert working_days(monday, monday + timedelta(days=6)) == 5


def test_working_days_excludes_holidays():
    monday = next_weekday()
    holiday = (monday + timedelta(days=2)).isoformat()
    assert working_days(monday, monday + timedelta(days=4), {holiday}) == 4


def test_working_days_empty_range():
    saturday = next_weekday() + timedelta(days=5)
    assert working_days(saturday, saturday + timedelta(days=1)) == 0


def test_academic_year_boundaries():
    assert academic_year(date(2026, 10, 6)) == "2026-27"
    assert academic_year(date(2026, 7, 1)) == "2026-27"
    assert academic_year(date(2026, 6, 30)) == "2025-26"
    assert academic_year(date(2026, 1, 15)) == "2025-26"


def test_approval_deducts_working_days(app):
    from leave_management.workflow import apply_decision
    from leave_management.db import query

    monday = next_weekday()
    year = academic_year(monday)
    before = ensure_balance(app, "student1@university.edu", "Casual Leave", year)
    req_id, _ = create_request(
        app,
        student_email="student1@university.edu",
        leave_type_name="Casual Leave",
        start=monday,
        end=monday + timedelta(days=5),
    )
    unchanged = get_balance(app, "student1@university.edu", "Casual Leave", year)
    assert unchanged["used"] == before["used"]

    with app.app_context():
        request_row = query("SELECT * FROM leave_requests WHERE id = ?", (req_id,), one=True)
        reviewer = query("SELECT * FROM users WHERE role = 'faculty' AND department_id = 1 LIMIT 1", one=True)
        apply_decision(request_row=request_row, reviewer=reviewer, action="approve", remarks="ok")

    after = get_balance(app, "student1@university.edu", "Casual Leave", year)
    expected_days = working_days(monday, monday + timedelta(days=5))
    assert expected_days == 5
    assert after["used"] == before["used"] + 5
    assert after["remaining"] == before["remaining"] - 5


def test_approval_excludes_holidays(app):
    from leave_management.workflow import apply_decision
    from leave_management.db import execute, query

    monday = next_weekday()
    year = academic_year(monday)
    with app.app_context():
        execute(
            "INSERT OR IGNORE INTO holidays (name, date) VALUES (?, ?)",
            ("Balance Test Holiday", (monday + timedelta(days=2)).isoformat()),
        )
    before = ensure_balance(app, "student1@university.edu", "Casual Leave", year)
    req_id, _ = create_request(
        app,
        student_email="student1@university.edu",
        leave_type_name="Casual Leave",
        start=monday,
        end=monday + timedelta(days=5),
    )
    with app.app_context():
        request_row = query("SELECT * FROM leave_requests WHERE id = ?", (req_id,), one=True)
        reviewer = query("SELECT * FROM users WHERE role = 'faculty' AND department_id = 1 LIMIT 1", one=True)
        apply_decision(request_row=request_row, reviewer=reviewer, action="approve", remarks="ok")

    after = get_balance(app, "student1@university.edu", "Casual Leave", year)
    assert after["used"] == before["used"] + 4


def test_rejection_does_not_touch_balance(app):
    from leave_management.workflow import apply_decision
    from leave_management.db import query

    monday = next_weekday()
    year = academic_year(monday)
    before = ensure_balance(app, "student1@university.edu", "Casual Leave", year)
    req_id, _ = create_request(
        app,
        student_email="student1@university.edu",
        leave_type_name="Casual Leave",
        start=monday,
        end=monday + timedelta(days=1),
    )
    with app.app_context():
        request_row = query("SELECT * FROM leave_requests WHERE id = ?", (req_id,), one=True)
        reviewer = query("SELECT * FROM users WHERE role = 'faculty' AND department_id = 1 LIMIT 1", one=True)
        apply_decision(request_row=request_row, reviewer=reviewer, action="reject", remarks="Not needed.")

    after = get_balance(app, "student1@university.edu", "Casual Leave", year)
    assert after["used"] == before["used"]
    assert after["remaining"] == before["remaining"]


def test_cancellation_does_not_touch_balance(app, student_client):
    from .conftest import submit_leave

    monday = next_weekday()
    year = academic_year(monday)
    before = ensure_balance(app, "student1@university.edu", "Casual Leave", year)
    submit_leave(
        student_client,
        leave_type_id=db_fetch(app, "SELECT id FROM leave_types WHERE name = 'Casual Leave'")[0]["id"],
        start=monday,
        end=monday + timedelta(days=1),
    )
    req_id = db_fetch(app, "SELECT id FROM leave_requests ORDER BY id DESC")[0]["id"]
    student_client.post(f"/student/requests/{req_id}/cancel", follow_redirects=True)
    after = get_balance(app, "student1@university.edu", "Casual Leave", year)
    assert after["used"] == before["used"]
