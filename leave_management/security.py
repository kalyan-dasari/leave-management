from functools import wraps

from flask import abort, flash, g, redirect, request, session, url_for

from .db import query


def load_user():
    user_id = session.get("user_id")
    g.user = None
    if user_id:
        g.user = query(
            """SELECT u.*, d.name AS department_name, b.name AS branch_name
               FROM users u
               LEFT JOIN departments d ON d.id = u.department_id
               LEFT JOIN branches b ON b.id = u.branch_id
               WHERE u.id = ? AND u.active = 1""",
            (user_id,),
            one=True,
        )
        if g.user is None:
            session.pop("user_id", None)


def _safe_next(target: str) -> str:
    if target and target.startswith("/") and not target.startswith("//"):
        return target
    return url_for("main.dashboard")


def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if g.user is None:
            flash("Please sign in to continue.", "warning")
            return redirect(url_for("auth.login", next=request.path))
        return view(*args, **kwargs)

    return wrapper


def roles_required(*roles):
    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            if g.user is None:
                flash("Please sign in to continue.", "warning")
                return redirect(url_for("auth.login", next=request.path))
            if g.user["role"] not in roles:
                abort(403)
            return view(*args, **kwargs)

        return wrapper

    return decorator


def redirect_by_role(role: str) -> str:
    if role == "student":
        return url_for("student.dashboard")
    if role in ("faculty", "hod"):
        return url_for("review.dashboard")
    return url_for("admin.dashboard")
