from datetime import datetime

from .extensions import db


class Student(db.Model):
    __tablename__ = "students"

    id = db.Column(db.Integer, primary_key=True)
    external_id = db.Column(db.String(64), unique=True, nullable=False, index=True)
    first_name = db.Column(db.String(64), nullable=True)
    last_name = db.Column(db.String(64), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    responses = db.relationship("Response", back_populates="student", cascade="all, delete-orphan")
    parent_contacts = db.relationship(
        "ParentContact", back_populates="student", cascade="all, delete-orphan"
    )
    email_logs = db.relationship("EmailLog", back_populates="student", cascade="all, delete-orphan")

    @property
    def display_name(self) -> str:
        name = " ".join(part for part in [self.first_name, self.last_name] if part).strip()
        if name:
            return name
        return f"Student {self.external_id}"


class Test(db.Model):
    __tablename__ = "tests"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(64), unique=True, nullable=False, index=True)
    name = db.Column(db.String(128), nullable=True)
    taken_on = db.Column(db.Date, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    questions = db.relationship("Question", back_populates="test", cascade="all, delete-orphan")


class Question(db.Model):
    __tablename__ = "questions"
    __table_args__ = (db.UniqueConstraint("test_id", "question_number", name="uq_test_question"),)

    id = db.Column(db.Integer, primary_key=True)
    test_id = db.Column(db.Integer, db.ForeignKey("tests.id"), nullable=False, index=True)
    question_number = db.Column(db.Integer, nullable=False)
    text = db.Column(db.Text, nullable=True)
    topic = db.Column(db.String(128), nullable=True, index=True)
    difficulty = db.Column(db.Integer, nullable=True, index=True)  # 1-5
    version = db.Column(db.String(32), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    test = db.relationship("Test", back_populates="questions")
    responses = db.relationship("Response", back_populates="question", cascade="all, delete-orphan")


class Response(db.Model):
    __tablename__ = "responses"
    __table_args__ = (db.UniqueConstraint("student_id", "question_id", name="uq_student_question"),)

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False, index=True)
    question_id = db.Column(db.Integer, db.ForeignKey("questions.id"), nullable=False, index=True)
    is_correct = db.Column(db.Boolean, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    student = db.relationship("Student", back_populates="responses")
    question = db.relationship("Question", back_populates="responses")


class ParentContact(db.Model):
    __tablename__ = "parent_contacts"
    __table_args__ = (db.UniqueConstraint("student_id", "email", name="uq_student_parent_email"),)

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False, index=True)
    email = db.Column(db.String(255), nullable=False)
    full_name = db.Column(db.String(128), nullable=True)
    is_primary = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    student = db.relationship("Student", back_populates="parent_contacts")


class EmailLog(db.Model):
    __tablename__ = "email_logs"

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False, index=True)
    recipient = db.Column(db.String(255), nullable=False)
    subject = db.Column(db.String(255), nullable=False)
    status = db.Column(db.String(32), nullable=False)
    error_message = db.Column(db.Text, nullable=True)
    report_path = db.Column(db.Text, nullable=True)
    sent_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    student = db.relationship("Student", back_populates="email_logs")
