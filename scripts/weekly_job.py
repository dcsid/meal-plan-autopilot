import json

from app import create_app
from app.extensions import db
from app.models import MacroTarget, PantryItem, Recipe, UserPreferences
from app.services.meal_planner import MealPlanner
from app.services.seed_data import ensure_seed_data
from app.services.shopping_list import build_shopping_list


def main():
    app = create_app()
    with app.app_context():
        ensure_seed_data(db.session)
        planner = MealPlanner(
            session=db.session,
            preferences=db.session.get(UserPreferences, 1),
            target=db.session.get(MacroTarget, 1),
            pantry_items=db.session.query(PantryItem).all(),
        )
        output = planner.generate(days=7)

        recipe_lookup = {
            row.id: row
            for row in db.session.query(Recipe).filter(Recipe.id.in_(output["recipe_ids"])).all()
        }
        selected = [recipe_lookup[row_id] for row_id in output["recipe_ids"] if row_id in recipe_lookup]
        shopping = build_shopping_list(selected, db.session.query(PantryItem).all())

    print(json.dumps({"plan": output["plan"], "shopping_list": shopping}, indent=2))


if __name__ == "__main__":
    main()
