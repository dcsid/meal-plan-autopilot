from __future__ import annotations

from typing import Any, Optional

from ..models import UserPreferences
from .restaurant_locator import RestaurantLocatorService


class RestaurantFinderService:
    SOURCE_NOTE = (
        "Restaurant discovery uses OpenStreetMap Overpass data. Menu links are marked accessible only when "
        "an explicit menu URL or known menu-platform URL is available."
    )

    _PRICE_PER_MEAL = {
        "budget": 13.0,
        "mainstream": 23.0,
        "premium": 38.0,
        "quick": 11.0,
    }

    _GOAL_BOOSTS = {
        "high_protein": ("steak", "bbq", "grill", "kebab", "seafood", "poke"),
        "fat_loss": ("salad", "mediterranean", "vegan", "poke", "grill"),
        "muscle_gain": ("bbq", "burger", "steak", "mexican", "rice", "grill"),
        "low_carb": ("keto", "grill", "seafood", "salad", "protein"),
    }

    def __init__(self, locator: Optional[RestaurantLocatorService] = None):
        self.locator = locator or RestaurantLocatorService()

    def recommend(
        self,
        payload: dict[str, Any],
        preferences: Optional[UserPreferences] = None,
    ) -> dict[str, Any]:
        location = payload.get("location") or {}
        lat = self._safe_float(location.get("latitude"))
        lon = self._safe_float(location.get("longitude"))
        if lat is None or lon is None:
            raise ValueError("Location is required. Use location permission to find nearby restaurants.")

        budget = self._to_float(payload.get("budget_usd"), default=35.0, min_value=5.0, max_value=400.0)
        radius_km = self._to_float(payload.get("radius_km"), default=5.0, min_value=0.5, max_value=25.0)
        goal = self._normalize_goal(payload.get("goal"))
        tradeoff = self._normalize_tradeoff(payload.get("tradeoff"))
        constraints = self._resolve_constraints(payload, preferences)
        cuisine_filters = self._normalize_list(payload.get("cuisines"))

        raw_rows = self.locator.search_restaurants(latitude=lat, longitude=lon, radius_km=radius_km, limit=80)
        if cuisine_filters:
            raw_rows = [
                row for row in raw_rows if self._matches_cuisine_filter(row=row, cuisine_filters=cuisine_filters)
            ]

        evaluated = [
            self._evaluate_restaurant(
                row=row,
                budget_usd=budget,
                goal=goal,
                constraints=constraints,
            )
            for row in raw_rows
        ]
        highlights = self._build_highlights(evaluated)
        ranked = sorted(evaluated, key=lambda row: row["strategy_scores"][tradeoff])

        visible_default_count = sum(1 for row in ranked if row["has_menu_access"])
        hidden_no_menu_count = max(0, len(ranked) - visible_default_count)

        notes: list[str] = [self.SOURCE_NOTE]
        if hidden_no_menu_count:
            notes.append(
                f"{hidden_no_menu_count} result(s) do not have a menu link and are hidden by default in the UI."
            )
        if cuisine_filters:
            notes.append(f"Cuisine filter applied: {', '.join(cuisine_filters)}.")
        if not ranked:
            notes.append("No restaurants matched this location and filter combination.")

        return {
            "input_summary": {
                "budget_usd": round(budget, 2),
                "radius_km": round(radius_km, 2),
                "goal": goal,
                "tradeoff": tradeoff,
                "diet_tags": constraints["diet_tags"],
                "allergens": constraints["allergens"],
                "dislikes": constraints["dislikes"],
                "cuisines": cuisine_filters,
                "location": {"latitude": lat, "longitude": lon},
            },
            "restaurants": ranked,
            "highlights": highlights,
            "visible_default_count": visible_default_count,
            "hidden_no_menu_count": hidden_no_menu_count,
            "source": {
                "locator_name": self.locator.SOURCE_NAME,
                "locator_url": self.locator.SOURCE_URL,
            },
            "notes": notes,
        }

    def _build_highlights(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not rows:
            return []

        strategies = [
            ("budget_first", "Budget First", "Lowest estimated meal cost while respecting constraints."),
            ("closest_store", "Closest", "Shortest distance from your location."),
            ("diet_first", "Diet Fit First", "Best alignment with your dietary constraints."),
            ("balanced", "Balanced", "Balances cost, distance, and diet/goal fit."),
        ]

        highlights: list[dict[str, Any]] = []
        used_ids: set[str] = set()
        for key, label, detail in strategies:
            ranked = sorted(rows, key=lambda row: row["strategy_scores"][key])
            chosen = next((row for row in ranked if row["id"] not in used_ids), ranked[0])
            used_ids.add(chosen["id"])
            highlights.append(
                {
                    "strategy": key,
                    "title": label,
                    "tradeoff_note": detail,
                    "restaurant_id": chosen["id"],
                    "restaurant_name": chosen["name"],
                    "distance_km": chosen["distance_km"],
                    "estimated_cost_usd": chosen["estimated_cost_usd"],
                    "diet_fit_score": chosen["diet_fit_score"],
                    "has_menu_access": chosen["has_menu_access"],
                    "menu_url": chosen["menu_url"],
                }
            )
        return highlights

    def _evaluate_restaurant(
        self,
        row: dict[str, Any],
        budget_usd: float,
        goal: str,
        constraints: dict[str, list[str]],
    ) -> dict[str, Any]:
        text = self._restaurant_text(row)
        price_tier = str(row.get("price_tier") or "mainstream")
        estimated_cost = self._PRICE_PER_MEAL.get(price_tier, 23.0)

        if goal == "high_protein":
            estimated_cost += 1.8
        elif goal == "muscle_gain":
            estimated_cost += 2.2
        elif goal == "fat_loss":
            estimated_cost -= 0.8
        elif goal == "low_carb":
            estimated_cost += 1.0
        estimated_cost = round(max(5.0, estimated_cost), 2)

        diet_fit, flags = self._diet_fit_score(text=text, row=row, constraints=constraints)
        goal_fit = self._goal_fit_score(text=text, goal=goal)

        distance = float(row.get("distance_km") or 0.0)
        budget_gap = round(max(0.0, estimated_cost - budget_usd), 2)
        has_menu = bool(row.get("has_menu_access"))
        menu_penalty = 0.0 if has_menu else 4.4

        strategy_scores = {
            "budget_first": (estimated_cost * 1.0)
            + (budget_gap * 3.4)
            + (distance * 0.7)
            + menu_penalty
            - (diet_fit * 7.5)
            - (goal_fit * 2.4),
            "closest_store": (distance * 12.0)
            + (estimated_cost * 0.42)
            + (budget_gap * 1.5)
            + (menu_penalty * 0.75)
            - (diet_fit * 3.2),
            "diet_first": ((1.0 - diet_fit) * 95.0)
            + (estimated_cost * 0.45)
            + (distance * 1.1)
            + (budget_gap * 1.9)
            + (menu_penalty * 0.8)
            - (goal_fit * 1.7),
            "balanced": (estimated_cost * 0.58)
            + (distance * 3.2)
            + (budget_gap * 2.4)
            + ((1.0 - diet_fit) * 38.0)
            + ((1.0 - goal_fit) * 16.0)
            + menu_penalty,
        }

        return {
            "id": row["id"],
            "name": row["name"],
            "amenity": row.get("amenity"),
            "cuisine_tags": row.get("cuisine_tags") or [],
            "cuisine_label": row.get("cuisine_label") or "unspecified",
            "distance_km": round(distance, 2),
            "price_tier": price_tier,
            "estimated_cost_usd": estimated_cost,
            "budget_ok": budget_gap <= 0,
            "budget_gap_usd": budget_gap,
            "diet_fit_score": round(diet_fit, 3),
            "goal_fit_score": round(goal_fit, 3),
            "website_url": row.get("website_url"),
            "menu_url": row.get("menu_url"),
            "has_menu_access": has_menu,
            "menu_access_note": row.get("menu_access_note") or "none",
            "diet_hints": row.get("diet_hints") or [],
            "flags": flags,
            "strategy_scores": strategy_scores,
            "source": row.get("source") or self.locator.SOURCE_NAME,
        }

    def _diet_fit_score(
        self,
        text: str,
        row: dict[str, Any],
        constraints: dict[str, list[str]],
    ) -> tuple[float, list[str]]:
        score = 0.64
        flags: list[str] = []
        hints = set((row.get("diet_hints") or []))
        diets = set(constraints["diet_tags"])

        if {"vegetarian", "vegan"} & diets:
            if any(token in text for token in ("steak", "bbq", "barbecue", "burger", "chicken", "meat")):
                if not (hints & {"vegetarian", "vegan"}):
                    score -= 0.22
                    flags.append("May not be ideal for vegetarian/vegan preference.")
            if any(token in text for token in ("vegan", "vegetarian", "plant", "salad", "mediterranean")):
                score += 0.18
            if hints & {"vegetarian", "vegan"}:
                score += 0.18

        if "halal" in diets:
            if "halal" in text or "halal" in hints:
                score += 0.24
            else:
                score -= 0.08
                flags.append("No explicit halal marker found.")

        if "gluten-free" in diets:
            if "gluten_free" in text or "gluten-free" in text or "gluten-free" in hints:
                score += 0.22
            elif any(token in text for token in ("pizza", "bakery", "pasta", "ramen", "sandwich")):
                score -= 0.2
                flags.append("Cuisine pattern may conflict with gluten-free preference.")

        for term in constraints["allergens"]:
            if term and term in text:
                score -= 0.12
                flags.append(f"Allergen keyword match: {term}")

        for term in constraints["dislikes"]:
            if term and term in text:
                score -= 0.08
                flags.append(f"Dislike keyword match: {term}")

        return max(0.1, min(1.0, score)), flags

    def _goal_fit_score(self, text: str, goal: str) -> float:
        score = 0.55
        if goal == "balanced":
            return score

        boosts = self._GOAL_BOOSTS.get(goal, ())
        if any(token in text for token in boosts):
            score += 0.25

        if goal == "low_carb" and any(token in text for token in ("pizza", "pasta", "bakery", "rice", "dessert")):
            score -= 0.2
        if goal == "fat_loss" and any(token in text for token in ("fried", "dessert", "shake", "cream")):
            score -= 0.15

        return max(0.1, min(1.0, score))

    def _matches_cuisine_filter(self, row: dict[str, Any], cuisine_filters: list[str]) -> bool:
        text = self._restaurant_text(row)
        return any(token in text for token in cuisine_filters)

    @staticmethod
    def _restaurant_text(row: dict[str, Any]) -> str:
        chunks = [str(row.get("name") or ""), str(row.get("cuisine_label") or "")]
        chunks.extend(row.get("cuisine_tags") or [])
        chunks.extend(row.get("diet_hints") or [])
        return " ".join(chunks).lower()

    def _resolve_constraints(
        self,
        payload: dict[str, Any],
        preferences: Optional[UserPreferences],
    ) -> dict[str, list[str]]:
        return {
            "diet_tags": self._normalize_list(
                payload.get("diet_tags") or (preferences.diet_tags if preferences else [])
            ),
            "allergens": self._normalize_list(
                payload.get("allergens") or (preferences.allergens if preferences else [])
            ),
            "dislikes": self._normalize_list(
                payload.get("dislikes") or (preferences.dislikes if preferences else [])
            ),
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

    @staticmethod
    def _normalize_goal(value: Any) -> str:
        allowed = {"balanced", "high_protein", "fat_loss", "muscle_gain", "low_carb"}
        token = str(value or "balanced").strip().lower()
        return token if token in allowed else "balanced"

    @staticmethod
    def _normalize_tradeoff(value: Any) -> str:
        allowed = {"budget_first", "closest_store", "diet_first", "balanced"}
        token = str(value or "balanced").strip().lower()
        return token if token in allowed else "balanced"

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

