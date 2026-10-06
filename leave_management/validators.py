from datetime import date, datetime, timedelta

DATE_FMT = "%Y-%m-%d"
MIN_REASON_LENGTH = 10


def page_number(raw, default=1) -> int:
    try:
        return max(int(raw or default), 1)
    except (TypeError, ValueError):
        return default


def parse_date(value) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(str(value), DATE_FMT).date()
    except ValueError:
        return None


def academic_year(day: date) -> str:
    if day.month >= 7:
        return f"{day.year}-{str(day.year + 1)[2:]}"
    return f"{day.year - 1}-{str(day.year)[2:]}"


def working_days(start: date, end: date, holidays=()) -> int:
    """Count weekdays between start and end, excluding configured holidays."""
    total = 0
    current = start
    while current <= end:
        if current.weekday() < 5 and current.isoformat() not in holidays:
            total += 1
        current += timedelta(days=1)
    return total


def load_holiday_dates(db_query) -> set[str]:
    return {row["date"] for row in db_query("SELECT date FROM holidays")}


def validate_leave(*, student_id, leave_type, start_raw, end_raw, reason, contact, attachment_file, has_attachment, query, today=None):
    """Validate a leave application. Returns (data, errors).

    ``data`` holds parsed values when errors is empty.
    """
    errors = []
    today = today or date.today()

    if not leave_type:
        errors.append("Please select a leave type.")
    if not contact or len(contact.strip()) < 5:
        errors.append("Emergency contact information is required.")

    start = parse_date(start_raw)
    end = parse_date(end_raw)
    if start is None:
        errors.append("Start date is required and must be a valid date.")
    if end is None:
        errors.append("End date is required and must be a valid date.")

    reason = (reason or "").strip()
    if len(reason) < MIN_REASON_LENGTH:
        errors.append(f"Reason must be at least {MIN_REASON_LENGTH} characters.")

    if start and end:
        if end < start:
            errors.append("End date cannot be before the start date.")
        elif start < today:
            errors.append("Leave cannot start in the past.")

    if errors:
        return None, errors

    holidays = load_holiday_dates(query)
    days = working_days(start, end, holidays)
    if days < 1:
        errors.append("The selected range contains no working days (weekends or holidays only).")

    if leave_type["max_days"] and days > leave_type["max_days"]:
        errors.append(f"{leave_type['name']} leave is limited to {leave_type['max_days']} day(s); you selected {days}.")

    if leave_type["requires_document"] and not has_attachment:
        errors.append(f"{leave_type['name']} leave requires a supporting document (PDF, JPG or PNG, max 5 MB).")

    overlap = query(
        """SELECT request_no FROM leave_requests
           WHERE student_id = ?
             AND status IN ('Pending', 'More Information Required', 'Approved', 'Completed')
             AND NOT (end_date < ? OR start_date > ?)""",
        (student_id, start.isoformat(), end.isoformat()),
    )
    if overlap:
        errors.append(f"Overlapping request {overlap[0]['request_no']} already exists for these dates.")

    year = academic_year(start)
    balance = query(
        "SELECT * FROM leave_balances WHERE student_id = ? AND leave_type_id = ? AND academic_year = ?",
        (student_id, leave_type["id"], year),
        one=True,
    )
    remaining = balance["remaining"] if balance else 0
    if remaining < days:
        errors.append(
            f"Insufficient {leave_type['name']} leave balance: {remaining} day(s) left, {days} requested."
        )

    if errors:
        return None, errors

    return {
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "days": days,
        "reason": reason,
        "contact": contact.strip(),
        "academic_year": year,
        "remaining_after": remaining - days,
    }, []
