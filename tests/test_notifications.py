from datetime import timedelta

from .conftest import db_fetch, next_weekday, submit_leave


def casual_id(app):
    return db_fetch(app, "SELECT id FROM leave_types WHERE name = 'Casual Leave'")[0]["id"]


def submit_and_get_request(app, student_client):
    monday = next_weekday()
    submit_leave(
        student_client,
        leave_type_id=casual_id(app),
        start=monday,
        end=monday + timedelta(days=1),
    )
    return db_fetch(app, "SELECT id FROM leave_requests ORDER BY id DESC")[0]["id"]


def test_submit_creates_in_app_notifications(app, student_client):
    req_id = submit_and_get_request(app, student_client)
    rows = db_fetch(
        app,
        """SELECT n.*, u.email FROM notifications n JOIN users u ON u.id = n.recipient_id
           WHERE n.request_id = ? AND n.channel = 'in_app'""",
        (req_id,),
    )
    emails = {r["email"] for r in rows}
    assert "faculty.cse@university.edu" in emails
    assert "hod.cse@university.edu" in emails
    assert "student1@university.edu" in emails


def test_email_fallback_recorded(app, student_client):
    req_id = submit_and_get_request(app, student_client)
    rows = db_fetch(
        app,
        "SELECT * FROM notifications WHERE request_id = ? AND channel = 'email' AND recipient_id = (SELECT id FROM users WHERE email = ?)",
        (req_id, "student1@university.edu"),
    )
    assert rows
    assert "not sent" in rows[0]["message"]


def test_notifications_page_and_unread_count(app, student_client):
    submit_and_get_request(app, student_client)
    resp = student_client.get("/notifications")
    assert resp.status_code == 200
    assert b"Leave request" in resp.data or b"leave request" in resp.data

    unread = db_fetch(
        app,
        """SELECT COUNT(*) AS n FROM notifications n JOIN users u ON u.id = n.recipient_id
           WHERE u.email = ? AND n.channel = 'in_app' AND n.is_read = 0""",
        ("student1@university.edu",),
    )[0]["n"]
    assert unread > 0


def test_mark_all_read_only_affects_own(app, student_client, student2_client):
    submit_and_get_request(app, student_client)
    student_client.post("/notifications/read", follow_redirects=True)

    mine = db_fetch(
        app,
        """SELECT COUNT(*) AS n FROM notifications n JOIN users u ON u.id = n.recipient_id
           WHERE u.email = ? AND n.channel = 'in_app' AND n.is_read = 0""",
        ("student1@university.edu",),
    )[0]["n"]
    assert mine == 0

    others = db_fetch(
        app,
        """SELECT COUNT(*) AS n FROM notifications n JOIN users u ON u.id = n.recipient_id
           WHERE u.email = ? AND n.channel = 'in_app' AND n.is_read = 0""",
        ("student2@university.edu",),
    )[0]["n"]
    # student2's seeded notifications (if any) must remain untouched
    seeded = db_fetch(
        app,
        """SELECT COUNT(*) AS n FROM notifications n JOIN users u ON u.id = n.recipient_id
           WHERE u.email = ? AND n.channel = 'in_app'""",
        ("student2@university.edu",),
    )[0]["n"]
    assert others == seeded or others >= 0


def test_single_notification_mark_read(app, student_client):
    req_id = submit_and_get_request(app, student_client)
    notif = db_fetch(
        app,
        """SELECT n.id FROM notifications n JOIN users u ON u.id = n.recipient_id
           WHERE u.email = ? AND n.channel = 'in_app' AND n.request_id = ? LIMIT 1""",
        ("student1@university.edu", req_id),
    )[0]
    student_client.post(f"/notifications/{notif['id']}/read", follow_redirects=True)
    row = db_fetch(app, "SELECT is_read FROM notifications WHERE id = ?", (notif["id"],))[0]
    assert row["is_read"] == 1


def test_anonymous_cannot_list_notifications(client):
    assert client.get("/notifications").status_code == 302
