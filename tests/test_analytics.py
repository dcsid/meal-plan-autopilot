from app import create_app
from app.extensions import db
from app.models import Question, Response, Student, Test
from app.services.analytics import build_student_analytics


class TestConfig:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    AUTO_CREATE_TABLES = True
    CENTER_NAME = "Test Center"


def test_student_analytics_basic():
    app = create_app(TestConfig)
    with app.app_context():
        student = Student(external_id="S1", first_name="Ada", last_name="Lovelace")
        test = Test(code="SAT-1")
        q1 = Question(test=test, question_number=1, topic="Algebra", difficulty=2)
        q2 = Question(test=test, question_number=2, topic="Geometry", difficulty=3)
        r1 = Response(student=student, question=q1, is_correct=True)
        r2 = Response(student=student, question=q2, is_correct=False)
        db.session.add_all([student, test, q1, q2, r1, r2])
        db.session.commit()

        result = build_student_analytics(db.session, student)
        assert result["overall"]["attempts"] == 2
        assert result["overall"]["correct"] == 1
        assert result["overall"]["accuracy"] == 50.0
