from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request
from sqlalchemy import func

from ..extensions import db
from ..models import (
    FoodItem,
    GeneratedPlan,
    MacroTarget,
    PantryItem,
    Recipe,
    UserPreferences,
)
from ..services.drug_interactions import DrugInteractionService
from ..services.food_lookup import FoodLookupService
from ..services.geocoding import GeocodingService
from ..services.meal_planner import MealPlanner
from ..services.restaurant_finder import RestaurantFinderService
from ..services.seed_data import ensure_seed_data
from ..services.smart_shopping import SmartShoppingService
from ..services.shopping_list import build_shopping_list
from ..services.unit_conversion import to_grams

meal_bp = Blueprint("meal", __name__, url_prefix="/api")


@meal_bp.get("/bootstrap")
def bootstrap_data():
    ensure_seed_data(db.session)
    return jsonify(
        {
            "ok": True,
            "result": {
                "pantry": _serialize_pantry_items(),
                "preferences": _serialize_preferences(_get_preferences()),
                "macro_target": _serialize_macro_target(_get_macro_target()),
            },
        }
    )


@meal_bp.get("/foods/search")
def search_foods():
    query = (request.args.get("q") or "").strip()
    if not query:
        return jsonify({"ok": False, "error": "Missing required query parameter 'q'."}), 400
    try:
        requested_limit = int(request.args.get("limit", 25))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Query parameter 'limit' must be an integer."}), 400
    try:
        requested_page = int(request.args.get("page", 1))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Query parameter 'page' must be an integer."}), 400
    limit = max(1, min(50, requested_limit))
    page = max(1, min(50, requested_page))

    ensure_seed_data(db.session)
    service = FoodLookupService(db.session, current_app.config.get("USDA_API_KEY"))
    results = service.search_foods(query, limit=limit, page=page)
    return (
        jsonify(
            {
                "ok": True,
                "result": results,
                "metadata": {
                    "limit": limit,
                    "page": page,
                    "usda_status": service.last_remote_error or "ok",
                },
            }
        ),
        200,
    )


@meal_bp.post("/location/geocode")
def geocode_location():
    payload = request.get_json(silent=True) or {}
    query = (payload.get("query") or "").strip()
    if not query:
        return jsonify({"ok": False, "error": "Missing required field 'query'."}), 400

    try:
        requested_limit = int(payload.get("limit", 5))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Field 'limit' must be an integer."}), 400
    limit = max(1, min(10, requested_limit))

    service = GeocodingService()
    results = service.search(query=query, limit=limit)
    return (
        jsonify(
            {
                "ok": True,
                "result": {
                    "query": query,
                    "matches": results,
                    "source": {
                        "name": service.SOURCE_NAME,
                        "url": service.SOURCE_URL,
                    },
                },
            }
        ),
        200,
    )


@meal_bp.post("/interactions/check")
def check_interactions():
    payload = request.get_json(silent=True) or {}
    items = payload.get("items")

    service = DrugInteractionService()
    try:
        result = service.check_interactions(items)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    return jsonify({"ok": True, "result": result}), 200


@meal_bp.post("/shopping/recommend")
def recommend_shopping():
    payload = request.get_json(silent=True) or {}
    service = SmartShoppingService()
    try:
        result = service.recommend(payload=payload, preferences=_get_preferences())
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    return jsonify({"ok": True, "result": result}), 200


@meal_bp.post("/restaurants/recommend")
def recommend_restaurants():
    payload = request.get_json(silent=True) or {}
    service = RestaurantFinderService()
    try:
        result = service.recommend(payload=payload, preferences=_get_preferences())
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    return jsonify({"ok": True, "result": result}), 200


@meal_bp.get("/pantry")
def list_pantry():
    return jsonify({"ok": True, "result": _serialize_pantry_items()}), 200


@meal_bp.post("/pantry")
def add_pantry_item():
    payload = request.get_json(silent=True) or {}
    try:
        quantity = float(payload.get("quantity", 0))
        unit = payload.get("unit", "g")
        quantity_grams = to_grams(quantity, unit)
        food = _resolve_food_from_payload(payload)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    existing = db.session.query(PantryItem).filter_by(food_id=food.id).first()
    if existing:
        existing.quantity_grams = round(existing.quantity_grams + quantity_grams, 2)
        existing.display_quantity = round(existing.quantity_grams, 2)
        existing.display_unit = "g"
        item = existing
    else:
        item = PantryItem(
            food_id=food.id,
            quantity_grams=quantity_grams,
            display_quantity=round(quantity, 2),
            display_unit=unit,
        )
        db.session.add(item)

    db.session.commit()
    return jsonify({"ok": True, "result": _serialize_pantry_item(item)}), 201


@meal_bp.put("/pantry/<int:item_id>")
def update_pantry_item(item_id: int):
    item = db.session.get(PantryItem, item_id)
    if not item:
        return jsonify({"ok": False, "error": "Pantry item not found."}), 404

    payload = request.get_json(silent=True) or {}
    try:
        quantity = float(payload.get("quantity", item.display_quantity))
        unit = payload.get("unit", item.display_unit)
        item.quantity_grams = to_grams(quantity, unit)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    item.display_quantity = round(quantity, 2)
    item.display_unit = unit
    db.session.commit()

    return jsonify({"ok": True, "result": _serialize_pantry_item(item)}), 200


@meal_bp.delete("/pantry/<int:item_id>")
def delete_pantry_item(item_id: int):
    item = db.session.get(PantryItem, item_id)
    if not item:
        return jsonify({"ok": False, "error": "Pantry item not found."}), 404

    db.session.delete(item)
    db.session.commit()
    return jsonify({"ok": True, "result": {"deleted": item_id}}), 200


@meal_bp.get("/preferences")
def get_preferences():
    return jsonify({"ok": True, "result": _serialize_preferences(_get_preferences())}), 200


@meal_bp.put("/preferences")
def update_preferences():
    preferences = _get_preferences()
    payload = request.get_json(silent=True) or {}

    preferences.diet_tags_csv = _csv_from_payload(payload.get("diet_tags"))
    preferences.allergens_csv = _csv_from_payload(payload.get("allergens"))
    preferences.dislikes_csv = _csv_from_payload(payload.get("dislikes"))

    db.session.commit()
    return jsonify({"ok": True, "result": _serialize_preferences(preferences)}), 200


@meal_bp.get("/macro-target")
def get_macro_target():
    return jsonify({"ok": True, "result": _serialize_macro_target(_get_macro_target())}), 200


@meal_bp.put("/macro-target")
def update_macro_target():
    target = _get_macro_target()
    payload = request.get_json(silent=True) or {}
    try:
        target.calories = float(payload.get("calories", target.calories))
        target.protein_min = float(payload.get("protein_min", target.protein_min))
        target.protein_max = float(payload.get("protein_max", target.protein_max))
        target.carbs_min = float(payload.get("carbs_min", target.carbs_min))
        target.carbs_max = float(payload.get("carbs_max", target.carbs_max))
        target.fat_min = float(payload.get("fat_min", target.fat_min))
        target.fat_max = float(payload.get("fat_max", target.fat_max))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Macro target values must be numeric."}), 400

    db.session.commit()
    return jsonify({"ok": True, "result": _serialize_macro_target(target)}), 200


@meal_bp.get("/recipes")
def list_recipes():
    ensure_seed_data(db.session)
    rows = db.session.query(Recipe).order_by(Recipe.name.asc()).all()
    return jsonify({"ok": True, "result": [_serialize_recipe(row) for row in rows]}), 200


@meal_bp.post("/meal-plan/generate")
def generate_plan():
    ensure_seed_data(db.session)
    payload = request.get_json(silent=True) or {}
    try:
        days = int(payload.get("days", 7))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Days must be an integer."}), 400
    days = max(1, min(14, days))

    planner = MealPlanner(
        session=db.session,
        preferences=_get_preferences(),
        target=_get_macro_target(),
        pantry_items=db.session.query(PantryItem).all(),
    )

    try:
        output = planner.generate(days=days)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    recipe_lookup = {
        recipe.id: recipe
        for recipe in db.session.query(Recipe).filter(Recipe.id.in_(output["recipe_ids"])).all()
    }
    selected_recipes = [recipe_lookup[recipe_id] for recipe_id in output["recipe_ids"] if recipe_id in recipe_lookup]
    shopping_list = build_shopping_list(
        selected_recipes=selected_recipes,
        pantry_items=db.session.query(PantryItem).all(),
    )

    db.session.add(GeneratedPlan(days=len(output["plan"])))
    db.session.commit()

    return (
        jsonify(
            {
                "ok": True,
                "result": {
                    "plan": output["plan"],
                    "shopping_list": shopping_list,
                    "macro_summary": output["macro_summary"],
                    "metadata": {
                        "candidate_count": output["candidate_count"],
                        "generated_days": len(output["plan"]),
                    },
                },
            }
        ),
        200,
    )


def _resolve_food_from_payload(payload: dict) -> FoodItem:
    food_id = payload.get("food_id")
    if food_id:
        food = db.session.get(FoodItem, int(food_id))
        if not food:
            raise ValueError("Food item not found for provided food_id.")
        return food

    food_name = (payload.get("food_name") or "").strip().lower()
    if not food_name:
        raise ValueError("Provide either food_id or food_name.")

    food = db.session.query(FoodItem).filter(func.lower(FoodItem.name) == food_name).first()
    if not food:
        food = FoodItem(
            name=food_name,
            source="manual",
            calories_per_100g=float(payload.get("calories", 0.0)),
            protein_per_100g=float(payload.get("protein", 0.0)),
            carbs_per_100g=float(payload.get("carbs", 0.0)),
            fat_per_100g=float(payload.get("fat", 0.0)),
        )
        db.session.add(food)
        db.session.flush()

    return food


def _serialize_pantry_items() -> list[dict]:
    rows = db.session.query(PantryItem).order_by(PantryItem.id.asc()).all()
    return [_serialize_pantry_item(row) for row in rows]


def _serialize_pantry_item(item: PantryItem) -> dict:
    return {
        "id": item.id,
        "food_id": item.food_id,
        "food": item.food.name,
        "quantity_grams": round(item.quantity_grams, 2),
        "display_quantity": round(item.display_quantity, 2),
        "display_unit": item.display_unit,
        "nutrients_per_100g": {
            "calories": round(item.food.calories_per_100g, 2),
            "protein": round(item.food.protein_per_100g, 2),
            "carbs": round(item.food.carbs_per_100g, 2),
            "fat": round(item.food.fat_per_100g, 2),
        },
    }


def _get_preferences() -> UserPreferences:
    preferences = db.session.get(UserPreferences, 1)
    if not preferences:
        preferences = UserPreferences(id=1)
        db.session.add(preferences)
        db.session.commit()
    return preferences


def _get_macro_target() -> MacroTarget:
    target = db.session.get(MacroTarget, 1)
    if not target:
        target = MacroTarget(id=1)
        db.session.add(target)
        db.session.commit()
    return target


def _serialize_preferences(preferences: UserPreferences) -> dict:
    return {
        "diet_tags": preferences.diet_tags,
        "allergens": preferences.allergens,
        "dislikes": preferences.dislikes,
    }


def _serialize_macro_target(target: MacroTarget) -> dict:
    return {
        "calories": round(target.calories, 2),
        "protein_min": round(target.protein_min, 2),
        "protein_max": round(target.protein_max, 2),
        "carbs_min": round(target.carbs_min, 2),
        "carbs_max": round(target.carbs_max, 2),
        "fat_min": round(target.fat_min, 2),
        "fat_max": round(target.fat_max, 2),
    }


def _serialize_recipe(recipe: Recipe) -> dict:
    return {
        "id": recipe.id,
        "name": recipe.name,
        "servings": recipe.servings,
        "diet_tags": recipe.diet_tags,
        "main_protein": recipe.main_protein,
        "macros_per_serving": {
            "calories": round(recipe.calories_per_serving, 2),
            "protein": round(recipe.protein_per_serving, 2),
            "carbs": round(recipe.carbs_per_serving, 2),
            "fat": round(recipe.fat_per_serving, 2),
        },
        "ingredients": [
            {
                "food_id": link.food_id,
                "food": link.food.name,
                "grams": round(link.grams, 2),
            }
            for link in recipe.ingredients
        ],
    }


def _csv_from_payload(value) -> str:
    if isinstance(value, str):
        rows = [part.strip().lower() for part in value.split(",") if part.strip()]
    elif isinstance(value, list):
        rows = [str(part).strip().lower() for part in value if str(part).strip()]
    else:
        rows = []

    deduped = list(dict.fromkeys(rows))
    return ",".join(deduped)
