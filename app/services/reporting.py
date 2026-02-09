from datetime import datetime
from pathlib import Path

import matplotlib
from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy.orm import Session

from ..models import Student
from .analytics import build_student_analytics
from .emailer import deliver_student_report

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


def generate_student_report(
    session: Session,
    student: Student,
    output_root: Path,
    center_name: str,
) -> dict:
    analytics = build_student_analytics(session, student)
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")

    student_dir = output_root / student.external_id
    chart_dir = student_dir / "charts"
    chart_dir.mkdir(parents=True, exist_ok=True)

    topic_chart = _save_topic_chart(analytics["by_topic"], chart_dir, timestamp)
    difficulty_chart = _save_difficulty_chart(analytics["by_difficulty"], chart_dir, timestamp)
    trend_chart = _save_trend_chart(analytics["trend_by_test"], chart_dir, timestamp)

    template = _template_env().get_template("report.html")
    summary = _summary_text(analytics)

    html = template.render(
        generated_at=datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        center_name=center_name,
        student_name=analytics["student_name"],
        student_id=analytics["student_id"],
        overall=analytics["overall"],
        by_topic=analytics["by_topic"],
        by_difficulty=analytics["by_difficulty"],
        trend_by_test=analytics["trend_by_test"],
        strongest_topics=analytics["strongest_topics"],
        weakest_topics=analytics["weakest_topics"],
        summary=summary,
        topic_chart=topic_chart,
        difficulty_chart=difficulty_chart,
        trend_chart=trend_chart,
    )

    report_path = student_dir / f"report_{timestamp}.html"
    report_path.write_text(html, encoding="utf-8")

    return {
        "report_path": str(report_path),
        "student_id": student.external_id,
        "analytics": analytics,
        "summary": summary,
    }


def run_weekly_reports(
    session: Session,
    output_root: Path,
    send_email: bool,
    center_name: str,
) -> dict:
    output_root.mkdir(parents=True, exist_ok=True)
    students = session.query(Student).all()
    generated = 0
    emailed = 0
    failures = []

    for student in students:
        try:
            result = generate_student_report(
                session=session,
                student=student,
                output_root=output_root,
                center_name=center_name,
            )
            generated += 1

            if send_email:
                email_status = deliver_student_report(
                    session=session,
                    student=student,
                    report_path=result["report_path"],
                )
                emailed += int(email_status.get("sent", 0))
        except Exception as exc:
            failures.append({"student_id": student.external_id, "error": str(exc)})

    return {
        "students_processed": len(students),
        "reports_generated": generated,
        "emails_sent": emailed,
        "failures": failures,
    }


def _template_env() -> Environment:
    templates_dir = Path(__file__).resolve().parents[1] / "templates"
    return Environment(
        loader=FileSystemLoader(str(templates_dir)),
        autoescape=select_autoescape(["html"]),
    )


def _summary_text(analytics: dict) -> str:
    overall = analytics["overall"]["accuracy"]
    strongest = analytics["strongest_topics"][0]["topic"] if analytics["strongest_topics"] else "N/A"
    weakest = analytics["weakest_topics"][0]["topic"] if analytics["weakest_topics"] else "N/A"
    trend = analytics["trend_by_test"]

    trend_note = "No trend available yet."
    if len(trend) >= 2:
        delta = trend[-1]["accuracy"] - trend[0]["accuracy"]
        if delta > 0:
            trend_note = f"Overall test accuracy improved by {round(delta, 1)} points over recent tests."
        elif delta < 0:
            trend_note = f"Overall test accuracy declined by {abs(round(delta, 1))} points over recent tests."
        else:
            trend_note = "Overall test accuracy stayed steady over recent tests."

    return (
        f"Overall accuracy is {overall}%. "
        f"Strongest area is {strongest}; most urgent review area is {weakest}. "
        f"{trend_note}"
    )


def _save_topic_chart(by_topic: list[dict], chart_dir: Path, timestamp: str) -> str | None:
    if not by_topic:
        return None
    labels = [item["topic"] for item in by_topic[:10]]
    values = [item["accuracy"] for item in by_topic[:10]]

    fig, ax = plt.subplots(figsize=(8, 4))
    ax.bar(labels, values, color="#1f77b4")
    ax.set_title("Topic Mastery")
    ax.set_ylabel("Accuracy (%)")
    ax.set_ylim(0, 100)
    ax.tick_params(axis="x", labelrotation=35)
    fig.tight_layout()

    filename = f"topic_mastery_{timestamp}.png"
    output = chart_dir / filename
    fig.savefig(output, dpi=150)
    plt.close(fig)
    return f"charts/{filename}"


def _save_difficulty_chart(by_difficulty: list[dict], chart_dir: Path, timestamp: str) -> str | None:
    if not by_difficulty:
        return None

    labels = [str(item["difficulty"]) for item in by_difficulty]
    sizes = [item["attempts"] for item in by_difficulty]

    fig, ax = plt.subplots(figsize=(5, 5))
    ax.pie(sizes, labels=labels, autopct="%1.0f%%", startangle=140)
    ax.set_title("Question Distribution by Difficulty")
    fig.tight_layout()

    filename = f"difficulty_distribution_{timestamp}.png"
    output = chart_dir / filename
    fig.savefig(output, dpi=150)
    plt.close(fig)
    return f"charts/{filename}"


def _save_trend_chart(trend_by_test: list[dict], chart_dir: Path, timestamp: str) -> str | None:
    if not trend_by_test:
        return None

    labels = [item["test_code"] for item in trend_by_test]
    values = [item["accuracy"] for item in trend_by_test]

    fig, ax = plt.subplots(figsize=(8, 4))
    ax.plot(labels, values, marker="o", color="#ff7f0e")
    ax.set_title("Score Trend Over Time")
    ax.set_ylabel("Accuracy (%)")
    ax.set_ylim(0, 100)
    ax.grid(alpha=0.3)
    fig.tight_layout()

    filename = f"score_trend_{timestamp}.png"
    output = chart_dir / filename
    fig.savefig(output, dpi=150)
    plt.close(fig)
    return f"charts/{filename}"
