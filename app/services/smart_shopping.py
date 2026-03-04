from __future__ import annotations

import re
from typing import Any, Optional

from ..models import UserPreferences
from .store_locator import StoreLocatorService
from .unit_conversion import to_grams


class SmartShoppingService:
    STORE_SOURCE_NOTE = (
        "Nearby store discovery uses OpenStreetMap Nominatim. Inventory and pricing are estimated, "
        "not real-time store feeds."
    )

    _CATEGORY_PRICE_PER_KG = {
        "protein_animal": 12.8,
        "protein_plant": 8.4,
        "produce": 5.6,
        "grains_starches": 4.0,
        "dairy_eggs": 7.5,
        "oils_condiments": 9.8,
        "supplements": 28.0,
        "other": 6.5,
    }

    _CATEGORY_RULES = [
        ("protein_animal", ["chicken", "beef", "pork", "turkey", "fish", "salmon", "tuna", "shrimp"]),
        ("protein_plant", ["tofu", "tempeh", "lentil", "bean", "chickpea", "edamame", "seitan"]),
        ("produce", ["broccoli", "spinach", "lettuce", "tomato", "onion", "pepper", "zucchini", "cucumber", "fruit"]),
        ("grains_starches", ["rice", "quinoa", "pasta", "noodle", "bread", "tortilla", "potato", "oat", "couscous"]),
        ("dairy_eggs", ["milk", "yogurt", "cheese", "egg"]),
        ("oils_condiments", ["oil", "sauce", "dressing", "vinegar", "seasoning"]),
        ("supplements", ["vitamin", "omega", "protein powder", "creatine", "supplement"]),
    ]

    def __init__(self, locator: Optional[StoreLocatorService] = None):
        self.locator = locator or StoreLocatorService()

    def recommend(
        self,
        payload: dict[str, Any],
        preferences: Optional[UserPreferences] = None,
    ) -> dict[str, Any]:
        normalized = self._normalize_items(payload.get("items"))
        if not normalized:
            raise ValueError("Provide at least one shopping item.")

        budget = self._to_float(payload.get("budget_usd"), default=70.0, min_value=1.0, max_value=2000.0)
        radius_km = self._to_float(payload.get("radius_km"), default=5.0, min_value=0.5, max_value=25.0)
        tradeoff = self._normalize_tradeoff(payload.get("tradeoff"))
        goal = self._normalize_goal(payload.get("goal"))
        constraints = self._resolve_constraints(payload, preferences)

        enriched_items = [
            self._enrich_item(item, goal=goal, constraints=constraints)
            for item in normalized
        ]

        stores = self._resolve_stores(payload, radius_km=radius_km)
        options = self._build_options(enriched_items, stores, budget=budget, goal=goal)
        selected = next((opt for opt in options if opt["strategy"] == tradeoff), options[0] if options else None)

        notes = [self.STORE_SOURCE_NOTE]
        if not payload.get("location"):
            notes.append("Location was not provided. Store options use generalized market profiles.")
        if any(item["constraint_conflict"] for item in enriched_items):
            notes.append("Some inputs conflicted with constraints. Suggested substitutions were applied in estimates.")

        return {
            "input_summary": {
                "budget_usd": round(budget, 2),
                "tradeoff": tradeoff,
                "goal": goal,
                "diet_tags": constraints["diet_tags"],
                "allergens": constraints["allergens"],
                "dislikes": constraints["dislikes"],
                "radius_km": radius_km,
            },
            "items": [
                {
                    "food": item["food"],
                    "effective_food": item["effective_food"],
                    "required_grams": item["required_grams"],
                    "category": item["category"],
                    "estimated_base_cost_usd": item["estimated_base_cost_usd"],
                    "constraint_conflict": item["constraint_conflict"],
                    "flags": item["flags"],
                }
                for item in enriched_items
            ],
            "stores": stores,
            "options": options,
            "selected_option": selected,
            "notes": notes,
            "source": {
                "store_locator": self.locator.SOURCE_NAME,
                "store_locator_url": self.locator.SOURCE_URL,
            },
        }

    def _normalize_items(self, raw_items: Any) -> list[dict[str, Any]]:
        if not isinstance(raw_items, list):
            return []

        merged: dict[str, float] = {}
        for row in raw_items:
            if isinstance(row, str):
                parsed = self._parse_line_item(row)
                if not parsed:
                    continue
                name, grams = parsed
            elif isinstance(row, dict):
                name = str(row.get("food") or row.get("name") or "").strip().lower()
                grams = self._parse_grams_from_dict(row)
                if not name or grams <= 0:
                    continue
            else:
                continue

            merged[name] = merged.get(name, 0.0) + grams

        return [
            {"food": name, "required_grams": round(grams, 2)}
            for name, grams in merged.items()
            if grams > 0
        ]

    def _parse_line_item(self, value: str) -> Optional[tuple[str, float]]:
        line = re.sub(r"\s+", " ", str(value).strip().lower())
        if not line:
            return None

        pattern = re.compile(r"^(.*?)(?:[-:, ]+)?(\d+(?:\.\d+)?)\s*(kg|g|lb|oz)?$")
        match = pattern.match(line)
        if not match:
            return line, 500.0

        name = match.group(1).strip() or line
        amount = float(match.group(2))
        unit = (match.group(3) or "g").strip().lower()
        try:
            grams = to_grams(amount, unit)
        except ValueError:
            grams = amount if unit == "g" else 500.0
        return name, grams

    def _parse_grams_from_dict(self, row: dict[str, Any]) -> float:
        if row.get("required_grams") is not None:
            return max(0.0, float(row.get("required_grams")))
        if row.get("missing_grams") is not None:
            return max(0.0, float(row.get("missing_grams")))

        quantity = row.get("quantity")
        unit = row.get("unit", "g")
        if quantity is None:
            return 0.0
        try:
            return max(0.0, float(to_grams(float(quantity), str(unit))))
        except (TypeError, ValueError):
            return 0.0

    def _resolve_constraints(
        self,
        payload: dict[str, Any],
        preferences: Optional[UserPreferences],
    ) -> dict[str, list[str]]:
        return {
            "diet_tags": self._normalize_list(payload.get("diet_tags") or (preferences.diet_tags if preferences else [])),
            "allergens": self._normalize_list(payload.get("allergens") or (preferences.allergens if preferences else [])),
            "dislikes": self._normalize_list(payload.get("dislikes") or (preferences.dislikes if preferences else [])),
        }

    @staticmethod
    def _normalize_list(value: Any) -> list[str]:
        if isinstance(value, str):
            rows = value.split(",")
        elif isinstance(value, list):
            rows = value
        else:
            rows = []
        output: list[str] = []
        for row in rows:
            token = str(row).strip().lower()
            if token and token not in output:
                output.append(token)
        return output

    def _enrich_item(self, item: dict[str, Any], goal: str, constraints: dict[str, list[str]]) -> dict[str, Any]:
        food = item["food"]
        category = self._infer_category(food)
        effective_food, flags, conflict = self._apply_constraints(food, constraints)
        effective_category = self._infer_category(effective_food)

        base = (item["required_grams"] / 1000.0) * self._CATEGORY_PRICE_PER_KG.get(effective_category, 6.5)
        goal_multiplier = self._goal_multiplier(goal=goal, category=effective_category)
        base *= goal_multiplier

        return {
            "food": food,
            "effective_food": effective_food,
            "required_grams": round(item["required_grams"], 2),
            "category": effective_category,
            "estimated_base_cost_usd": round(base, 2),
            "constraint_conflict": conflict,
            "flags": flags,
            "goal_multiplier": goal_multiplier,
        }

    def _resolve_stores(self, payload: dict[str, Any], radius_km: float) -> list[dict[str, Any]]:
        location = payload.get("location") or {}
        lat = self._safe_float(location.get("latitude"))
        lon = self._safe_float(location.get("longitude"))
        if lat is None or lon is None:
            return self._default_store_profiles()

        rows = self.locator.search_stores(latitude=lat, longitude=lon, radius_km=radius_km, limit=18)
        return rows or self._default_store_profiles()

    def _build_options(
        self,
        items: list[dict[str, Any]],
        stores: list[dict[str, Any]],
        budget: float,
        goal: str,
    ) -> list[dict[str, Any]]:
        if not stores:
            return []

        evaluated: list[dict[str, Any]] = []
        for store in stores:
            plan = self._evaluate_store_plan(store=store, items=items, budget=budget, goal=goal)
            evaluated.append(plan)

        strategies = [
            ("budget_first", "Budget First", "Prioritizes lowest estimated total cost."),
            ("closest_store", "Closest Store", "Prioritizes shortest travel distance."),
            ("diet_first", "Diet Fit First", "Prioritizes stronger diet-constraint fit."),
            ("balanced", "Balanced", "Balances cost, distance, and diet fit."),
        ]

        options: list[dict[str, Any]] = []
        used_store_ids: set[str] = set()
        for key, label, detail in strategies:
            ranked = sorted(evaluated, key=lambda row: row["strategy_scores"][key])
            chosen = next((row for row in ranked if row["store"]["id"] not in used_store_ids), ranked[0])
            used_store_ids.add(chosen["store"]["id"])
            options.append(
                {
                    "strategy": key,
                    "title": label,
                    "tradeoff_note": detail,
                    "store": chosen["store"],
                    "estimated_total_usd": chosen["estimated_total_usd"],
                    "budget_ok": chosen["budget_ok"],
                    "budget_gap_usd": chosen["budget_gap_usd"],
                    "diet_fit_score": chosen["diet_fit_score"],
                    "distance_km": chosen["store"].get("distance_km"),
                    "line_items": chosen["line_items"],
                }
            )
        return options

    def _evaluate_store_plan(
        self,
        store: dict[str, Any],
        items: list[dict[str, Any]],
        budget: float,
        goal: str,
    ) -> dict[str, Any]:
        line_items: list[dict[str, Any]] = []
        subtotal = 0.0
        fit_acc = []

        for item in items:
            base_cost = float(item["estimated_base_cost_usd"])
            cost = base_cost * float(store.get("price_multiplier", 1.0))
            if store.get("price_tier") == "premium" and item["category"] in {"produce", "protein_plant"}:
                cost *= 0.98
            if store.get("price_tier") == "quick":
                cost *= 1.05

            subtotal += cost
            line_items.append(
                {
                    "food": item["food"],
                    "effective_food": item["effective_food"],
                    "required_grams": item["required_grams"],
                    "estimated_cost_usd": round(cost, 2),
                    "category": item["category"],
                    "constraint_conflict": item["constraint_conflict"],
                    "flags": item["flags"],
                }
            )

            base_fit = 0.72 if not item["constraint_conflict"] else 0.45
            base_fit += 0.08 if goal == "high_protein" and item["category"].startswith("protein") else 0.0
            fit_acc.append(min(1.0, max(0.2, base_fit)))

        subtotal = round(subtotal, 2)
        budget_gap = round(max(0.0, subtotal - budget), 2)
        diet_fit = round(
            min(
                1.0,
                ((sum(fit_acc) / max(1, len(fit_acc))) * 0.62) + (float(store.get("diet_fit_score", 0.7)) * 0.38),
            ),
            3,
        )
        distance = float(store.get("distance_km", 3.5) or 3.5)

        strategy_scores = {
            "budget_first": (subtotal * 1.0) + (budget_gap * 5.0) + (distance * 0.8) - (diet_fit * 12.0),
            "closest_store": (distance * 18.0) + (subtotal * 0.35) + (budget_gap * 2.0) - (diet_fit * 8.0),
            "diet_first": ((1.0 - diet_fit) * 120.0) + (subtotal * 0.45) + (distance * 1.1) + (budget_gap * 2.0),
            "balanced": (subtotal * 0.55) + (distance * 4.0) + (budget_gap * 3.0) + ((1.0 - diet_fit) * 42.0),
        }

        return {
            "store": store,
            "line_items": line_items,
            "estimated_total_usd": subtotal,
            "budget_ok": budget_gap <= 0,
            "budget_gap_usd": budget_gap,
            "diet_fit_score": diet_fit,
            "strategy_scores": strategy_scores,
        }

    def _apply_constraints(
        self,
        food: str,
        constraints: dict[str, list[str]],
    ) -> tuple[str, list[str], bool]:
        lowered = food.lower()
        flags: list[str] = []
        conflict = False

        for term in constraints["allergens"]:
            if term and term in lowered:
                flags.append(f"Contains allergen term: {term}")
                conflict = True
        for term in constraints["dislikes"]:
            if term and term in lowered:
                flags.append(f"Matches dislike: {term}")
                conflict = True

        substitution = ""
        diets = set(constraints["diet_tags"])
        if {"vegetarian", "vegan"} & diets and any(
            token in lowered for token in ["chicken", "beef", "pork", "turkey", "fish", "shrimp"]
        ):
            substitution = "firm tofu"
            flags.append("Substituted to support vegetarian/vegan preference.")
            conflict = True
        if "halal" in diets and any(token in lowered for token in ["pork", "bacon", "ham", "lard"]):
            substitution = "chicken breast"
            flags.append("Substituted to support halal preference.")
            conflict = True
        if "gluten-free" in diets and any(token in lowered for token in ["wheat", "bread", "pasta", "whole wheat"]):
            substitution = "rice cooked"
            flags.append("Substituted to support gluten-free preference.")
            conflict = True

        effective_food = substitution or food
        return effective_food, flags, conflict

    def _infer_category(self, food_name: str) -> str:
        name = food_name.lower()
        for category, keywords in self._CATEGORY_RULES:
            if any(keyword in name for keyword in keywords):
                return category
        return "other"

    def _default_store_profiles(self) -> list[dict[str, Any]]:
        return [
            {
                "id": "default-budget",
                "name": "Budget Grocer (estimated)",
                "display_name": "Budget Grocer profile",
                "type": "supermarket",
                "category": "profile",
                "lat": None,
                "lon": None,
                "distance_km": None,
                "price_tier": "budget",
                "price_multiplier": 0.85,
                "diet_fit_score": 0.72,
                "source": "estimated",
            },
            {
                "id": "default-mainstream",
                "name": "Neighborhood Supermarket (estimated)",
                "display_name": "Neighborhood Supermarket profile",
                "type": "supermarket",
                "category": "profile",
                "lat": None,
                "lon": None,
                "distance_km": None,
                "price_tier": "mainstream",
                "price_multiplier": 1.0,
                "diet_fit_score": 0.76,
                "source": "estimated",
            },
            {
                "id": "default-premium",
                "name": "Specialty Health Market (estimated)",
                "display_name": "Specialty Health Market profile",
                "type": "health_food",
                "category": "profile",
                "lat": None,
                "lon": None,
                "distance_km": None,
                "price_tier": "premium",
                "price_multiplier": 1.22,
                "diet_fit_score": 0.9,
                "source": "estimated",
            },
        ]

    @staticmethod
    def _normalize_tradeoff(value: Any) -> str:
        allowed = {"budget_first", "closest_store", "diet_first", "balanced"}
        token = str(value or "balanced").strip().lower()
        return token if token in allowed else "balanced"

    @staticmethod
    def _normalize_goal(value: Any) -> str:
        allowed = {"balanced", "high_protein", "fat_loss", "muscle_gain", "low_carb"}
        token = str(value or "balanced").strip().lower()
        return token if token in allowed else "balanced"

    @staticmethod
    def _goal_multiplier(goal: str, category: str) -> float:
        if goal == "high_protein":
            return 1.08 if category.startswith("protein") else 0.98
        if goal == "fat_loss":
            return 1.03 if category in {"produce", "protein_plant", "protein_animal"} else 0.97
        if goal == "muscle_gain":
            return 1.1 if category in {"protein_animal", "protein_plant", "grains_starches"} else 1.0
        if goal == "low_carb":
            return 0.92 if category == "grains_starches" else 1.03
        return 1.0

    @staticmethod
    def _safe_float(value: Any) -> Optional[float]:
        try:
            if value is None:
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _to_float(value: Any, default: float, min_value: float, max_value: float) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError):
            number = default
        return max(min_value, min(max_value, number))
