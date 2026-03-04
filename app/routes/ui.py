from flask import Blueprint, jsonify, render_template

ui_bp = Blueprint("ui", __name__)


@ui_bp.get("/")
def index():
    return render_template("index.html")


@ui_bp.get("/healthz")
def healthz():
    return jsonify({"ok": True, "service": "meal-plan-autopilot"}), 200
