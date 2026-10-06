from datetime import timedelta

from .conftest import create_request, db_fetch, next_weekday, submit_leave

CASUAL = "SELECT id FROM leave_types WHERE name = 'Casual Leave'"
MEDICAL = "SELECT id FROM leave_types WHERE name = 'Medical Leave'"


def casual_id(app):
    return db_fetch(app, CASUAL)[0]["id"]


def medical_id(app):
    return db_fetch(app, MEDICAL)[0]["id"]


def count_requests(app):
    return db_fetch(app, "SELECT COUNT(*) AS n FROM leave_requests")[0]["n"]


def test_valid_submission(app, student_client):
    monday = next_weekday()
    before = count_requests(app)
    resp = submit_leave(
        student_client,
        leave_type_id=casual_id(app),
        start=monday,
        end=monday + timedelta(days=1),
    )
    assert b"submitted" in resp.data
    assert count_requests(app) == before + 1
    row = db_fetch(app, "SELECT * FROM leave_requests ORDER BY id DESC")[0]
    assert row["status"] == "Pending"
    assert row["request_no"].startswith("LR-")
    assert row["current_level"] == 1


def test_end_before_start_rejected(app, student_client):
    monday = next_weekday()
    before = count_requests(app)
    resp = submit_leave(
        student_client,
        leave_type_id=casual_id(app),
        start=monday + timedelta(days=2),
        end=monday,
    )
    assert b"End date cannot be before the start date" in resp.data
    assert count_requests(app) == before


def test_past_start_rejected(app, student_client):
    monday = next_weekday() - timedelta(days=14)
    resp = submit_leave(
        student_client,
        leave_type_id=casual_id(app),
        start=monday,
        end=monday + timedelta(days=1),
    )
    assert b"cannot start in the past" in resp.data


def test_short_reason_rejected(app, student_client):
    monday = next_weekday()
    resp = submit_leave(
        student_client,
        leave_type_id=casual_id(app),
        start=monday,
        end=monday + timedelta(days=1),
        reason="sick",
    )
    assert b"at least 10 characters" in resp.data


def test_missing_contact_rejected(app, student_client):
    monday = next_weekday()
    resp = student_client.post(
        "/student/new",
        data={
            "leave_type_id": casual_id(app),
            "start_date": monday.isoformat(),
            "end_date": (monday + timedelta(days=1)).isoformat(),
            "reason": "Family function at home.",
            "contact_info": "",
        },
        follow_redirects=True,
    )
    assert b"Emergency contact information is required" in resp.data


def test_weekend_only_range_rejected(app, student_client):
    monday = next_weekday()
    saturday = monday + timedelta(days=5)
    resp = submit_leave(
        student_client,
        leave_type_id=casual_id(app),
        start=saturday,
        end=saturday + timedelta(days=1),
    )
    assert b"no working days" in resp.data


def test_max_days_enforced(app, student_client):
    monday = next_weekday()
    resp = submit_leave(
        student_client,
        leave_type_id=casual_id(app),
        start=monday,
        end=monday + timedelta(days=13),
    )
    assert b"limited to 5 day(s)" in resp.data


def test_overlapping_request_rejected(app, student_client):
    monday = next_weekday()
    submit_leave(
        student_client,
        leave_type_id=casual_id(app),
        start=monday,
        end=monday + timedelta(days=1),
    )
    resp = submit_leave(
        student_client,
        leave_type_id=casual_id(app),
        start=monday + timedelta(days=1),
        end=monday + timedelta(days=2),
    )
    assert b"Overlapping request" in resp.data


def test_insufficient_balance_rejected(app, student_client):
    monday = next_weekday()
    from leave_management.validators import academic_year

    db_fetch(
        app,
        """SELECT b.id FROM leave_balances b JOIN users u ON u.id = b.student_id
           JOIN leave_types t ON t.id = b.leave_type_id
           WHERE u.email = ? AND t.name = 'Casual Leave' AND b.academic_year = ?""",
        ("student1@university.edu", academic_year(monday)),
    )
    from leave_management.db import execute

    with app.app_context():
        execute(
            """UPDATE leave_balances SET remaining = 0
               WHERE student_id = (SELECT id FROM users WHERE email = ?)
                 AND leave_type_id = (SELECT id FROM leave_types WHERE name = 'Casual Leave')""",
            ("student1@university.edu",),
        )
    resp = submit_leave(
        student_client,
        leave_type_id=casual_id(app),
        start=monday,
        end=monday + timedelta(days=1),
    )
    assert b"Insufficient Casual Leave leave balance" in resp.data


def test_medical_requires_document(app, student_client):
    monday = next_weekday()
    resp = submit_leave(
        student_client,
        leave_type_id=medical_id(app),
        start=monday,
        end=monday + timedelta(days=2),
        reason="Fever and doctor consultation advised rest.",
    )
    assert b"requires a supporting document" in resp.data


def test_valid_submission_with_attachment(app, student_client, tmp_path):
    monday = next_weekday()
    attachment = tmp_path / "doctor_note.pdf"
    attachment.write_bytes(b"%PDF-1.4 test")
    resp = student_client.post(
        "/student/new",
        data={
            "leave_type_id": medical_id(app),
            "start_date": monday.isoformat(),
            "end_date": (monday + timedelta(days=2)).isoformat(),
            "reason": "Fever and doctor consultation advised rest.",
            "contact_info": "9848012345",
            "attachment": (attachment, "doctor_note.pdf"),
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert b"submitted" in resp.data
    row = db_fetch(app, "SELECT * FROM leave_requests ORDER BY id DESC")[0]
    assert row["attachment_path"] is not None


def test_invalid_attachment_type_rejected(app, student_client, tmp_path):
    monday = next_weekday()
    bad = tmp_path / "malware.exe"
    bad.write_bytes(b"MZ")
    resp = student_client.post(
        "/student/new",
        data={
            "leave_type_id": medical_id(app),
            "start_date": monday.isoformat(),
            "end_date": (monday + timedelta(days=2)).isoformat(),
            "reason": "Fever and doctor consultation advised rest.",
            "contact_info": "9848012345",
            "attachment": (bad, "malware.exe"),
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert b"PDF, JPG or PNG" in resp.data
    assert count_requests(app) == db_fetch(app, "SELECT COUNT(*) AS n FROM leave_requests")[0]["n"]


def test_holiday_range_counts_only_working_days(app, student_client):
    from leave_management.db import execute
    from leave_management.validators import academic_year

    monday = next_weekday()
    with app.app_context():
        execute(
            "INSERT OR IGNORE INTO holidays (name, date) VALUES (?, ?)",
            ("Test Holiday", (monday + timedelta(days=2)).isoformat()),
        )
    resp = submit_leave(
        student_client,
        leave_type_id=casual_id(app),
        start=monday,
        end=monday + timedelta(days=4),
    )
    # Mon-Fri with Wednesday holiday => 4 working days, within the 5 day limit
    assert b"submitted" in resp.data
    row = db_fetch(app, "SELECT * FROM leave_requests ORDER BY id DESC")[0]
    assert row["status"] == "Pending"
