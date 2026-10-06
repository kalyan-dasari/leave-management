from datetime import timedelta

from .conftest import create_request, db_fetch, decide, next_weekday, submit_leave


def approvals(app, req_id):
    return db_fetch(app, "SELECT * FROM approvals WHERE request_id = ? ORDER BY id", (req_id,))


def test_submit_notifies_reviewers(app, student_client, faculty_client):
    monday = next_weekday()
    submit_leave(
        student_client,
        leave_type_id=db_fetch(app, "SELECT id FROM leave_types WHERE name = 'Casual Leave'")[0]["id"],
        start=monday,
        end=monday + timedelta(days=1),
    )
    faculty_notifs = db_fetch(
        app,
        """SELECT n.* FROM notifications n JOIN users u ON u.id = n.recipient_id
           WHERE u.email = ? AND n.channel = 'in_app' AND n.request_id IS NOT NULL""",
        ("faculty.cse@university.edu",),
    )
    assert faculty_notifs
    student_notifs = db_fetch(
        app,
        """SELECT n.* FROM notifications n JOIN users u ON u.id = n.recipient_id
           WHERE u.email = ? AND n.channel = 'in_app' AND n.request_id IS NOT NULL""",
        ("student1@university.edu",),
    )
    assert any("submitted" in n["message"] for n in student_notifs)


def test_faculty_approval_is_final_for_casual(app, faculty_client):
    monday = next_weekday()
    req_id, _ = create_request(
        app,
        student_email="student1@university.edu",
        leave_type_name="Casual Leave",
        start=monday,
        end=monday + timedelta(days=1),
    )
    resp = faculty_client.post(
        f"/review/requests/{req_id}/decision",
        data={"action": "approve", "remarks": "Enjoy."},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    row = db_fetch(app, "SELECT * FROM leave_requests WHERE id = ?", (req_id,))[0]
    assert row["status"] == "Approved"
    assert row["current_level"] == 1
    assert approvals(app, req_id)[-1]["action"] == "Approved"


def test_medical_escalates_to_hod(app, faculty_client, hod_client):
    monday = next_weekday()
    req_id, _ = create_request(
        app,
        student_email="student1@university.edu",
        leave_type_name="Medical Leave",
        start=monday,
        end=monday + timedelta(days=2),
    )
    faculty_client.post(
        f"/review/requests/{req_id}/decision",
        data={"action": "approve", "remarks": "Get well soon."},
        follow_redirects=True,
    )
    row = db_fetch(app, "SELECT * FROM leave_requests WHERE id = ?", (req_id,))[0]
    assert row["status"] == "Pending"
    assert row["current_level"] == 2
    assert approvals(app, req_id)[-1]["action"] == "Recommended"

    hod_notifs = db_fetch(
        app,
        """SELECT n.* FROM notifications n JOIN users u ON u.id = n.recipient_id
           WHERE u.role = 'hod' AND u.email = ? AND n.channel = 'in_app'""",
        ("hod.cse@university.edu",),
    )
    assert any("HOD" in n["message"] or "level 2" in n["message"] for n in hod_notifs)

    hod_client.post(
        f"/review/requests/{req_id}/decision",
        data={"action": "approve", "remarks": "Final approval."},
        follow_redirects=True,
    )
    row = db_fetch(app, "SELECT * FROM leave_requests WHERE id = ?", (req_id,))[0]
    assert row["status"] == "Approved"
    assert approvals(app, req_id)[-1]["level"] == 2


def test_faculty_cannot_decide_level_2(app, faculty_client):
    monday = next_weekday()
    req_id, _ = create_request(
        app,
        student_email="student1@university.edu",
        leave_type_name="Medical Leave",
        start=monday,
        end=monday + timedelta(days=2),
    )
    faculty_client.post(
        f"/review/requests/{req_id}/decision",
        data={"action": "approve", "remarks": "Recommend."},
        follow_redirects=True,
    )
    faculty_client.post(
        f"/review/requests/{req_id}/decision",
        data={"action": "approve", "remarks": "Trying to bypass HOD."},
        follow_redirects=True,
    )
    row = db_fetch(app, "SELECT * FROM leave_requests WHERE id = ?", (req_id,))[0]
    assert row["status"] == "Pending"
    assert row["current_level"] == 2


def test_rejection_requires_reason(app, faculty_client):
    monday = next_weekday()
    req_id, _ = create_request(
        app,
        student_email="student1@university.edu",
        leave_type_name="Casual Leave",
        start=monday,
        end=monday + timedelta(days=1),
    )
    resp = faculty_client.post(
        f"/review/requests/{req_id}/decision",
        data={"action": "reject", "remarks": ""},
        follow_redirects=True,
    )
    assert b"rejection reason is required" in resp.data
    row = db_fetch(app, "SELECT status FROM leave_requests WHERE id = ?", (req_id,))[0]
    assert row["status"] == "Pending"
    assert approvals(app, req_id) == []


def test_rejection_with_reason(app, faculty_client, student_client):
    monday = next_weekday()
    req_id, _ = create_request(
        app,
        student_email="student1@university.edu",
        leave_type_name="Casual Leave",
        start=monday,
        end=monday + timedelta(days=1),
    )
    faculty_client.post(
        f"/review/requests/{req_id}/decision",
        data={"action": "reject", "remarks": "Clashing with lab exams."},
        follow_redirects=True,
    )
    row = db_fetch(app, "SELECT status FROM leave_requests WHERE id = ?", (req_id,))[0]
    assert row["status"] == "Rejected"
    student_notifs = db_fetch(
        app,
        """SELECT n.* FROM notifications n JOIN users u ON u.id = n.recipient_id
           WHERE u.email = ? AND n.request_id = ?""",
        ("student1@university.edu", req_id),
    )
    assert any("rejected" in n["message"] for n in student_notifs)


def test_request_info_round_trip(app, faculty_client, student_client):
    monday = next_weekday()
    req_id, _ = create_request(
        app,
        student_email="student1@university.edu",
        leave_type_name="Casual Leave",
        start=monday,
        end=monday + timedelta(days=1),
    )
    faculty_client.post(
        f"/review/requests/{req_id}/decision",
        data={"action": "request_info", "remarks": "Please attach the invitation."},
        follow_redirects=True,
    )
    row = db_fetch(app, "SELECT status FROM leave_requests WHERE id = ?", (req_id,))[0]
    assert row["status"] == "More Information Required"

    resp = student_client.post(
        f"/student/requests/{req_id}/respond",
        data={"response": "Invitation will be shared by tomorrow."},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    row = db_fetch(app, "SELECT status FROM leave_requests WHERE id = ?", (req_id,))[0]
    assert row["status"] == "Pending"
    acts = [a["action"] for a in approvals(app, req_id)]
    assert acts == ["Requested Information", "Response"]


def test_short_response_rejected(app, student_client):
    monday = next_weekday()
    req_id, _ = create_request(
        app,
        student_email="student1@university.edu",
        leave_type_name="Casual Leave",
        start=monday,
        end=monday + timedelta(days=1),
    )
    from leave_management.db import execute

    with app.app_context():
        execute(
            "UPDATE leave_requests SET status = 'More Information Required' WHERE id = ?",
            (req_id,),
        )
    student_client.post(
        f"/student/requests/{req_id}/respond",
        data={"response": "ok"},
        follow_redirects=True,
    )
    row = db_fetch(app, "SELECT status FROM leave_requests WHERE id = ?", (req_id,))[0]
    assert row["status"] == "More Information Required"


def test_student_can_cancel_pending(app, student_client):
    monday = next_weekday()
    submit_leave(
        student_client,
        leave_type_id=db_fetch(app, "SELECT id FROM leave_types WHERE name = 'Casual Leave'")[0]["id"],
        start=monday,
        end=monday + timedelta(days=1),
    )
    req_id = db_fetch(app, "SELECT id FROM leave_requests ORDER BY id DESC")[0]["id"]
    student_client.post(f"/student/requests/{req_id}/cancel", follow_redirects=True)
    row = db_fetch(app, "SELECT status FROM leave_requests WHERE id = ?", (req_id,))[0]
    assert row["status"] == "Cancelled"


def test_cannot_cancel_approved(app, faculty_client, student_client):
    monday = next_weekday()
    req_id, _ = create_request(
        app,
        student_email="student1@university.edu",
        leave_type_name="Casual Leave",
        start=monday,
        end=monday + timedelta(days=1),
    )
    faculty_client.post(
        f"/review/requests/{req_id}/decision",
        data={"action": "approve", "remarks": "ok"},
        follow_redirects=True,
    )
    student_client.post(f"/student/requests/{req_id}/cancel", follow_redirects=True)
    row = db_fetch(app, "SELECT status FROM leave_requests WHERE id = ?", (req_id,))[0]
    assert row["status"] == "Approved"


def test_decided_request_cannot_be_decided_again(app, faculty_client):
    monday = next_weekday()
    req_id, _ = create_request(
        app,
        student_email="student1@university.edu",
        leave_type_name="Casual Leave",
        start=monday,
        end=monday + timedelta(days=1),
    )
    faculty_client.post(
        f"/review/requests/{req_id}/decision",
        data={"action": "approve", "remarks": "ok"},
        follow_redirects=True,
    )
    faculty_client.post(
        f"/review/requests/{req_id}/decision",
        data={"action": "reject", "remarks": "changed my mind"},
        follow_redirects=True,
    )
    row = db_fetch(app, "SELECT status FROM leave_requests WHERE id = ?", (req_id,))[0]
    assert row["status"] == "Approved"
    assert len(approvals(app, req_id)) == 1


def test_completed_transition(app, faculty_client, student_client):
    from leave_management.db import execute

    monday = next_weekday()
    req_id, _ = create_request(
        app,
        student_email="student1@university.edu",
        leave_type_name="Casual Leave",
        start=monday,
        end=monday + timedelta(days=1),
    )
    faculty_client.post(
        f"/review/requests/{req_id}/decision",
        data={"action": "approve", "remarks": "ok"},
        follow_redirects=True,
    )
    with app.app_context():
        execute(
            "UPDATE leave_requests SET end_date = date('now', '-2 days') WHERE id = ?",
            (req_id,),
        )
    student_client.get("/student/")
    row = db_fetch(app, "SELECT status FROM leave_requests WHERE id = ?", (req_id,))[0]
    assert row["status"] == "Completed"
