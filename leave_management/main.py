from flask import Blueprint, flash, g, redirect, render_template, request, url_for

from .db import execute, query
from .security import login_required, redirect_by_role

bp = Blueprint("main", __name__)


@bp.route("/")
def dashboard():
    if g.user is None:
        return render_template("index.html")
    return redirect(redirect_by_role(g.user["role"]))


@bp.route("/notifications")
@login_required
def notifications():
    rows = query(
        """SELECT n.*, r.request_no FROM notifications n
           LEFT JOIN leave_requests r ON r.id = n.request_id
           WHERE n.recipient_id = ? AND n.channel = 'in_app'
           ORDER BY n.sent_at DESC, n.id DESC LIMIT 200""",
        (g.user["id"],),
    )
    return render_template("notifications.html", notifications=rows)


@bp.route("/notifications/read", methods=["POST"])
@login_required
def mark_all_read():
    execute("UPDATE notifications SET is_read = 1 WHERE recipient_id = ? AND channel = 'in_app'", (g.user["id"],))
    flash("All notifications marked as read.", "info")
    return redirect(url_for("main.notifications"))


@bp.route("/notifications/<int:notif_id>/read", methods=["POST"])
@login_required
def mark_read(notif_id):
    execute(
        "UPDATE notifications SET is_read = 1 WHERE id = ? AND recipient_id = ?",
        (notif_id, g.user["id"]),
    )
    target = request.form.get("next") or url_for("main.notifications")
    if not target.startswith("/") or target.startswith("//"):
        target = url_for("main.notifications")
    return redirect(target)
