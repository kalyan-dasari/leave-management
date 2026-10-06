import sqlite3

conn = sqlite3.connect("leaves.db")
conn.row_factory = sqlite3.Row
cur = conn.cursor()

students = [r["id"] for r in cur.execute("SELECT id FROM users WHERE role = 'student'").fetchall()]
types = [r["id"] for r in cur.execute("SELECT id FROM leave_types WHERE active = 1").fetchall()]
year = "2026-27"

count = 0
for s in students:
    for t in types:
        row = cur.execute(
            "SELECT id, remaining FROM leave_balances WHERE student_id = ? AND leave_type_id = ? AND academic_year = ?",
            (s, t, year),
        ).fetchone()
        if not row:
            cur.execute(
                "INSERT INTO leave_balances (student_id, leave_type_id, academic_year, allocated, used, remaining) VALUES (?, ?, ?, 5, 0, 5)",
                (s, t, year),
            )
            count += 1
        elif row["remaining"] == 0:
            cur.execute("UPDATE leave_balances SET allocated = 5, remaining = 5 WHERE id = ?", (row["id"],))

conn.commit()
print(f"Updated balances! Added {count} new balance records with 5 days each.")
