from flask import Blueprint, jsonify

from ..extensions import db
from ..models import Student
from ..services.analytics import build_class_overview, build_student_analytics

analytics_bp = Blueprint("analytics", __name__, url_prefix="/api")


@analytics_bp.get("/students/<external_id>/analytics")
def student_analytics(external_id: str):
    student = db.session.query(Student).filter_by(external_id=external_id).first()
    if not student:
        return jsonify({"ok": False, "error": "Student not found."}), 404

    result = build_student_analytics(db.session, student)
    return jsonify({"ok": True, "result": result}), 200


@analytics_bp.get("/analytics/class-overview")
def class_overview():
    result = build_class_overview(db.session)
    return jsonify({"ok": True, "result": result}), 200
