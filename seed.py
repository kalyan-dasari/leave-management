"""Seed the database with demo data.

Run with:  python seed.py
"""

from datetime import date, timedelta

from werkzeug.security import generate_password_hash

from leave_management import create_app
from leave_management.db import utcnow
from leave_management.validators import academic_year

PASSWORDS = {
    "admin": "Admin@1234",
    "faculty": "Faculty@123",
    "hod": "Hod@12345",
    "student": "Student@123",
}


def seed_demo(db=None):
    """Create demo departments, users, leave types, balances and requests."""
    if db is None:
        from leave_management.db import get_db

        db = get_db()

    def run(sql, args=()):
        cur = db.execute(sql, args)
        db.commit()
        return cur

    def find(sql, args=()):
        cur = db.execute(sql, args)
        row = cur.fetchone()
        cur.close()
        return row

    # departments & branches
    def dept(name, code):
        row = find("SELECT id FROM departments WHERE code = ?", (code,))
        if row:
            return row[0]
        return run("INSERT INTO departments (name, code, active) VALUES (?, ?, 1)", (name, code)).lastrowid

    def branch(name, code, department_id):
        row = find("SELECT id FROM branches WHERE code = ?", (code,))
        if row:
            return row[0]
        return run(
            "INSERT INTO branches (department_id, name, code, active) VALUES (?, ?, ?, 1)",
            (department_id, name, code),
        ).lastrowid

    cse = dept("Computer Science & Engineering", "CSE")
    ece = dept("Electronics & Communication", "ECE")
    cse_a = branch("CSE - A", "CSEA", cse)
    cse_b = branch("CSE - B", "CSEB", cse)
    ece_a = branch("ECE - A", "ECEA", ece)

    def user(name, email, role, password, department_id, branch_id=None, roll_no=None):
        row = find("SELECT id FROM users WHERE email = ?", (email,))
        if row:
            return row[0]
        return run(
            """INSERT INTO users (name, roll_no, email, password_hash, role, department_id, branch_id, active, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)""",
            (name, roll_no, email, generate_password_hash(password), role, department_id, branch_id, utcnow()),
        ).lastrowid

    admin_id = user("System Admin", "admin@university.edu", "admin", PASSWORDS["admin"], None, None, "EMP-000")
    faculty_id = user("Prof. Anitha Rao", "faculty.cse@university.edu", "faculty", PASSWORDS["faculty"], cse, None, "EMP-101")
    faculty2_id = user("Prof. Ravi Kumar", "faculty.ece@university.edu", "faculty", PASSWORDS["faculty"], ece, None, "EMP-102")
    hod_id = user("Dr. Suresh Babu", "hod.cse@university.edu", "hod", PASSWORDS["hod"], cse, None, "EMP-201")
    hod2_id = user("Dr. Meena Devi", "hod.ece@university.edu", "hod", PASSWORDS["hod"], ece, None, "EMP-202")

    students = [
        ("A. Kumar", "student1@university.edu", "22B81A0501", cse, cse_a),
        ("B. Shruti", "student2@university.edu", "22B81A0502", cse, cse_b),
        ("C. Rakesh", "student3@university.edu", "22B81A0401", ece, ece_a),
    ]
    student_ids = [user(n, e, "student", PASSWORDS["student"], d, b, r) for n, e, r, d, b in students]

    # leave types
    def leave_type(name, description, max_days, requires_document=0, hod_required=0):
        row = find("SELECT id FROM leave_types WHERE name = ?", (name,))
        if row:
            return row[0]
        return run(
            """INSERT INTO leave_types (name, description, max_days, requires_document, hod_required, active)
               VALUES (?, ?, ?, ?, ?, 1)""",
            (name, description, max_days, requires_document, hod_required),
        ).lastrowid

    casual = leave_type("Casual Leave", "Short personal leave", 5)
    medical = leave_type("Medical Leave", "Illness or medical treatment", 15, requires_document=1, hod_required=1)
    academic = leave_type("Academic Leave", "Exams, interviews, conferences", 10, requires_document=1)

    # balances for the current academic year
    year = academic_year(date.today())
    for sid in student_ids:
        for lid, allocated in ((casual, 12), (medical, 15), (academic, 8)):
            row = find(
                "SELECT id FROM leave_balances WHERE student_id = ? AND leave_type_id = ? AND academic_year = ?",
                (sid, lid, year),
            )
            if not row:
                run(
                    """INSERT INTO leave_balances (student_id, leave_type_id, academic_year, allocated, used, remaining)
                       VALUES (?, ?, ?, ?, 0, ?)""",
                    (sid, lid, year, allocated, allocated),
                )

    # holidays
    today = date.today()
    for name, day in (
        ("Foundation Day", today + timedelta(days=20)),
        ("Winter Break", today + timedelta(days=60)),
    ):
        if not find("SELECT id FROM holidays WHERE date = ?", (day.isoformat(),)):
            run("INSERT INTO holidays (name, date) VALUES (?, ?)", (name, day.isoformat()))

    # a couple of demo requests
    if not find("SELECT id FROM leave_requests LIMIT 1"):
        from leave_management.workflow import apply_decision, create_leave_request

        create_leave_request(
            student=dict(find("SELECT * FROM users WHERE id = ?", (student_ids[0],))),
            leave_type=dict(find("SELECT * FROM leave_types WHERE id = ?", (casual,))),
            data={
                "start_date": (today + timedelta(days=7)).isoformat(),
                "end_date": (today + timedelta(days=8)).isoformat(),
                "days": 2,
                "reason": "Family function out of town.",
                "contact": "9848012345",
                "academic_year": year,
                "remaining_after": 10,
            },
        )
        req_id, _ = create_leave_request(
            student=dict(find("SELECT * FROM users WHERE id = ?", (student_ids[1],))),
            leave_type=dict(find("SELECT * FROM leave_types WHERE id = ?", (medical,))),
            data={
                "start_date": (today + timedelta(days=3)).isoformat(),
                "end_date": (today + timedelta(days=5)).isoformat(),
                "days": 3,
                "reason": "Fever and doctor consultation.",
                "contact": "9848098765",
                "academic_year": year,
                "remaining_after": 12,
            },
        )
        apply_decision(
            request_row=dict(find("SELECT * FROM leave_requests WHERE id = ?", (req_id,))),
            reviewer=dict(find("SELECT * FROM users WHERE id = ?", (faculty_id,))),
            action="approve",
            remarks="Wishing a speedy recovery.",
        )

    return {
        "admin": ("admin@university.edu", PASSWORDS["admin"]),
        "faculty": ("faculty.cse@university.edu", PASSWORDS["faculty"]),
        "faculty_ece": ("faculty.ece@university.edu", PASSWORDS["faculty"]),
        "hod": ("hod.cse@university.edu", PASSWORDS["hod"]),
        "student": ("student1@university.edu", PASSWORDS["student"]),
        "student2": ("student2@university.edu", PASSWORDS["student"]),
        "ids": {"admin": admin_id, "faculty": faculty_id, "faculty_ece": faculty2_id, "hod": hod_id, "hod_ece": hod2_id},
    }


def main():
    app = create_app()
    with app.app_context():
        from leave_management.db import get_db

        get_db()
        accounts = seed_demo()
    print("Seed complete.")
    for label, value in accounts.items():
        if label == "ids":
            continue
        email, password = value
        print(f"  {label:12s} {email:32s} {password}")


if __name__ == "__main__":
    main()
