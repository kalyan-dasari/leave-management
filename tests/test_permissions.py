from datetime import timedelta

from .conftest import create_request, db_fetch, next_weekday, submit_leave


def test_student_cannot_view_others_request(app, student_client, student2_client):
    monday = next_weekday()
    req_id, _ = create_request(
        app,
        student_email="student2@university.edu",
        leave_type_name="Casual Leave",
        start=monday,
        end=monday + timedelta(days=1),
    )
    own = student2_client.get(f"/student/requests/{req_id}")
    assert own.status_code == 200

    other = student_client.get(f"/student/requests/{req_id}")
    assert other.status_code == 404


def test_student_cannot_cancel_others_request(app, student_client, student2_client):
    monday = next_weekday()
    req_id, _ = create_request(
        app,
        student_email="student2@university.edu",
        leave_type_name="Casual Leave",
        start=monday,
        end=monday + timedelta(days=1),
    )
    student_client.post(f"/student/requests/{req_id}/cancel", follow_redirects=True)
    row = db_fetch(app, "SELECT status FROM leave_requests WHERE id = ?", (req_id,))[0]
    assert row["status"] == "Pending"


def test_student_cannot_respond_to_others_request(app, student_client):
    monday = next_weekday()
    req_id, _ = create_request(
        app,
        student_email="student2@university.edu",
        leave_type_name="Casual Leave",
        start=monday,
        end=monday + timedelta(days=1),
    )
    student_client.post(
        f"/student/requests/{req_id}/respond",
        data={"response": "Here is the clarification."},
        follow_redirects=True,
    )
    row = db_fetch(app, "SELECT status FROM leave_requests WHERE id = ?", (req_id,))[0]
    assert row["status"] == "Pending"


def test_faculty_of_other_department_blocked(app, faculty_ece_client):
    monday = next_weekday()
    req_id, _ = create_request(
        app,
        student_email="student1@university.edu",
        leave_type_name="Casual Leave",
        start=monday,
        end=monday + timedelta(days=1),
    )
    resp = faculty_ece_client.get(f"/review/requests/{req_id}")
    assert resp.status_code == 404

    resp = faculty_ece_client.post(
        f"/review/requests/{req_id}/decision",
        data={"action": "approve", "remarks": "Approved by mistake."},
        follow_redirects=True,
    )
    assert resp.status_code == 404
    row = db_fetch(app, "SELECT status FROM leave_requests WHERE id = ?", (req_id,))[0]
    assert row["status"] == "Pending"


def test_faculty_of_same_department_can_view(app, faculty_client):
    monday = next_weekday()
    req_id, _ = create_request(
        app,
        student_email="student1@university.edu",
        leave_type_name="Casual Leave",
        start=monday,
        end=monday + timedelta(days=1),
    )
    resp = faculty_client.get(f"/review/requests/{req_id}")
    assert resp.status_code == 200


def test_student_blocked_from_review_area(student_client):
    assert student_client.get("/review/").status_code == 403
    assert student_client.get("/admin/audit").status_code == 403


def test_admin_sees_everything(app, admin_client):
    monday = next_weekday()
    req_id, _ = create_request(
        app,
        student_email="student1@university.edu",
        leave_type_name="Casual Leave",
        start=monday,
        end=monday + timedelta(days=1),
    )
    assert admin_client.get(f"/review/requests/{req_id}").status_code == 200
    assert admin_client.get("/admin/users").status_code == 200
    assert admin_client.get("/admin/reports").status_code == 200


def test_notifications_are_private(app, student_client, student2_client):
    rows = db_fetch(
        app,
        "SELECT * FROM notifications WHERE recipient_id = (SELECT id FROM users WHERE email = ?)",
        ("student2@university.edu",),
    )
    if not rows:
        return
    notif_id = rows[0]["id"]
    student_client.post(f"/notifications/{notif_id}/read", follow_redirects=True)
    after = db_fetch(app, "SELECT is_read FROM notifications WHERE id = ?", (notif_id,))[0]
    assert after["is_read"] == 0


def test_attachment_download_is_scoped(app, student_client, faculty_client):
    monday = next_weekday()
    req_id, _ = create_request(
        app,
        student_email="student2@university.edu",
        leave_type_name="Casual Leave",
        start=monday,
        end=monday + timedelta(days=1),
    )
    assert student_client.get(f"/student/attachments/{req_id}").status_code == 404
    assert faculty_client.get(f"/review/attachments/{req_id}").status_code == 404
