# Feature Mapping

This file maps Meal Plan Autopilot product features to implementation files.

## Pantry CRUD

- Model: `app/models.py` (`PantryItem`)
- API: `app/routes/meal.py` (`GET/POST/PUT/DELETE /api/pantry`)
- Unit conversion: `app/services/unit_conversion.py`

## Food Lookup + Caching

- Service: `app/services/food_lookup.py`
- API: `GET /api/foods/search`
- Persistence cache: `FoodItem` rows in SQLite

## Preferences + Constraints

- Model: `app/models.py` (`UserPreferences`, `MacroTarget`)
- API: `PUT /api/preferences`, `PUT /api/macro-target`

## Recipe Dataset + Macro Precompute

- Seed files: `app/data/foods.json`, `app/data/recipes.json`
- Seed loader: `app/services/seed_data.py`
- Macro computation: `app/services/macro_calculator.py`

## Decision Engine

- Filtering + scoring: `app/services/recipe_filter.py`
- Weekly greedy planner + explanations: `app/services/meal_planner.py`
- API: `POST /api/meal-plan/generate`

## Shopping List Builder

- Service: `app/services/shopping_list.py`
- Output included in meal-plan generation response

## Frontend

- Route: `app/routes/ui.py`
- UI template: `app/templates/index.html`

## Runtime + Bootstrapping

- App factory + blueprints + CLI: `app/__init__.py`
- Config: `app/config.py`
- Entry point: `run.py`
