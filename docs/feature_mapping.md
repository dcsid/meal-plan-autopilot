# Feature Mapping

This file maps your requested modules to implementation files in this scaffold.

## 1) Scantron Data Import

- `app/services/ingestion.py`
- API: `POST /api/upload/scantron` in `app/routes/uploads.py`

## 2) Question Metadata Upload

- `app/services/ingestion.py` (`import_question_metadata_dataframe`)
- API: `POST /api/upload/questions`

## 3) AI-Powered Question Labeling

- `app/services/labeling.py`
- API: `POST /api/questions/label-missing`
- Supports custom taxonomy payload

## 4) Data Integration Engine

- Data joins are modeled via relational entities in `app/models.py`
- Aggregation logic in `app/services/analytics.py`

## 5) Analytics Engine

- Student analytics: `build_student_analytics`
- Class analytics: `build_class_overview`

## 6) Visualizations

- Chart generation in `app/services/reporting.py`
- Report template embedding in `app/templates/report.html`

## 7) Weekly Report Generator

- `generate_student_report` in `app/services/reporting.py`
- API: `POST /api/reports/student/<student_id>`

## 8) Parent Email Automation

- SMTP delivery + logging in `app/services/emailer.py`
- Weekly send path in `run_weekly_reports`

## 9) Admin Dashboard

- `GET /admin` in `app/routes/admin.py`
- `GET /api/admin/overview` for JSON analytics snapshot

## 10) Automation Engine

- CLI command: `flask --app run.py run-weekly`
- Script: `scripts/weekly_job.py`

## 11) Configurability & Reusability

- Config flags in `app/config.py` + `.env.example`
- Taxonomy override support in labeling endpoint payload
