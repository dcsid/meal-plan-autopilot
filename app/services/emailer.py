import smtplib
from email.message import EmailMessage
from pathlib import Path

from flask import current_app
from sqlalchemy.orm import Session

from ..models import EmailLog, ParentContact, Student


def deliver_student_report(
    session: Session,
    student: Student,
    report_path: str,
    override_recipients: list[str] | None = None,
) -> dict:
    recipients = override_recipients or _parent_recipients(student)
    if not recipients:
        return {"sent": 0, "failed": 0, "skipped": 1, "reason": "No parent recipients configured."}

    smtp_host = current_app.config.get("SMTP_HOST")
    if not smtp_host:
        for recipient in recipients:
            _log_email(
                session,
                student_id=student.id,
                recipient=recipient,
                subject=_subject(student),
                status="skipped",
                report_path=report_path,
                error_message="SMTP not configured.",
            )
        session.commit()
        return {"sent": 0, "failed": 0, "skipped": len(recipients), "reason": "SMTP not configured."}

    sent = 0
    failed = 0
    for recipient in recipients:
        try:
            _send_email(recipient, student, report_path)
            _log_email(
                session,
                student_id=student.id,
                recipient=recipient,
                subject=_subject(student),
                status="sent",
                report_path=report_path,
                error_message=None,
            )
            sent += 1
        except Exception as exc:  # pragma: no cover - depends on SMTP environment
            _log_email(
                session,
                student_id=student.id,
                recipient=recipient,
                subject=_subject(student),
                status="failed",
                report_path=report_path,
                error_message=str(exc),
            )
            failed += 1

    session.commit()
    return {"sent": sent, "failed": failed, "skipped": 0}


def _send_email(recipient: str, student: Student, report_path: str) -> None:
    smtp_host = current_app.config["SMTP_HOST"]
    smtp_port = int(current_app.config["SMTP_PORT"])
    smtp_user = current_app.config.get("SMTP_USER")
    smtp_password = current_app.config.get("SMTP_PASSWORD")
    smtp_from = current_app.config["SMTP_FROM"]
    use_tls = bool(current_app.config.get("SMTP_TLS", True))

    msg = EmailMessage()
    msg["From"] = smtp_from
    msg["To"] = recipient
    msg["Subject"] = _subject(student)
    msg.set_content(
        f"Attached is the weekly progress report for {student.display_name}. "
        "Please review the report and contact your tutor for any questions."
    )

    path = Path(report_path)
    with path.open("rb") as f:
        data = f.read()
    subtype = "pdf" if path.suffix.lower() == ".pdf" else "html"
    msg.add_attachment(data, maintype="application", subtype=subtype, filename=path.name)

    with smtplib.SMTP(smtp_host, smtp_port) as server:
        if use_tls:
            server.starttls()
        if smtp_user and smtp_password:
            server.login(smtp_user, smtp_password)
        server.send_message(msg)


def _parent_recipients(student: Student) -> list[str]:
    contacts = sorted(student.parent_contacts, key=lambda c: (not c.is_primary, c.email))
    return [c.email for c in contacts]


def _subject(student: Student) -> str:
    center_name = current_app.config.get("CENTER_NAME", "Tutoring Center")
    return f"{center_name}: Weekly Progress Report for {student.display_name}"


def _log_email(
    session: Session,
    student_id: int,
    recipient: str,
    subject: str,
    status: str,
    report_path: str | None,
    error_message: str | None,
) -> None:
    session.add(
        EmailLog(
            student_id=student_id,
            recipient=recipient,
            subject=subject,
            status=status,
            report_path=report_path,
            error_message=error_message,
        )
    )
