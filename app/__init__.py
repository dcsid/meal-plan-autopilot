from pathlib import Path

from flask import Flask

from .config import Config
from .extensions import db


def create_app(config_class=Config) -> Flask:
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)

    with app.app_context():
        from . import models  # noqa: F401

        if app.config.get("AUTO_CREATE_TABLES", True):
            db.create_all()

    _register_blueprints(app)
    _register_cli(app)
    _ensure_report_dir(app)
    return app


def _register_blueprints(app: Flask) -> None:
    from .routes.admin import admin_bp
    from .routes.analytics import analytics_bp
    from .routes.reports import reports_bp
    from .routes.uploads import uploads_bp

    app.register_blueprint(uploads_bp)
    app.register_blueprint(analytics_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(admin_bp)


def _register_cli(app: Flask) -> None:
    @app.cli.command("init-db")
    def init_db() -> None:
        with app.app_context():
            db.create_all()
        print("Database initialized.")

    @app.cli.command("run-weekly")
    def run_weekly() -> None:
        from .services.reporting import run_weekly_reports

        with app.app_context():
            summary = run_weekly_reports(
                db.session,
                output_root=Path(app.config["REPORT_OUTPUT_DIR"]),
                send_email=True,
                center_name=app.config["CENTER_NAME"],
            )
        print(summary)


def _ensure_report_dir(app: Flask) -> None:
    Path(app.config["REPORT_OUTPUT_DIR"]).mkdir(parents=True, exist_ok=True)
