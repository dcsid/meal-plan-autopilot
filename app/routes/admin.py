from flask import Blueprint, jsonify, render_template_string

from ..extensions import db
from ..models import EmailLog, ParentContact, Question, Response, Student, Test
from ..services.analytics import build_class_overview

admin_bp = Blueprint("admin", __name__)


@admin_bp.get("/admin")
def admin_dashboard():
    context = {
        "students": db.session.query(Student).count(),
        "tests": db.session.query(Test).count(),
        "questions": db.session.query(Question).count(),
        "responses": db.session.query(Response).count(),
        "parents": db.session.query(ParentContact).count(),
        "emails": db.session.query(EmailLog).count(),
    }

    template = """
    <!doctype html>
    <html>
    <head>
      <title>Tutoring Analytics Admin</title>
      <style>
        body { font-family: Arial, sans-serif; margin: 24px; }
        .grid { display: grid; grid-template-columns: repeat(3, minmax(180px, 1fr)); gap: 12px; }
        .card { border: 1px solid #ddd; border-radius: 8px; padding: 12px; }
        .label { font-size: 12px; color: #666; text-transform: uppercase; }
        .value { font-size: 28px; font-weight: bold; margin-top: 8px; }
      </style>
    </head>
    <body>
      <h1>Tutoring Analytics Admin</h1>
      <div class="grid">
        <div class="card"><div class="label">Students</div><div class="value">{{ students }}</div></div>
        <div class="card"><div class="label">Tests</div><div class="value">{{ tests }}</div></div>
        <div class="card"><div class="label">Questions</div><div class="value">{{ questions }}</div></div>
        <div class="card"><div class="label">Responses</div><div class="value">{{ responses }}</div></div>
        <div class="card"><div class="label">Parent Emails</div><div class="value">{{ parents }}</div></div>
        <div class="card"><div class="label">Email Logs</div><div class="value">{{ emails }}</div></div>
      </div>
      <p>API endpoints are available under <code>/api/*</code>.</p>
    </body>
    </html>
    """
    return render_template_string(template, **context)


@admin_bp.get("/api/admin/overview")
def admin_overview():
    result = build_class_overview(db.session)
    return jsonify({"ok": True, "result": result}), 200
