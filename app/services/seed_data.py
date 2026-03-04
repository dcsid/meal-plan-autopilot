from __future__ import annotations

import json
from pathlib import Path

from ..models import FoodItem, MacroTarget, Recipe, RecipeIngredient, UserPreferences
from .macro_calculator import MacroCalculator

DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def _load_json(filename: str) -> list[dict]:
    path = DATA_DIR / filename
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def ensure_default_profiles(session) -> dict[str, int]:
    changes = 0

    preferences = session.get(UserPreferences, 1)
    if not preferences:
        session.add(UserPreferences(id=1))
        changes += 1

    target = session.get(MacroTarget, 1)
    if not target:
        session.add(MacroTarget(id=1))
        changes += 1

    if changes:
        session.commit()

    return {"defaults_created": changes}


def seed_food_items(session) -> dict[str, int]:
    rows = _load_json("foods.json")
    existing = {food.name.lower(): food for food in session.query(FoodItem).all()}

    created = 0
    for row in rows:
        name = row["name"].strip().lower()
        food = existing.get(name)
        if not food:
            food = FoodItem(name=row["name"].strip(), source="seed")
            session.add(food)
            existing[name] = food
            created += 1

        food.calories_per_100g = float(row["calories"])
        food.protein_per_100g = float(row["protein"])
        food.carbs_per_100g = float(row["carbs"])
        food.fat_per_100g = float(row["fat"])

    session.commit()
    return {"foods_created": created, "foods_total": len(existing)}


def seed_recipes(session) -> dict[str, int]:
    rows = _load_json("recipes.json")
    foods = {food.name.lower(): food for food in session.query(FoodItem).all()}
    existing = {recipe.name.lower(): recipe for recipe in session.query(Recipe).all()}

    created = 0
    for row in rows:
        key = row["name"].strip().lower()
        recipe = existing.get(key)
        if not recipe:
            recipe = Recipe(name=row["name"].strip())
            session.add(recipe)
            existing[key] = recipe
            created += 1
        elif recipe.ingredients:
            continue

        recipe.servings = int(row.get("servings", 1) or 1)
        recipe.diet_tags_csv = ",".join(
            tag.strip().lower() for tag in row.get("diet_tags", []) if tag.strip()
        )
        recipe.main_protein = (row.get("main_protein") or "").strip().lower() or None

        recipe.ingredients.clear()
        for ingredient in row.get("ingredients", []):
            food_name = ingredient["food"].strip().lower()
            food = foods.get(food_name)
            if food is None:
                raise ValueError(f"Missing food item '{food_name}' for recipe '{recipe.name}'.")
            recipe.ingredients.append(
                RecipeIngredient(food=food, grams=float(ingredient["grams"]))
            )

        macros = MacroCalculator.recipe_macros(recipe)
        recipe.calories_per_serving = macros["calories"]
        recipe.protein_per_serving = macros["protein"]
        recipe.carbs_per_serving = macros["carbs"]
        recipe.fat_per_serving = macros["fat"]

    session.commit()
    return {"recipes_created": created, "recipes_total": len(existing)}


def ensure_seed_data(session) -> dict[str, int]:
    results: dict[str, int] = {}
    results.update(seed_food_items(session))
    results.update(seed_recipes(session))
    results.update(ensure_default_profiles(session))
    return results
