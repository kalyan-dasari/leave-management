from seed import PASSWORDS

from .conftest import db_fetch, login


def test_login_success(client):
    resp = login(client, "student1@university.edu")
    assert resp.status_code == 200
    assert b"My leave requests" in resp.data


def test_login_wrong_password(client):
    resp = login(client, "student1@university.edu", "wrong-password")
    assert b"Invalid email or password" in resp.data
    assert b"My leave requests" not in resp.data


def test_login_unknown_email(client):
    resp = login(client, "nobody@university.edu", "whatever123")
    assert b"Invalid email or password" in resp.data


def test_protected_route_redirects_anonymous(client):
    resp = client.get("/student/")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_register_and_login(app):
    client = app.test_client()
    resp = client.post(
        "/register",
        data={
            "name": "New Student",
            "roll_no": "22B81A0599",
            "email": "new.student@university.edu",
            "password": "StrongPass@1",
            "confirm": "StrongPass@1",
            "department_id": "1",
            "branch_id": "1",
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b"Account created" in resp.data

    resp = login(client, "new.student@university.edu", "StrongPass@1")
    assert b"My leave requests" in resp.data


def test_register_rejects_mismatched_password(app):
    client = app.test_client()
    client.post(
        "/register",
        data={
            "name": "New Student",
            "roll_no": "22B81A0598",
            "email": "new.student2@university.edu",
            "password": "StrongPass@1",
            "confirm": "DifferentPass@1",
            "department_id": "1",
        },
        follow_redirects=True,
    )
    users = db_fetch(app, "SELECT id FROM users WHERE email = ?", ("new.student2@university.edu",))
    assert users == []


def test_duplicate_email_rejected(app):
    client = app.test_client()
    client.post(
        "/register",
        data={
            "name": "Dup Student",
            "roll_no": "22B81A0597",
            "email": "student1@university.edu",
            "password": "StrongPass@1",
            "confirm": "StrongPass@1",
            "department_id": "1",
        },
        follow_redirects=True,
    )
    count = db_fetch(app, "SELECT COUNT(*) AS n FROM users WHERE email = ?", ("student1@university.edu",))[0]["n"]
    assert count == 1


def test_inactive_user_cannot_login(app, student_client):
    db_fetch(app, "SELECT id FROM users WHERE email = ?", ("student1@university.edu",))
    from leave_management.db import execute

    with app.app_context():
        execute("UPDATE users SET active = 0 WHERE email = ?", ("student1@university.edu",))
    client = app.test_client()
    resp = login(client, "student1@university.edu")
    assert b"Invalid email or password" in resp.data


def test_student_cannot_access_admin(student_client):
    resp = student_client.get("/admin/")
    assert resp.status_code == 403


def test_faculty_cannot_access_admin(faculty_client):
    resp = faculty_client.get("/admin/users")
    assert resp.status_code == 403


def test_admin_cannot_apply_as_student(admin_client):
    resp = admin_client.get("/student/new")
    assert resp.status_code == 403


def test_logout(client):
    login(client, "student1@university.edu")
    resp = client.post("/logout", follow_redirects=True)
    assert b"signed out" in resp.data
    assert client.get("/student/").status_code == 302


def test_csrf_enforced_in_production_mode(tmp_path):
    app = create_csrf_app(tmp_path)
    client = app.test_client()
    resp = client.post("/login", data={"email": "a@b.c", "password": "password1"})
    assert resp.status_code == 400


def create_csrf_app(tmp_path):
    from leave_management import create_app

    return create_app(
        {
            "TESTING": False,
            "SECRET_KEY": "test-secret-key",
            "DATABASE": str(tmp_path / "csrf.db"),
            "UPLOAD_FOLDER": str(tmp_path / "uploads"),
            "WTF_CSRF_ENABLED": True,
            "MAIL_USERNAME": None,
            "MAIL_PASSWORD": None,
        }
    )
