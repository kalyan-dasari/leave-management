import logging
import os
import secrets
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, flash, g, redirect, render_template, url_for
from flask_wtf.csrf import CSRFProtect

from . import db as db_module
from .security import load_user

BASE_DIR = Path(__file__).resolve().parent.parent


def create_app(test_config=None):
    load_dotenv(BASE_DIR / ".env")

    app = Flask(__name__, static_folder=str(BASE_DIR / "static"), template_folder=str(BASE_DIR / "templates"))
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY") or secrets.token_hex(32),
        DATABASE=os.environ.get("DATABASE_PATH") or str(BASE_DIR / "leaves.db"),
        UPLOAD_FOLDER=str(BASE_DIR / "uploads"),
        MAX_CONTENT_LENGTH=5 * 1024 * 1024,
        MAIL_SERVER=os.environ.get("MAIL_SERVER", "smtp.gmail.com"),
        MAIL_PORT=int(os.environ.get("MAIL_PORT", 587)),
        MAIL_USE_TLS=os.environ.get("MAIL_USE_TLS", "true").lower() == "true",
        MAIL_USERNAME=os.environ.get("MAIL_USERNAME"),
        MAIL_PASSWORD=os.environ.get("MAIL_PASSWORD"),
        MAIL_DEFAULT_SENDER=os.environ.get("MAIL_DEFAULT_SENDER") or os.environ.get("MAIL_USERNAME"),
        PER_PAGE=10,
        WTF_CSRF_ENABLED=True,
    )
    if test_config:
        app.config.update(test_config)

    if not os.environ.get("SECRET_KEY"):
        app.logger.warning("SECRET_KEY not set - using a random development key (sessions reset on restart).")

    Path(app.config["UPLOAD_FOLDER"]).mkdir(parents=True, exist_ok=True)

    db_module.init_app(app)
    CSRFProtect(app)

    with app.app_context():
        db_module.init_db()

    from .notify import unread_count

    @app.before_request
    def _load_current_user():
        load_user()

    @app.context_processor
    def _inject_globals():
        user = getattr(g, "user", None)
        return {
            "current_user": user,
            "unread_count": unread_count(user["id"]) if user else 0,
        }

    @app.errorhandler(403)
    def forbidden(_e):
        return render_template("errors/403.html"), 403

    @app.errorhandler(404)
    def not_found(_e):
        return render_template("errors/404.html"), 404

    @app.errorhandler(413)
    def too_large(_e):
        flash("Attachment is too large (maximum 5 MB).", "danger")
        return redirect(url_for("student.new_request")), 413

    from . import admin_views, auth, main, review, student

    app.register_blueprint(main.bp)
    app.register_blueprint(auth.bp)
    app.register_blueprint(student.bp)
    app.register_blueprint(review.bp)
    app.register_blueprint(admin_views.bp)

    logging.basicConfig(level=logging.INFO)
    return app
