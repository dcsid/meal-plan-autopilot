from pathlib import Path

from flask import Blueprint, current_app, jsonify, request

from ..extensions import db
from ..models import Student
from ..services.emailer import deliver_student_report
from ..services.reporting import generate_student_report, run_weekly_reports

reports_bp = Blueprint("reports", __name__, url_prefix="/api")


@reports_bp.post("/reports/student/<external_id>")
def create_student_report(external_id: str):
    student = db.session.query(Student).filter_by(external_id=external_id).first()
    if not student:
        return jsonify({"ok": False, "error": "Student not found."}), 404

    payload = request.get_json(silent=True) or {}
    send_email = bool(payload.get("send_email", False))
    override = payload.get("recipients")

    result = generate_student_report(
        session=db.session,
        student=student,
        output_root=Path(current_app.config["REPORT_OUTPUT_DIR"]),
        center_name=current_app.config["CENTER_NAME"],
    )

    email_result = None
    if send_email:
        recipients = override if isinstance(override, list) else None
        email_result = deliver_student_report(
            session=db.session,
            student=student,
            report_path=result["report_path"],
            override_recipients=recipients,
        )

    return jsonify({"ok": True, "result": result, "email": email_result}), 200


@reports_bp.post("/reports/weekly")
def run_weekly():
    payload = request.get_json(silent=True) or {}
    send_email = bool(payload.get("send_email", True))

    result = run_weekly_reports(
        session=db.session,
        output_root=Path(current_app.config["REPORT_OUTPUT_DIR"]),
        send_email=send_email,
        center_name=current_app.config["CENTER_NAME"],
    )
    return jsonify({"ok": True, "result": result}), 200
