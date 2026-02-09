from collections import defaultdict

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from ..models import Question, Response, Student, Test


def _round_accuracy(correct: int, attempts: int) -> float:
    if attempts == 0:
        return 0.0
    return round((correct / attempts) * 100, 1)


def _to_bucket(value, empty_label):
    if value is None or str(value).strip() == "":
        return empty_label
    return str(value)


def build_student_analytics(session: Session, student: Student) -> dict:
    rows = (
        session.query(
            Response.is_correct,
            Question.topic,
            Question.difficulty,
            Test.code,
            Test.taken_on,
            Question.question_number,
        )
        .join(Question, Question.id == Response.question_id)
        .join(Test, Test.id == Question.test_id)
        .filter(Response.student_id == student.id)
        .all()
    )

    overall_attempts = len(rows)
    overall_correct = sum(1 for r in rows if r.is_correct)

    by_topic_map = defaultdict(lambda: {"attempts": 0, "correct": 0})
    by_difficulty_map = defaultdict(lambda: {"attempts": 0, "correct": 0})
    by_test_map = defaultdict(lambda: {"attempts": 0, "correct": 0, "taken_on": None})

    for row in rows:
        topic_key = _to_bucket(row.topic, "Unlabeled")
        diff_key = _to_bucket(row.difficulty, "Unlabeled")
        test_key = row.code

        by_topic_map[topic_key]["attempts"] += 1
        by_difficulty_map[diff_key]["attempts"] += 1
        by_test_map[test_key]["attempts"] += 1

        if row.is_correct:
            by_topic_map[topic_key]["correct"] += 1
            by_difficulty_map[diff_key]["correct"] += 1
            by_test_map[test_key]["correct"] += 1

        if row.taken_on and not by_test_map[test_key]["taken_on"]:
            by_test_map[test_key]["taken_on"] = row.taken_on.isoformat()

    by_topic = []
    for topic, values in by_topic_map.items():
        by_topic.append(
            {
                "topic": topic,
                "attempts": values["attempts"],
                "correct": values["correct"],
                "accuracy": _round_accuracy(values["correct"], values["attempts"]),
            }
        )
    by_topic.sort(key=lambda item: item["accuracy"], reverse=True)

    by_difficulty = []
    for difficulty, values in by_difficulty_map.items():
        by_difficulty.append(
            {
                "difficulty": difficulty,
                "attempts": values["attempts"],
                "correct": values["correct"],
                "accuracy": _round_accuracy(values["correct"], values["attempts"]),
            }
        )
    by_difficulty.sort(key=lambda item: str(item["difficulty"]))

    trend_by_test = []
    for test_code, values in by_test_map.items():
        trend_by_test.append(
            {
                "test_code": test_code,
                "taken_on": values["taken_on"],
                "attempts": values["attempts"],
                "correct": values["correct"],
                "accuracy": _round_accuracy(values["correct"], values["attempts"]),
            }
        )
    trend_by_test.sort(key=lambda item: item["taken_on"] or "")

    topic_candidates = [item for item in by_topic if item["attempts"] >= 2]
    if not topic_candidates:
        topic_candidates = by_topic

    strongest = sorted(topic_candidates, key=lambda item: item["accuracy"], reverse=True)[:3]
    weakest = sorted(topic_candidates, key=lambda item: item["accuracy"])[:3]

    percentile = _student_percentile(session, student.id, overall_correct, overall_attempts)

    return {
        "student_id": student.external_id,
        "student_name": student.display_name,
        "overall": {
            "attempts": overall_attempts,
            "correct": overall_correct,
            "accuracy": _round_accuracy(overall_correct, overall_attempts),
            "percentile": percentile,
        },
        "by_topic": by_topic,
        "by_difficulty": by_difficulty,
        "trend_by_test": trend_by_test,
        "strongest_topics": strongest,
        "weakest_topics": weakest,
    }


def _student_percentile(session: Session, student_id: int, student_correct: int, student_attempts: int):
    if student_attempts == 0:
        return None

    score_expr = func.sum(case((Response.is_correct.is_(True), 1), else_=0)).label("correct")
    attempt_expr = func.count(Response.id).label("attempts")
    all_scores = session.query(Response.student_id, score_expr, attempt_expr).group_by(Response.student_id)

    normalized_scores = []
    for row in all_scores:
        if not row.attempts:
            continue
        normalized_scores.append((row.student_id, row.correct / row.attempts))

    if not normalized_scores:
        return None

    student_score = student_correct / student_attempts
    lower = sum(1 for _, score in normalized_scores if score < student_score)
    equal = sum(1 for _, score in normalized_scores if score == student_score)
    percentile = ((lower + 0.5 * equal) / len(normalized_scores)) * 100
    return round(percentile, 1)


def build_class_overview(session: Session) -> dict:
    topic_rows = (
        session.query(
            Question.topic,
            func.count(Response.id).label("attempts"),
            func.sum(case((Response.is_correct.is_(True), 1), else_=0)).label("correct"),
        )
        .join(Response, Response.question_id == Question.id)
        .group_by(Question.topic)
        .all()
    )

    topic_trends = []
    for row in topic_rows:
        attempts = int(row.attempts or 0)
        correct = int(row.correct or 0)
        topic_trends.append(
            {
                "topic": row.topic or "Unlabeled",
                "attempts": attempts,
                "correct": correct,
                "accuracy": _round_accuracy(correct, attempts),
            }
        )
    topic_trends.sort(key=lambda item: item["accuracy"])

    missed_rows = (
        session.query(
            Test.code,
            Question.question_number,
            Question.topic,
            func.count(Response.id).label("attempts"),
            func.sum(case((Response.is_correct.is_(True), 1), else_=0)).label("correct"),
        )
        .join(Response, Response.question_id == Question.id)
        .join(Test, Test.id == Question.test_id)
        .group_by(Test.code, Question.question_number, Question.topic)
        .all()
    )

    frequently_missed = []
    for row in missed_rows:
        attempts = int(row.attempts or 0)
        correct = int(row.correct or 0)
        accuracy = _round_accuracy(correct, attempts)
        if attempts >= 3:
            frequently_missed.append(
                {
                    "test_code": row.code,
                    "question_number": row.question_number,
                    "topic": row.topic or "Unlabeled",
                    "attempts": attempts,
                    "accuracy": accuracy,
                }
            )
    frequently_missed.sort(key=lambda item: item["accuracy"])

    return {
        "topic_trends": topic_trends,
        "frequently_missed_questions": frequently_missed[:20],
        "students": session.query(Student).count(),
        "tests": session.query(Test).count(),
        "responses": session.query(Response).count(),
    }
