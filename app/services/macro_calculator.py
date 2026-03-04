from __future__ import annotations

from ..models import FoodItem, Recipe


class MacroCalculator:
    @staticmethod
    def food_macros(food: FoodItem, grams: float) -> dict[str, float]:
        factor = max(grams, 0.0) / 100.0
        return {
            "calories": round(food.calories_per_100g * factor, 2),
            "protein": round(food.protein_per_100g * factor, 2),
            "carbs": round(food.carbs_per_100g * factor, 2),
            "fat": round(food.fat_per_100g * factor, 2),
        }

    @staticmethod
    def recipe_macros(recipe: Recipe) -> dict[str, float]:
        totals = {"calories": 0.0, "protein": 0.0, "carbs": 0.0, "fat": 0.0}

        for link in recipe.ingredients:
            item = MacroCalculator.food_macros(link.food, link.grams)
            for key in totals:
                totals[key] += item[key]

        servings = max(recipe.servings, 1)
        return {key: round(value / servings, 2) for key, value in totals.items()}

    @staticmethod
    def add_macros(items: list[dict[str, float]]) -> dict[str, float]:
        totals = {"calories": 0.0, "protein": 0.0, "carbs": 0.0, "fat": 0.0}
        for item in items:
            for key in totals:
                totals[key] += float(item.get(key, 0.0))
        return {key: round(value, 2) for key, value in totals.items()}
