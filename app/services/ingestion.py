import re
from datetime import datetime
from typing import Any

import pandas as pd
from sqlalchemy.orm import Session

from ..models import ParentContact, Question, Response, Student, Test


def load_dataframe(file_storage) -> pd.DataFrame:
    if not file_storage or not file_storage.filename:
        raise ValueError("Missing upload file.")

    filename = file_storage.filename.lower()
    if filename.endswith(".csv"):
        return pd.read_csv(file_storage)
    if filename.endswith(".xlsx") or filename.endswith(".xls"):
        return pd.read_excel(file_storage)
    raise ValueError("Unsupported file type. Use CSV or Excel.")


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    column_map = {}
    for col in df.columns:
        normalized = re.sub(r"[^a-z0-9]+", "_", str(col).strip().lower()).strip("_")
        column_map[col] = normalized
    return df.rename(columns=column_map)


def _normalize_scantron(df: pd.DataFrame) -> pd.DataFrame:
    frame = _normalize_columns(df)
    required_long = {"student_id", "question_number", "is_correct"}
    if required_long.issubset(set(frame.columns)):
        if "test_code" not in frame.columns:
            frame["test_code"] = "default-test"
        return frame

    if "student_id" not in frame.columns:
        raise ValueError("Scantron file must include student_id.")

    question_columns = [c for c in frame.columns if re.fullmatch(r"(q)?\d+", c)]
    if not question_columns:
        raise ValueError(
            "Scantron file needs long format (question_number/is_correct) or wide format columns like Q1,Q2."
        )

    if "test_code" not in frame.columns:
        frame["test_code"] = "default-test"

    long_df = frame.melt(
        id_vars=[c for c in frame.columns if c not in question_columns],
        value_vars=question_columns,
        var_name="question_number",
        value_name="is_correct",
    )
    long_df["question_number"] = long_df["question_number"].str.extract(r"(\d+)").astype(int)
    return long_df


def _to_bool(value: Any) -> bool | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "t", "yes", "y", "correct", "c"}:
        return True
    if text in {"0", "false", "f", "no", "n", "incorrect", "i"}:
        return False
    return None


def _normalize_difficulty(value: Any) -> int | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, int):
        return max(1, min(5, value))

    text = str(value).strip().lower()
    lookup = {"easy": 1, "medium": 3, "hard": 5}
    if text in lookup:
        return lookup[text]

    try:
        numeric = int(float(text))
        return max(1, min(5, numeric))
    except ValueError:
        return None


def _parse_date(value: Any):
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if hasattr(value, "date"):
        return value.date()
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _get_or_create_student(session: Session, external_id: str) -> Student:
    student = session.query(Student).filter_by(external_id=external_id).first()
    if student:
        return student
    student = Student(external_id=external_id)
    session.add(student)
    session.flush()
    return student


def _get_or_create_test(session: Session, code: str, taken_on=None) -> Test:
    test = session.query(Test).filter_by(code=code).first()
    if test:
        if taken_on and not test.taken_on:
            test.taken_on = taken_on
        return test

    test = Test(code=code, taken_on=taken_on)
    session.add(test)
    session.flush()
    return test


def _get_or_create_question(session: Session, test_id: int, question_number: int) -> Question:
    question = (
        session.query(Question)
        .filter_by(test_id=test_id, question_number=question_number)
        .first()
    )
    if question:
        return question

    question = Question(test_id=test_id, question_number=question_number)
    session.add(question)
    session.flush()
    return question


def import_scantron_dataframe(df: pd.DataFrame, session: Session) -> dict[str, int]:
    frame = _normalize_scantron(df)
    required = {"student_id", "test_code", "question_number", "is_correct"}
    missing = required.difference(set(frame.columns))
    if missing:
        raise ValueError(f"Missing required columns: {sorted(missing)}")

    counters = {"students_created": 0, "tests_created": 0, "responses_upserted": 0, "errors": 0}

    existing_student_ids = {s.external_id for s in session.query(Student.external_id).all()}
    existing_tests = {t.code for t in session.query(Test.code).all()}

    for record in frame.to_dict(orient="records"):
        student_external_id = str(record["student_id"]).strip()
        test_code = str(record["test_code"]).strip() or "default-test"
        question_number = int(record["question_number"])
        is_correct = _to_bool(record["is_correct"])
        if not student_external_id or is_correct is None:
            counters["errors"] += 1
            continue

        taken_on = _parse_date(record.get("taken_on"))

        student = _get_or_create_student(session, student_external_id)
        if student_external_id not in existing_student_ids:
            counters["students_created"] += 1
            existing_student_ids.add(student_external_id)

        test = _get_or_create_test(session, test_code, taken_on=taken_on)
        if test_code not in existing_tests:
            counters["tests_created"] += 1
            existing_tests.add(test_code)

        question = _get_or_create_question(session, test.id, question_number)
        response = (
            session.query(Response)
            .filter_by(student_id=student.id, question_id=question.id)
            .first()
        )
        if not response:
            response = Response(student_id=student.id, question_id=question.id, is_correct=is_correct)
            session.add(response)
        else:
            response.is_correct = is_correct

        counters["responses_upserted"] += 1

    session.commit()
    return counters


def import_question_metadata_dataframe(df: pd.DataFrame, session: Session) -> dict[str, int]:
    frame = _normalize_columns(df)
    required = {"test_code", "question_number", "question_text"}
    missing = required.difference(set(frame.columns))
    if missing:
        raise ValueError(f"Missing required columns: {sorted(missing)}")

    counters = {"tests_created": 0, "questions_upserted": 0}
    existing_tests = {t.code for t in session.query(Test.code).all()}

    for record in frame.to_dict(orient="records"):
        test_code = str(record["test_code"]).strip() or "default-test"
        question_number = int(record["question_number"])
        taken_on = _parse_date(record.get("taken_on"))
        test = _get_or_create_test(session, test_code, taken_on=taken_on)
        if test_code not in existing_tests:
            counters["tests_created"] += 1
            existing_tests.add(test_code)

        question = _get_or_create_question(session, test.id, question_number)
        question.text = str(record.get("question_text", "")).strip() or question.text

        topic = record.get("topic")
        if topic is not None and str(topic).strip():
            question.topic = str(topic).strip()

        difficulty = _normalize_difficulty(record.get("difficulty"))
        if difficulty is not None:
            question.difficulty = difficulty

        version = record.get("version")
        if version is not None and str(version).strip():
            question.version = str(version).strip()

        counters["questions_upserted"] += 1

    session.commit()
    return counters


def import_parent_contacts_dataframe(df: pd.DataFrame, session: Session) -> dict[str, int]:
    frame = _normalize_columns(df)
    required = {"student_id", "parent_email"}
    missing = required.difference(set(frame.columns))
    if missing:
        raise ValueError(f"Missing required columns: {sorted(missing)}")

    counters = {"contacts_upserted": 0, "errors": 0}
    for record in frame.to_dict(orient="records"):
        student_external_id = str(record["student_id"]).strip()
        email = str(record["parent_email"]).strip().lower()
        if not student_external_id or not email:
            counters["errors"] += 1
            continue

        student = _get_or_create_student(session, student_external_id)
        contact = (
            session.query(ParentContact)
            .filter_by(student_id=student.id, email=email)
            .first()
        )
        if not contact:
            contact = ParentContact(student_id=student.id, email=email)
            session.add(contact)

        full_name = record.get("parent_name")
        if full_name is not None and str(full_name).strip():
            contact.full_name = str(full_name).strip()

        is_primary = _to_bool(record.get("is_primary"))
        if is_primary is not None:
            contact.is_primary = is_primary

        counters["contacts_upserted"] += 1

    session.commit()
    return counters
