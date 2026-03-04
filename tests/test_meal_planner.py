from app.models import FoodItem, MacroTarget, PantryItem, Recipe, UserPreferences
from app.services.meal_planner import MealPlanner
from app.services.seed_data import ensure_seed_data
from app.services.shopping_list import build_shopping_list


def test_seed_data_loads_foods_and_recipes(db_session):
    ensure_seed_data(db_session)
    assert db_session.query(FoodItem).count() >= 20
    assert db_session.query(Recipe).count() >= 8


def test_meal_planner_respects_preferences(db_session):
    prefs = db_session.get(UserPreferences, 1)
    prefs.diet_tags_csv = "vegetarian"
    prefs.allergens_csv = "shrimp"
    prefs.dislikes_csv = ""
    db_session.commit()

    planner = MealPlanner(
        session=db_session,
        preferences=prefs,
        target=db_session.get(MacroTarget, 1),
        pantry_items=[],
    )
    output = planner.generate(days=4)

    assert len(output["plan"]) == 4
    for item in output["plan"]:
        assert "vegetarian" in item["diet_tags"]
        assert "shrimp" not in item["recipe_name"].lower()
        assert item["explanation"]


def test_shopping_list_subtracts_existing_pantry(db_session):
    recipe = db_session.query(Recipe).filter_by(name="Lemon Chicken Rice Bowl").first()
    assert recipe is not None

    chicken = db_session.query(FoodItem).filter_by(name="chicken breast").first()
    assert chicken is not None

    pantry_item = PantryItem(
        food_id=chicken.id,
        quantity_grams=1000,
        display_quantity=1000,
        display_unit="g",
    )

    shopping = build_shopping_list([recipe], [pantry_item])
    names = [row["food"] for row in shopping]

    assert "chicken breast" not in names
    assert "rice cooked" in names


def test_generate_plan_endpoint_shape(client):
    response = client.post("/api/meal-plan/generate", json={"days": 2})
    assert response.status_code == 200

    data = response.get_json()
    assert data["ok"] is True
    assert len(data["result"]["plan"]) == 2
    assert "shopping_list" in data["result"]
    assert "macro_summary" in data["result"]
    assert "metadata" in data["result"]
