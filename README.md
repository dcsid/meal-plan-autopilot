# Meal Plan Autopilot

Pantry-aware, macro-constrained weekly meal planning for normal people.

This is a web app (Flask backend + browser UI), built to be easy for interviewers to open and click through.

## What it does

- Pantry CRUD with quantity + unit conversion to grams
- Diet tags, allergens, and dislikes constraints
- Daily calorie + protein/carbs/fat target ranges
- Weekly greedy planner with explainable scoring
- Shopping list of only missing ingredients
- USDA FoodData Central lookup with local cache (falls back to `DEMO_KEY` if key is blank)
- Medications & supplements workspace using FDA openFDA label data for interaction signals and diet/nutrient effect mentions (informational-only framing)
- Seeded local foods + recipes for offline/demo use

## Stack

- Flask + Flask-SQLAlchemy
- SQLite (or Postgres via `DATABASE_URL`)
- Vanilla HTML/CSS/JS UI
- Gunicorn for production serving
- Includes `psycopg2-binary` so `postgresql://...` URLs work out of the box

## Run locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python run.py
```

Open [http://localhost:5000](http://localhost:5000).

## Interview-ready hosted format (recommended)

Use a **public Render web service URL** so interviewers can click through immediately.

### Option A: Blueprint deploy (fastest)

1. Push this repo to GitHub.
2. In Render, choose **New + > Blueprint** and connect the repo.
3. Render will read `/render.yaml` and create the service.
4. Share the generated URL (no login required).

### Option B: Manual Render deploy

1. Create a new **Web Service** from the repo.
2. Set:
   - Build command: `pip install -r requirements.txt`
   - Start command: `gunicorn run:app --bind 0.0.0.0:$PORT --workers 2 --threads 4 --timeout 120 --worker-tmp-dir /tmp`
3. Add env vars:
   - `SECRET_KEY` (random)
   - `DATABASE_URL=sqlite:////tmp/meal_autopilot.db`
   - `AUTO_CREATE_TABLES=true`
   - `AUTO_SEED_DATA=true`
   - `AUTO_SEED_DEMO_PANTRY=true`
   - `USDA_API_KEY` (optional)

## Why this is low-friction for interviewers

- Public URL, no setup/downloads
- Health endpoint: `GET /healthz`
- Demo pantry can auto-seed on boot (`AUTO_SEED_DEMO_PANTRY=true`), so plan generation works immediately
- Existing API + UI are in one deployment

## Core endpoints

- `GET /`
- `GET /healthz`
- `GET /api/bootstrap`
- `GET /api/foods/search?q=<term>&limit=<1..50>`
- `POST /api/interactions/check`
- `GET /api/pantry`
- `POST /api/pantry`
- `PUT /api/pantry/<id>`
- `DELETE /api/pantry/<id>`
- `GET /api/preferences`
- `PUT /api/preferences`
- `GET /api/macro-target`
- `PUT /api/macro-target`
- `GET /api/recipes`
- `POST /api/meal-plan/generate`

## Tests

```bash
source .venv/bin/activate
PYTHONPYCACHEPREFIX=/tmp/pycache pytest -q
```

Current suite covers endpoint contracts, validation paths, planner behavior, lookup service behavior, seed idempotency, and UI route integrity.

## Chrome Extension Prototype

This repo also includes a standalone Chrome extension at `chrome-fact-checker/`:

- deterministic, non-AI fact checker
- weighted source confidence model
- context categorization
- full citation report page with decision trace

Load it in Chrome via `chrome://extensions` -> **Load unpacked** -> select `chrome-fact-checker/`.
