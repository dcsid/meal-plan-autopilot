import os


def _to_bool(value: str, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key")
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", "sqlite:///tutor_analytics.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    REPORT_OUTPUT_DIR = os.getenv("REPORT_OUTPUT_DIR", "reports")
    CENTER_NAME = os.getenv("CENTER_NAME", "Tutoring Center")

    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    ENABLE_GPT_LABELING = _to_bool(os.getenv("ENABLE_GPT_LABELING"), default=True)

    SMTP_HOST = os.getenv("SMTP_HOST")
    SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USER = os.getenv("SMTP_USER")
    SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
    SMTP_FROM = os.getenv("SMTP_FROM", "noreply@example.com")
    SMTP_TLS = _to_bool(os.getenv("SMTP_TLS"), default=True)

    AUTO_CREATE_TABLES = _to_bool(os.getenv("AUTO_CREATE_TABLES"), default=True)
