from __future__ import annotations

import json
from urllib import error, request
from typing import Optional

from sqlalchemy import func, or_

from ..models import FoodItem


class FoodLookupService:
    USDA_SEARCH_URL = "https://api.nal.usda.gov/fdc/v1/foods/search"

    def __init__(self, session, api_key: Optional[str] = None):
        self.session = session
        self.api_key = api_key
        self.last_remote_error: Optional[str] = None

    def search_foods(self, query: str, limit: int = 10, page: int = 1) -> list[dict]:
        normalized = query.strip()
        if not normalized:
            return []

        self.last_remote_error = None
        safe_limit = max(1, min(50, int(limit)))
        safe_page = max(1, int(page))
        local = self._search_local(normalized, max(safe_limit, 25))
        if not self.api_key or len(normalized) < 2:
            if not self.api_key:
                self.last_remote_error = "disabled"
            return local[:safe_limit]

        remote_limit = min(max(safe_limit * 4, 50), 200)
        remote = self._search_usda(normalized, remote_limit, page=safe_page)
        seen = {item["id"] for item in local}
        merged = list(local)
        for item in remote:
            if item["id"] not in seen:
                merged.append(item)
                seen.add(item["id"])
        ranked = sorted(
            merged,
            key=lambda row: (-self._score_name_match(row["name"], normalized), row["name"]),
        )
        return ranked[:safe_limit]

    def _search_local(self, query: str, limit: int) -> list[dict]:
        normalized = query.lower().strip()
        if not normalized:
            return []

        tokens = [token for token in normalized.replace(",", " ").split() if token]
        patterns = [f"%{normalized}%"] + [f"%{token}%" for token in tokens]
        patterns = list(dict.fromkeys(patterns))

        rows = (
            self.session.query(FoodItem)
            .filter(or_(*[func.lower(FoodItem.name).like(pattern) for pattern in patterns]))
            .all()
        )

        ranked = sorted(rows, key=lambda row: (-self._score_name_match(row.name, normalized), row.name))
        return [self.serialize_food(row) for row in ranked[:limit]]

    def _search_usda(self, query: str, limit: int, page: int = 1) -> list[dict]:
        payload = {
            "query": query,
            "pageSize": limit,
            "pageNumber": page,
            "dataType": ["Foundation", "SR Legacy", "Branded", "Survey (FNDDS)"],
            "sortBy": "dataType.keyword",
            "sortOrder": "asc",
        }
        endpoint = f"{self.USDA_SEARCH_URL}?api_key={self.api_key}"
        body = json.dumps(payload).encode("utf-8")
        req = request.Request(
            endpoint,
            data=body,
            method="POST",
            headers={"Content-Type": "application/json"},
        )

        try:
            with request.urlopen(req, timeout=10) as response:
                data = json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            if exc.code == 429:
                self.last_remote_error = "rate_limited"
            elif exc.code in {401, 403}:
                self.last_remote_error = "unauthorized"
            else:
                self.last_remote_error = f"http_{exc.code}"
            return []
        except (error.URLError, TimeoutError):
            self.last_remote_error = "unavailable"
            return []
        except ValueError:
            self.last_remote_error = "invalid_response"
            return []

        created_or_updated: list[FoodItem] = []
        for row in data.get("foods", []):
            parsed = self._parse_usda_row(row)
            if not parsed:
                continue
            created_or_updated.append(self._upsert_from_usda(parsed))

        if created_or_updated:
            self.session.commit()

        return [self.serialize_food(row) for row in created_or_updated]

    @staticmethod
    def _score_name_match(name: str, query: str) -> float:
        normalized_name = name.lower()
        normalized_query = query.lower().strip()
        tokens = [token for token in normalized_query.replace(",", " ").split() if token]

        value = 0.0
        if normalized_name == normalized_query:
            value += 100.0
        if normalized_name.startswith(normalized_query):
            value += 40.0
        if normalized_query in normalized_name:
            value += 25.0

        matched_tokens = 0
        for token in tokens:
            if token in normalized_name:
                value += 10.0
                matched_tokens += 1
        value += matched_tokens * 4.0
        value -= abs(len(normalized_name) - len(normalized_query)) * 0.05
        return value

    def _parse_usda_row(self, row: dict) -> Optional[dict]:
        description = (row.get("description") or "").strip()
        fdc_id = row.get("fdcId")
        if not description or fdc_id is None:
            return None

        nutrients = {
            "calories": None,
            "protein": None,
            "carbs": None,
            "fat": None,
        }
        for nutrient in row.get("foodNutrients", []):
            name = (
                nutrient.get("nutrientName")
                or nutrient.get("name")
                or nutrient.get("nutrient", {}).get("name")
                or ""
            ).strip().lower()
            nutrient_number = str(nutrient.get("nutrientNumber") or "").strip()
            value = nutrient.get("value")
            if value is None:
                value = nutrient.get("amount")
            if value is None:
                continue

            numeric = self._coerce_float(value)
            if numeric is None:
                continue

            if nutrient_number == "1008" or name in {"energy", "energy (kcal)"}:
                nutrients["calories"] = numeric
            elif nutrient_number == "1003" or name == "protein":
                nutrients["protein"] = numeric
            elif nutrient_number == "1005" or name == "carbohydrate, by difference":
                nutrients["carbs"] = numeric
            elif nutrient_number == "1004" or name == "total lipid (fat)":
                nutrients["fat"] = numeric

        # Branded rows frequently expose nutrient values via labelNutrients.
        label_nutrients = row.get("labelNutrients") or {}
        if nutrients["calories"] is None:
            nutrients["calories"] = self._coerce_float((label_nutrients.get("calories") or {}).get("value"))
        if nutrients["protein"] is None:
            nutrients["protein"] = self._coerce_float((label_nutrients.get("protein") or {}).get("value"))
        if nutrients["carbs"] is None:
            nutrients["carbs"] = self._coerce_float((label_nutrients.get("carbohydrates") or {}).get("value"))
        if nutrients["fat"] is None:
            nutrients["fat"] = self._coerce_float((label_nutrients.get("fat") or {}).get("value"))

        return {
            "fdc_id": str(fdc_id),
            "name": description.lower(),
            "calories": float(nutrients["calories"] or 0.0),
            "protein": float(nutrients["protein"] or 0.0),
            "carbs": float(nutrients["carbs"] or 0.0),
            "fat": float(nutrients["fat"] or 0.0),
        }

    @staticmethod
    def _coerce_float(value) -> Optional[float]:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _upsert_from_usda(self, row: dict) -> FoodItem:
        food = self.session.query(FoodItem).filter_by(fdc_id=row["fdc_id"]).first()
        if not food:
            food = self.session.query(FoodItem).filter(
                func.lower(FoodItem.name) == row["name"].lower()
            ).first()

        if not food:
            food = FoodItem(name=row["name"])
            self.session.add(food)

        food.fdc_id = row["fdc_id"]
        food.source = "usda"
        food.calories_per_100g = row["calories"]
        food.protein_per_100g = row["protein"]
        food.carbs_per_100g = row["carbs"]
        food.fat_per_100g = row["fat"]
        return food

    @staticmethod
    def serialize_food(food: FoodItem) -> dict:
        return {
            "id": food.id,
            "name": food.name,
            "source": food.source,
            "fdc_id": food.fdc_id,
            "nutrients_per_100g": {
                "calories": round(food.calories_per_100g, 2),
                "protein": round(food.protein_per_100g, 2),
                "carbs": round(food.carbs_per_100g, 2),
                "fat": round(food.fat_per_100g, 2),
            },
        }
