from datetime import date, timedelta

import pytest

from leave_management import create_app
from seed import PASSWORDS, seed_demo


def next_weekday(days_ahead=7):
    """Return a date at least `days_ahead` days out that falls on a Monday."""
    day = date.today() + timedelta(days=days_ahead)
    while day.weekday() != 0:
        day += timedelta(days=1)
    return day


@pytest.fixture
def app(tmp_path):
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret-key",
            "DATABASE": str(tmp_path / "test.db"),
            "UPLOAD_FOLDER": str(tmp_path / "uploads"),
            "WTF_CSRF_ENABLED": False,
            "MAIL_USERNAME": None,
            "MAIL_PASSWORD": None,
        }
    )
    with app.app_context():
        seed_demo()
    return app


@pytest.fixture
def client(app):
    return app.test_client()


def login(client, email, password=PASSWORDS["student"]):
    return client.post("/login", data={"email": email, "password": password}, follow_redirects=True)


@pytest.fixture
def student_client(app):
    client = app.test_client()
    login(client, "student1@university.edu")
    return client


@pytest.fixture
def student2_client(app):
    client = app.test_client()
    login(client, "student2@university.edu")
    return client


@pytest.fixture
def faculty_client(app):
    client = app.test_client()
    login(client, "faculty.cse@university.edu", PASSWORDS["faculty"])
    return client


@pytest.fixture
def faculty_ece_client(app):
    client = app.test_client()
    login(client, "faculty.ece@university.edu", PASSWORDS["faculty"])
    return client


@pytest.fixture
def hod_client(app):
    client = app.test_client()
    login(client, "hod.cse@university.edu", PASSWORDS["hod"])
    return client


@pytest.fixture
def admin_client(app):
    client = app.test_client()
    login(client, "admin@university.edu", PASSWORDS["admin"])
    return client


def submit_leave(client, *, leave_type_id, start, end, reason="Family function at home.", contact="9848012345", follow=True):
    return client.post(
        "/student/new",
        data={
            "leave_type_id": leave_type_id,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "reason": reason,
            "contact_info": contact,
        },
        follow_redirects=follow,
    )


def create_request(app, *, student_email, leave_type_name, start, end, reason="Medical rest advised by doctor.", contact="9848012345"):
    """Create a leave request directly through the workflow (no HTTP)."""
    from leave_management.db import query
    from leave_management.workflow import create_leave_request

    with app.app_context():
        student = query("SELECT * FROM users WHERE email = ?", (student_email,), one=True)
        leave_type = query("SELECT * FROM leave_types WHERE name = ?", (leave_type_name,), one=True)
        return create_leave_request(
            student=student,
            leave_type=leave_type,
            data={
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "days": (end - start).days + 1,
                "reason": reason,
                "contact": contact,
                "academic_year": "2026-27",
                "remaining_after": 0,
            },
        )


def decide(app, request_id, reviewer_email, action, remarks=""):
    from leave_management.db import query
    from leave_management.workflow import apply_decision

    with app.app_context():
        request_row = query("SELECT * FROM leave_requests WHERE id = ?", (request_id,), one=True)
        reviewer = query("SELECT * FROM users WHERE email = ?", (reviewer_email,), one=True)
        return apply_decision(request_row=request_row, reviewer=reviewer, action=action, remarks=remarks)


def db_fetch(app, sql, args=()):
    from leave_management.db import query

    with app.app_context():
        return query(sql, args)


def db_execute(app, sql, args=()):
    from leave_management.db import execute

    with app.app_context():
        execute(sql, args)
