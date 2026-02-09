from pathlib import Path
import json

from app import create_app
from app.extensions import db
from app.services.reporting import run_weekly_reports


def main():
    app = create_app()
    with app.app_context():
        result = run_weekly_reports(
            session=db.session,
            output_root=Path(app.config["REPORT_OUTPUT_DIR"]),
            send_email=True,
            center_name=app.config["CENTER_NAME"],
        )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
