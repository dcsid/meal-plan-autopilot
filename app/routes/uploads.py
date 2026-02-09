from flask import Blueprint, jsonify, request

from ..extensions import db
from ..services.ingestion import (
    import_parent_contacts_dataframe,
    import_question_metadata_dataframe,
    import_scantron_dataframe,
    load_dataframe,
)
from ..services.labeling import label_missing_questions

uploads_bp = Blueprint("uploads", __name__, url_prefix="/api")


@uploads_bp.post("/upload/scantron")
def upload_scantron():
    try:
        file = request.files.get("file")
        dataframe = load_dataframe(file)
        result = import_scantron_dataframe(dataframe, db.session)
        return jsonify({"ok": True, "result": result}), 200
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@uploads_bp.post("/upload/questions")
def upload_questions():
    try:
        file = request.files.get("file")
        dataframe = load_dataframe(file)
        result = import_question_metadata_dataframe(dataframe, db.session)
        return jsonify({"ok": True, "result": result}), 200
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@uploads_bp.post("/upload/parents")
def upload_parents():
    try:
        file = request.files.get("file")
        dataframe = load_dataframe(file)
        result = import_parent_contacts_dataframe(dataframe, db.session)
        return jsonify({"ok": True, "result": result}), 200
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@uploads_bp.post("/questions/label-missing")
def label_missing():
    payload = request.get_json(silent=True) or {}
    taxonomy = payload.get("taxonomy")
    batch_size = int(payload.get("batch_size", 20))

    try:
        result = label_missing_questions(db.session, taxonomy=taxonomy, batch_size=batch_size)
        return jsonify({"ok": True, "result": result}), 200
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
