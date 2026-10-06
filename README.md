# Smart Student Leave Management and Approval System

## Abstract

The Smart Student Leave Management and Approval System is a web-based application designed to automate and simplify the process of applying for, managing, and approving student leave requests.

The system provides a centralized platform where students can submit leave applications by entering details such as leave type, reason, start date, end date, and other required information. Once a leave request is submitted, the respective faculty member or in-charge is notified and can review, approve, reject, or request additional information regarding the application. Students can also track the real-time status of their leave requests and view their leave history.

The system supports role-based access for Students, Faculty/In-charges, Heads of Departments, and Administrators, enabling a structured approval workflow. Additional features such as email notifications, leave balance tracking, dashboard analytics, and attendance integration can improve the overall functionality and efficiency of the system.

The proposed application aims to reduce manual paperwork, improve communication between students and faculty, provide transparency in the leave approval process, and maintain centralized digital records. The system can be implemented using modern web technologies with a database for secure storage and management of student and leave-related information.

## Project Goal

Build a secure, responsive, and easy-to-use leave management portal for Malla Reddy University. The application must replace paper-based leave requests with a traceable digital workflow from submission through final decision.

## User Roles

- **Student:** Create leave requests, attach supporting documents, view request status, respond to clarification requests, see leave history, and view available leave balance.
- **Faculty/In-charge:** Review assigned student requests, ask for more information, approve or reject requests, and add remarks.
- **Head of Department:** Review escalated or department-level requests and give the final departmental decision where required.
- **Administrator:** Manage users, departments, branches, leave types, academic settings, permissions, and system-wide reports.

## Required Workflow

1. A student signs in and submits a leave request with student details, leave type, start date, end date, reason, contact information, and optional supporting documents.
2. The system validates the dates, required fields, leave balance, overlapping requests, and any department rules.
3. The request is saved with a unique request number and the status `Pending`.
4. The assigned faculty member or in-charge receives an in-app and email notification.
5. The reviewer can approve, reject, or request additional information. Every decision must include the reviewer, timestamp, and optional remarks.
6. Requests that require another level of approval are forwarded to the Head of Department.
7. The student can see the current status and complete history at any time.
8. The student receives a notification whenever the status changes. Approved leave updates the leave balance and can be sent to the attendance system.

Suggested statuses are `Draft`, `Pending`, `More Information Required`, `Approved`, `Rejected`, `Cancelled`, and `Completed`.

## Main Features

### Student portal

- Secure student registration and login.
- Dashboard showing pending, approved, rejected, and completed requests.
- Leave application form with leave type, start date, end date, reason, emergency contact, and attachments.
- Leave balance and previous leave history.
- Search and filter requests by date, type, and status.
- Request cancellation before approval, subject to university rules.
- Status timeline showing every workflow action and remark.

### Faculty and HOD portal

- Role-based dashboard for assigned requests.
- Filters for department, branch, date range, leave type, and status.
- Request detail view with student information and attachments.
- Approve, reject, or request additional information.
- Mandatory rejection reason and optional approval remarks.
- Notification queue and complete audit history.

### Administrator portal

- Manage students, faculty, HODs, departments, branches, and roles.
- Configure leave types, maximum duration, required documents, holidays, and approval rules.
- View reports for leave usage, approval time, department activity, and outstanding requests.
- Export filtered records to CSV or PDF.
- Maintain audit logs for important administrative actions.

### Notifications and integration

- Email notifications for submission, approval, rejection, and clarification requests.
- In-app notifications with unread/read state.
- Optional SMS or messaging integration.
- Optional attendance-system integration after approval.

## Data Model

The database should include, at minimum:

- `users`: id, name, roll number or employee id, email, password hash, role, department, branch, and active state.
- `departments` and `branches`: names, codes, and active state.
- `leave_types`: name, description, maximum days, balance rules, and required documents.
- `leave_requests`: request number, student, leave type, start date, end date, reason, contact details, attachment path, status, created time, and updated time.
- `approvals`: request, reviewer, action, remarks, action time, and level.
- `leave_balances`: student, leave type, academic year, allocated days, used days, and remaining days.
- `notifications`: recipient, request, message, channel, read state, and sent time.
- `audit_logs`: user, action, affected record, metadata, and timestamp.

Use foreign keys, indexes for common filters, UTC timestamps, and parameterized queries. Do not store plain-text passwords.

## Security and Quality Requirements

- Use secure password hashing and session management.
- Store secrets such as `SECRET_KEY` and mail credentials in environment variables.
- Enforce authorization on every protected route; do not rely only on hidden buttons.
- Add CSRF protection to state-changing forms.
- Validate and sanitize all user input on the server.
- Restrict attachment file types and sizes, and store uploads safely.
- Prevent students from viewing another student's requests.
- Keep an immutable approval and audit history.
- Use clear error messages, empty states, loading states, and responsive layouts for desktop and mobile.
- Add automated tests for authentication, request validation, permissions, status transitions, notifications, and leave-balance calculations.

## Current Prototype

The current Flask prototype already provides:

- A basic student leave form for name, email, branch, leave date, and reason.
- SQLite storage for leave requests.
- An admin login and request list.
- Admin approval or rejection.
- Email notification after a status update when mail settings are configured.
- Status lookup by email.

The prototype still needs the role-based accounts, multi-step approval workflow, leave types and balances, date-range validation, attachments, secure configuration, audit trail, dashboards, stronger authorization, CSRF protection, and automated tests described above.

## Suggested Implementation Plan

1. Refactor the database into users, roles, departments, leave types, requests, approvals, balances, notifications, and audit logs.
2. Add secure authentication and role-based authorization for Student, Faculty/In-charge, HOD, and Administrator.
3. Replace the single-date form with a validated leave request form and request-number workflow.
4. Implement configurable approval levels and status transitions with remarks and timestamps.
5. Add student, reviewer, and administrator dashboards with filtering and pagination.
6. Add email and in-app notifications with a development-friendly fallback when SMTP is unavailable.
7. Add leave balance calculation, holiday and overlap validation, and optional attendance integration.
8. Improve the UI for mobile and desktop, including accessible forms, clear status badges, and useful empty/error states.
9. Add tests, seed data, deployment configuration, and documentation for local setup and production deployment.

## Local Development Setup

Follow these instructions to run the application locally on your machine after cloning the repository.

### 1. Prerequisites

- **Python**: Version 3.10 or higher installed.
- **Git**: Installed on your system.

---

### 2. Clone the Repository

```bash
git clone https://github.com/your-username/leave-management.git
cd leave-management
```

---

### 3. Create & Activate a Virtual Environment

#### On Windows (PowerShell):
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```
*(If you encounter a script execution policy error on PowerShell, run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` first)*

#### On Windows (Command Prompt):
```cmd
python -m venv .venv
.\.venv\Scripts\activate.bat
```

#### On macOS / Linux (Bash / Zsh):
```bash
python3 -m venv .venv
source .venv/bin/activate
```

---

### 4. Install Dependencies

```bash
pip install -r requirements.txt
```

---

### 5. Initialize & Seed the Database

The database is powered by SQLite (`leaves.db`). Run the seed script to create all required tables, departments, leave types, default holidays, and pre-configured demo user accounts:

```bash
python seed.py
```

---

### 6. Environment Configuration (Optional)

Create a `.env` file in the root directory if you wish to configure custom settings or enable live email notifications (by default, development fallbacks are used):

```env
# Application Secret Key
SECRET_KEY=your-super-secret-key-change-in-production

# Database path (defaults to leaves.db)
DATABASE_PATH=leaves.db

# Optional SMTP Email configuration
MAIL_SERVER=smtp.gmail.com
MAIL_PORT=587
MAIL_USE_TLS=True
MAIL_USERNAME=your-email@example.com
MAIL_PASSWORD=your-email-app-password
MAIL_DEFAULT_SENDER=noreply@mallareddyuniversity.ac.in
```

---

### 7. Run the Application

Start the local Flask development server:

```bash
python app.py
```

The application will be live at **`http://127.0.0.1:5000/`**.

---

### 8. Demo User Accounts

Use any of the following pre-seeded accounts to explore the role-based portals:

| Role | Name | Email | Password | Details |
| :--- | :--- | :--- | :--- | :--- |
| **System Admin** | System Admin | `admin@university.edu` | `Admin@1234` | Full administration & settings |
| **Faculty / In-charge** | Prof. Anitha Rao | `faculty.cse@university.edu` | `Faculty@123` | CSE Department reviewer |
| **Faculty / In-charge** | Prof. Ravi Kumar | `faculty.ece@university.edu` | `Faculty@123` | ECE Department reviewer |
| **Head of Department** | Dr. Suresh Babu | `hod.cse@university.edu` | `Hod@12345` | CSE Department HOD |
| **Head of Department** | Dr. Meena Devi | `hod.ece@university.edu` | `Hod@12345` | ECE Department HOD |
| **Student** | A. Kumar | `student1@university.edu` | `Student@123` | CSE student (Roll: 22B81A0501) |
| **Student** | B. Shruti | `student2@university.edu` | `Student@123` | CSE student (Roll: 22B81A0502) |
| **Student** | C. Rakesh | `student3@university.edu` | `Student@123` | ECE student (Roll: 22B81A0401) |

> **Note**: You can also register a brand new student account directly from the **Register** page. New students automatically receive a default leave balance of 5 days for each leave category.

---

### 9. Running Automated Tests

Run the complete test suite (60+ unit, validation, auth, and workflow tests):

```bash
pytest
```

---

## Existing Deployment

The original prototype was deployed at https://leave-management-kclb.onrender.com/. Production deployment should use a persistent database, environment variables, HTTPS, secure authentication, and proper backup and monitoring.

