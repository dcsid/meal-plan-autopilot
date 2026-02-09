# AI Tutoring Analytics Platform

Flask-based analytics system for tutoring centers that ingest assessment data, auto-label questions, compute student performance insights, generate weekly reports, and send parent emails.

## What is included

- Scantron upload pipeline (CSV/XLSX, long and wide formats)
- Question metadata upload and version-aware updates
- AI-assisted topic/difficulty labeling with GPT and heuristic fallback
- Student and class analytics engine (topic, difficulty, trends, percentile)
- Branded weekly HTML report generation with charts
- Parent email delivery and email logs
- Admin dashboard + API endpoints
- Weekly automation entrypoint (`scripts/weekly_job.py`)

## Quick start

1. Create virtual environment and install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2. Configure environment:

```bash
cp .env.example .env
```

3. Run the app:

```bash
python run.py
```

4. Useful endpoints:

- `POST /api/upload/scantron`
- `POST /api/upload/questions`
- `POST /api/upload/parents`
- `POST /api/questions/label-missing`
- `GET /api/students/<student_id>/analytics`
- `GET /api/analytics/class-overview`
- `POST /api/reports/student/<student_id>`
- `POST /api/reports/weekly`
- `GET /admin`

## Input formats

### Scantron upload

Long format columns:

- `student_id`
- `test_code`
- `question_number`
- `is_correct`
- optional `taken_on`

Wide format is also supported:

- `student_id`
- optional `test_code`
- `Q1..Qn` (or `1..n`) where values are `1/0`, `true/false`, `correct/incorrect`

### Question metadata upload

- `test_code`
- `question_number`
- `question_text`
- optional `topic`
- optional `difficulty` (1-5 or Easy/Medium/Hard)
- optional `version`
- optional `taken_on`

### Parent contacts upload

- `student_id`
- `parent_email`
- optional `parent_name`
- optional `is_primary`

## Weekly automation

Use Flask CLI:

```bash
flask --app run.py run-weekly
```

or:

```bash
python scripts/weekly_job.py
```

Reports are written to `REPORT_OUTPUT_DIR` (default: `reports/`).

## Notes

- GPT labeling is optional and controlled by `ENABLE_GPT_LABELING` + `OPENAI_API_KEY`.
- If SMTP is not configured, report email attempts are logged as `skipped`.
- This scaffold is production-minded but intentionally lightweight; see `docs/feature_mapping.md` for module mapping.
