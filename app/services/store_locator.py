from __future__ import annotations

import json
import math
import time
from typing import Any
from urllib import error, parse, request


class StoreLocatorService:
    NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
    SOURCE_NAME = "OpenStreetMap Nominatim"
    SOURCE_URL = "https://nominatim.openstreetmap.org/"
    CACHE_TTL_SECONDS = 60 * 20

    _SEARCH_TERMS = [
        "supermarket",
        "grocery store",
        "organic grocery",
        "health food store",
        "convenience store",
    ]

    def __init__(self, timeout: int = 12):
        self.timeout = timeout
        self._cache: dict[tuple[str, str], tuple[float, list[dict[str, Any]]]] = {}

    def search_stores(
        self,
        latitude: float,
        longitude: float,
        radius_km: float = 5.0,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        lat = float(latitude)
        lon = float(longitude)
        radius = max(0.5, min(25.0, float(radius_km)))
        max_rows = max(1, min(40, int(limit)))

        viewbox = self._viewbox(lat, lon, radius)
        merged: dict[str, dict[str, Any]] = {}

        for term in self._SEARCH_TERMS:
            for row in self._query_nominatim(term=term, viewbox=viewbox, limit=max_rows):
                identifier = f"{row.get('osm_type')}:{row.get('osm_id')}"
                if identifier in merged:
                    continue

                try:
                    store_lat = float(row.get("lat"))
                    store_lon = float(row.get("lon"))
                except (TypeError, ValueError):
                    continue

                distance = self._haversine_km(lat, lon, store_lat, store_lon)
                if distance > radius * 1.35:
                    continue

                profile = self._profile_store(
                    name=row.get("name") or row.get("display_name") or "Nearby grocery store",
                    place_type=str(row.get("type") or ""),
                    category=str(row.get("category") or ""),
                )
                merged[identifier] = {
                    "id": identifier,
                    "name": row.get("name") or row.get("display_name") or "Nearby grocery store",
                    "display_name": row.get("display_name") or "",
                    "type": str(row.get("type") or ""),
                    "category": str(row.get("category") or ""),
                    "lat": store_lat,
                    "lon": store_lon,
                    "distance_km": round(distance, 2),
                    "price_tier": profile["price_tier"],
                    "price_multiplier": profile["price_multiplier"],
                    "diet_fit_score": profile["diet_fit_score"],
                    "source": self.SOURCE_NAME,
                }

        rows = sorted(
            merged.values(),
            key=lambda item: (item["distance_km"], item["price_multiplier"], -item["diet_fit_score"]),
        )
        return rows[:max_rows]

    def _query_nominatim(self, term: str, viewbox: str, limit: int) -> list[dict[str, Any]]:
        cache_key = (term, viewbox)
        now = time.time()
        cached = self._cache.get(cache_key)
        if cached and (now - cached[0]) < self.CACHE_TTL_SECONDS:
            return cached[1]

        params = {
            "q": term,
            "format": "jsonv2",
            "limit": str(limit),
            "viewbox": viewbox,
            "bounded": "1",
        }
        endpoint = f"{self.NOMINATIM_URL}?{parse.urlencode(params)}"
        req = request.Request(
            endpoint,
            headers={
                "User-Agent": "MealPlanAutopilot/1.0 (smart-shopping)",
                "Accept": "application/json",
            },
        )

        try:
            with request.urlopen(req, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (error.HTTPError, error.URLError, TimeoutError, ValueError):
            payload = []

        rows = payload if isinstance(payload, list) else []
        self._cache[cache_key] = (now, rows)
        return rows

    @staticmethod
    def _viewbox(latitude: float, longitude: float, radius_km: float) -> str:
        lat_delta = radius_km / 111.0
        lon_delta = radius_km / max(1.0, (111.0 * math.cos(math.radians(latitude))))
        left = longitude - lon_delta
        top = latitude + lat_delta
        right = longitude + lon_delta
        bottom = latitude - lat_delta
        return f"{left},{top},{right},{bottom}"

    @staticmethod
    def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        r = 6371.0
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        a = (
            math.sin(dlat / 2) ** 2
            + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
        )
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return r * c

    @staticmethod
    def _profile_store(name: str, place_type: str, category: str) -> dict[str, float | str]:
        label = f"{name} {place_type} {category}".lower()

        budget_keywords = [
            "grocery outlet",
            "food 4 less",
            "aldi",
            "walmart",
            "costco",
            "smart & final",
            "warehouse",
            "cash & carry",
        ]
        premium_keywords = [
            "whole foods",
            "erewhon",
            "sprouts",
            "natural grocers",
            "organic",
            "health food",
        ]

        if any(key in label for key in budget_keywords):
            return {"price_tier": "budget", "price_multiplier": 0.84, "diet_fit_score": 0.72}
        if "convenience" in label:
            return {"price_tier": "quick", "price_multiplier": 1.14, "diet_fit_score": 0.46}
        if any(key in label for key in premium_keywords):
            return {"price_tier": "premium", "price_multiplier": 1.22, "diet_fit_score": 0.9}
        if "health_food" in label or "health food" in label:
            return {"price_tier": "premium", "price_multiplier": 1.2, "diet_fit_score": 0.92}
        return {"price_tier": "mainstream", "price_multiplier": 1.0, "diet_fit_score": 0.76}
