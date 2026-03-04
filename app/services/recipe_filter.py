from __future__ import annotations

from ..models import MacroTarget, Recipe, UserPreferences


def filter_recipes(recipes: list[Recipe], preferences: UserPreferences) -> list[Recipe]:
    required_tags = set(preferences.diet_tags)
    blocked_terms = [*preferences.allergens, *preferences.dislikes]

    filtered: list[Recipe] = []
    for recipe in recipes:
        recipe_tags = set(recipe.diet_tags)
        if required_tags and not required_tags.issubset(recipe_tags):
            continue

        ingredient_names = [link.food.name.lower() for link in recipe.ingredients]
        if any(any(term in name for name in ingredient_names) for term in blocked_terms):
            continue

        filtered.append(recipe)

    return filtered


def coverage_score(recipe: Recipe, pantry_grams_by_food: dict[int, float]) -> float:
    if not recipe.ingredients:
        return 0.0

    covered = 0
    for link in recipe.ingredients:
        if pantry_grams_by_food.get(link.food_id, 0.0) >= link.grams:
            covered += 1
    return covered / len(recipe.ingredients)


def pantry_usage_percent(recipe: Recipe, pantry_grams_by_food: dict[int, float]) -> float:
    total_grams = 0.0
    covered_grams = 0.0

    for link in recipe.ingredients:
        total_grams += link.grams
        covered_grams += min(link.grams, pantry_grams_by_food.get(link.food_id, 0.0))

    if total_grams == 0:
        return 0.0
    return round((covered_grams / total_grams) * 100.0, 2)


def macro_fit_error(recipe: Recipe, target: MacroTarget) -> float:
    return abs(recipe.protein_per_serving - target.protein_target) + abs(
        recipe.carbs_per_serving - target.carbs_target
    ) + abs(recipe.fat_per_serving - target.fat_target)


def score_recipe(
    recipe: Recipe,
    pantry_grams_by_food: dict[int, float],
    target: MacroTarget,
    variety_bonus: float,
) -> tuple[float, float, float]:
    coverage = coverage_score(recipe, pantry_grams_by_food)
    macro_error = macro_fit_error(recipe, target)
    score = (coverage * 3.0) - (macro_error * 0.5) + variety_bonus
    return round(score, 4), round(coverage, 4), round(macro_error, 4)
