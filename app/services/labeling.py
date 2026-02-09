import json
import os
import re
from typing import Iterable

from flask import current_app
from sqlalchemy.orm import Session

from ..models import Question


def label_missing_questions(
    session: Session,
    taxonomy: list[str] | None = None,
    batch_size: int = 20,
) -> dict:
    missing_questions = (
        session.query(Question)
        .filter((Question.topic.is_(None)) | (Question.difficulty.is_(None)))
        .filter(Question.text.isnot(None))
        .all()
    )
    if not missing_questions:
        return {"updated": 0, "mode": "none", "total_candidates": 0}

    use_gpt = bool(current_app.config.get("ENABLE_GPT_LABELING", True))
    api_key = current_app.config.get("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")
    model = current_app.config.get("OPENAI_MODEL", "gpt-4o-mini")

    updated = 0
    mode = "heuristic"
    batches = [missing_questions[i : i + batch_size] for i in range(0, len(missing_questions), batch_size)]

    for batch in batches:
        labels = None
        if use_gpt and api_key:
            labels = _label_with_gpt(batch, model=model, api_key=api_key, taxonomy=taxonomy)
            mode = "gpt" if labels else "heuristic"

        if not labels:
            labels = [_heuristic_label(question.text or "", taxonomy=taxonomy) for question in batch]

        for question, label in zip(batch, labels):
            topic = label.get("topic")
            difficulty = label.get("difficulty")
            if question.topic is None and topic:
                question.topic = topic
                updated += 1
            if question.difficulty is None and difficulty:
                question.difficulty = max(1, min(5, int(difficulty)))
                updated += 1

    session.commit()
    return {"updated": updated, "mode": mode, "total_candidates": len(missing_questions)}


def _label_with_gpt(
    questions: Iterable[Question],
    model: str,
    api_key: str,
    taxonomy: list[str] | None = None,
) -> list[dict] | None:
    try:
        from openai import OpenAI
    except ImportError:
        return None

    payload = [{"id": q.id, "text": q.text or ""} for q in questions]
    taxonomy_text = ", ".join(taxonomy) if taxonomy else "Algebra, Geometry, Reading, Writing, Data Analysis"

    system_prompt = (
        "You classify SAT-style questions. "
        "Return strict JSON with a top-level key 'labels' where each item has: "
        "'id' (int), 'topic' (string), 'difficulty' (int 1-5). "
        f"Use only these topic labels when possible: {taxonomy_text}."
    )

    user_prompt = json.dumps(payload, ensure_ascii=True)
    client = OpenAI(api_key=api_key)

    try:
        response = client.responses.create(
            model=model,
            temperature=0,
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
    except Exception:
        return None

    content = getattr(response, "output_text", "") or ""
    json_blob = _extract_json(content)
    if not json_blob:
        return None

    try:
        parsed = json.loads(json_blob)
    except json.JSONDecodeError:
        return None

    items = parsed.get("labels", [])
    by_id = {item.get("id"): item for item in items if isinstance(item, dict)}
    labels = []
    for question in payload:
        item = by_id.get(question["id"], {})
        labels.append(
            {
                "topic": str(item.get("topic", "")).strip() or None,
                "difficulty": _safe_int(item.get("difficulty")),
            }
        )
    return labels


def _extract_json(text: str) -> str | None:
    if not text:
        return None
    text = text.strip()
    if text.startswith("{") and text.endswith("}"):
        return text

    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if match:
        return match.group(0)
    return None


def _safe_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _heuristic_label(question_text: str, taxonomy: list[str] | None = None) -> dict:
    text = question_text.lower()

    keyword_map = {
        "Algebra": {"equation", "variable", "linear", "quadratic", "system"},
        "Geometry": {"triangle", "circle", "angle", "perimeter", "area"},
        "Data Analysis": {"table", "graph", "probability", "median", "mean"},
        "Reading": {"passage", "author", "inference", "tone", "claim"},
        "Writing": {"grammar", "sentence", "punctuation", "revision", "transition"},
    }

    if taxonomy:
        keyword_map = {k: v for k, v in keyword_map.items() if k in taxonomy} or keyword_map

    topic = "General"
    best_hits = 0
    for candidate, keywords in keyword_map.items():
        hits = sum(1 for kw in keywords if kw in text)
        if hits > best_hits:
            best_hits = hits
            topic = candidate

    word_count = max(1, len(text.split()))
    if word_count < 20:
        difficulty = 2
    elif word_count < 40:
        difficulty = 3
    elif word_count < 70:
        difficulty = 4
    else:
        difficulty = 5

    return {"topic": topic, "difficulty": difficulty}
