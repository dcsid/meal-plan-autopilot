from __future__ import annotations

from typing import Optional

from ..models import MacroTarget, PantryItem, Recipe, UserPreferences
from .recipe_filter import filter_recipes, pantry_usage_percent, score_recipe


class MealPlanner:
    def __init__(
        self,
        session,
        preferences: UserPreferences,
        target: MacroTarget,
        pantry_items: list[PantryItem],
    ):
        self.session = session
        self.preferences = preferences
        self.target = target
        self.pantry_items = pantry_items

    def generate(self, days: int = 7) -> dict:
        recipes = self.session.query(Recipe).all()
        candidates = filter_recipes(recipes, self.preferences)
        if not candidates:
            raise ValueError("No recipes match the current preferences and restriction filters.")

        pantry_map = {item.food_id: float(item.quantity_grams) for item in self.pantry_items}
        protein_counts: dict[str, int] = {}
        used_recipe_ids: set[int] = set()

        plan: list[dict] = []
        for day in range(1, days + 1):
            best = None
            for recipe in candidates:
                variety = self._variety_bonus(recipe.main_protein, protein_counts)
                repeat_penalty = -1.0 if recipe.id in used_recipe_ids else 0.0
                score, coverage, macro_error = score_recipe(
                    recipe,
                    pantry_map,
                    self.target,
                    variety + repeat_penalty,
                )
                if best is None or score > best["score"]:
                    best = {
                        "recipe": recipe,
                        "score": score,
                        "coverage": coverage,
                        "macro_error": macro_error,
                    }

            if not best:
                break

            recipe = best["recipe"]
            usage_percent = pantry_usage_percent(recipe, pantry_map)
            available_names = [
                link.food.name for link in recipe.ingredients if pantry_map.get(link.food_id, 0.0) > 0
            ]

            plan.append(
                {
                    "day": day,
                    "recipe_id": recipe.id,
                    "recipe_name": recipe.name,
                    "main_protein": recipe.main_protein,
                    "diet_tags": recipe.diet_tags,
                    "score": round(best["score"], 2),
                    "coverage": round(best["coverage"], 2),
                    "macro_error": round(best["macro_error"], 2),
                    "pantry_usage_percent": usage_percent,
                    "macros": {
                        "calories": round(recipe.calories_per_serving, 2),
                        "protein": round(recipe.protein_per_serving, 2),
                        "carbs": round(recipe.carbs_per_serving, 2),
                        "fat": round(recipe.fat_per_serving, 2),
                    },
                    "ingredients": [
                        {"food": link.food.name, "grams": round(link.grams, 2)}
                        for link in recipe.ingredients
                    ],
                    "explanation": self._explain(
                        recipe.name,
                        usage_percent,
                        available_names,
                        best["macro_error"],
                    ),
                }
            )

            used_recipe_ids.add(recipe.id)
            if recipe.main_protein:
                key = recipe.main_protein.lower().strip()
                protein_counts[key] = protein_counts.get(key, 0) + 1

            self._consume_pantry(pantry_map, recipe)

        macro_summary = [
            {
                "day": item["day"],
                "planned": item["macros"],
                "target": {
                    "calories": round(self.target.calories, 2),
                    "protein_range": [
                        round(self.target.protein_min, 2),
                        round(self.target.protein_max, 2),
                    ],
                    "carbs_range": [
                        round(self.target.carbs_min, 2),
                        round(self.target.carbs_max, 2),
                    ],
                    "fat_range": [
                        round(self.target.fat_min, 2),
                        round(self.target.fat_max, 2),
                    ],
                },
            }
            for item in plan
        ]

        return {
            "plan": plan,
            "macro_summary": macro_summary,
            "recipe_ids": [item["recipe_id"] for item in plan],
            "candidate_count": len(candidates),
        }

    @staticmethod
    def _variety_bonus(main_protein: Optional[str], counts: dict[str, int]) -> float:
        if not main_protein:
            return 0.0

        key = main_protein.strip().lower()
        seen = counts.get(key, 0)
        if seen == 0:
            return 1.0
        if seen == 1:
            return 0.25
        return -0.5 * seen

    @staticmethod
    def _consume_pantry(pantry_map: dict[int, float], recipe: Recipe) -> None:
        for link in recipe.ingredients:
            current = pantry_map.get(link.food_id, 0.0)
            pantry_map[link.food_id] = max(0.0, current - link.grams)

    @staticmethod
    def _explain(
        recipe_name: str,
        usage_percent: float,
        pantry_foods: list[str],
        macro_error: float,
    ) -> str:
        pantry_fragment = " + ".join(pantry_foods[:2]) if pantry_foods else "limited pantry overlap"
        return (
            f"Selected {recipe_name} because it uses {pantry_fragment} and keeps macro error at "
            f"{round(macro_error, 2)} with {round(usage_percent, 1)}% pantry coverage."
        )
