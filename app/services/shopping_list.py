from __future__ import annotations

from ..models import PantryItem, Recipe


def build_shopping_list(selected_recipes: list[Recipe], pantry_items: list[PantryItem]) -> list[dict]:
    required_grams: dict[int, float] = {}
    food_names: dict[int, str] = {}

    for recipe in selected_recipes:
        for link in recipe.ingredients:
            required_grams[link.food_id] = required_grams.get(link.food_id, 0.0) + link.grams
            food_names[link.food_id] = link.food.name

    pantry_grams: dict[int, float] = {}
    for item in pantry_items:
        pantry_grams[item.food_id] = pantry_grams.get(item.food_id, 0.0) + item.quantity_grams

    rows: list[dict] = []
    for food_id, required in required_grams.items():
        pantry_qty = pantry_grams.get(food_id, 0.0)
        missing = max(0.0, required - pantry_qty)
        if missing <= 0:
            continue

        rows.append(
            {
                "food_id": food_id,
                "food": food_names[food_id],
                "required_grams": round(required, 2),
                "pantry_grams": round(pantry_qty, 2),
                "missing_grams": round(missing, 2),
            }
        )

    return sorted(rows, key=lambda row: row["food"])
