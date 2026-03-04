from flask import Flask

from .config import Config
from .extensions import db
from .services.demo_data import ensure_demo_pantry
from .services.seed_data import ensure_seed_data


def create_app(config_class=Config) -> Flask:
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)

    with app.app_context():
        from . import models  # noqa: F401

        if app.config.get("AUTO_CREATE_TABLES", True):
            db.create_all()

        if app.config.get("AUTO_SEED_DATA", True):
            ensure_seed_data(db.session)
        if app.config.get("AUTO_SEED_DEMO_PANTRY", False):
            ensure_demo_pantry(db.session)

    _register_blueprints(app)
    _register_cli(app)
    return app


def _register_blueprints(app: Flask) -> None:
    from .routes.meal import meal_bp
    from .routes.ui import ui_bp

    app.register_blueprint(ui_bp)
    app.register_blueprint(meal_bp)


def _register_cli(app: Flask) -> None:
    @app.cli.command("init-db")
    def init_db() -> None:
        with app.app_context():
            db.create_all()
            ensure_seed_data(db.session)
            if app.config.get("AUTO_SEED_DEMO_PANTRY", False):
                ensure_demo_pantry(db.session)
        print("Database initialized and seed data loaded.")

    @app.cli.command("seed-data")
    def seed_data() -> None:
        with app.app_context():
            result = ensure_seed_data(db.session)
            if app.config.get("AUTO_SEED_DEMO_PANTRY", False):
                result.update(ensure_demo_pantry(db.session))
        print(result)
