from __future__ import annotations

import json
import math
import re
import time
from typing import Any, Optional
from urllib import error, parse, request


class RestaurantLocatorService:
    OVERPASS_URL = "https://overpass-api.de/api/interpreter"
    SOURCE_NAME = "OpenStreetMap Overpass API"
    SOURCE_URL = "https://overpass-api.de/"
    CACHE_TTL_SECONDS = 60 * 15

    _MENU_PLATFORM_HINTS = (
        "doordash.",
        "ubereats.",
        "grubhub.",
        "seamless.",
        "postmates.",
        "menupages.",
        "opentable.",
        "resy.",
        "yelp.com",
    )

    _PREMIUM_CUISINES = {
        "sushi",
        "steak_house",
        "steakhouse",
        "fine_dining",
        "french",
    }
    _BUDGET_CUISINES = {
        "fast_food",
        "sandwich",
        "pizza",
        "burger",
        "food_court",
        "taco",
    }

    def __init__(self, timeout: int = 14):
        self.timeout = timeout
        self._cache: dict[tuple[str, str, str, int], tuple[float, list[dict[str, Any]]]] = {}

    def search_restaurants(
        self,
        latitude: float,
        longitude: float,
        radius_km: float = 5.0,
        limit: int = 60,
    ) -> list[dict[str, Any]]:
        lat = float(latitude)
        lon = float(longitude)
        radius = max(0.5, min(25.0, float(radius_km)))
        max_rows = max(1, min(120, int(limit)))

        key = (f"{lat:.4f}", f"{lon:.4f}", f"{radius:.1f}", max_rows)
        now = time.time()
        cached = self._cache.get(key)
        if cached and (now - cached[0]) < self.CACHE_TTL_SECONDS:
            return cached[1]

        elements = self._query_overpass(lat, lon, radius, max_rows)
        deduped: dict[str, dict[str, Any]] = {}

        for element in elements:
            row = self._normalize_element(element=element, origin_lat=lat, origin_lon=lon)
            if not row:
                continue
            identifier = row["id"]
            if identifier in deduped:
                continue
            deduped[identifier] = row

        rows = sorted(
            deduped.values(),
            key=lambda item: (
                item.get("distance_km", 999.0),
                0 if item.get("has_menu_access") else 1,
                item.get("name", ""),
            ),
        )[:max_rows]
        self._cache[key] = (now, rows)
        return rows

    def _query_overpass(
        self,
        lat: float,
        lon: float,
        radius_km: float,
        limit: int,
    ) -> list[dict[str, Any]]:
        radius_m = int(max(500, min(25000, radius_km * 1000)))
        query = self._build_query(lat=lat, lon=lon, radius_m=radius_m, limit=limit)
        payload = parse.urlencode({"data": query}).encode("utf-8")
        req = request.Request(
            self.OVERPASS_URL,
            data=payload,
            headers={
                "User-Agent": "MealPlanAutopilot/1.0 (restaurant-finder)",
                "Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
                "Accept": "application/json",
            },
        )
        try:
            with request.urlopen(req, timeout=self.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except (error.HTTPError, error.URLError, TimeoutError, ValueError):
            return []
        rows = data.get("elements")
        return rows if isinstance(rows, list) else []

    @staticmethod
    def _build_query(lat: float, lon: float, radius_m: int, limit: int) -> str:
        return (
            "[out:json][timeout:25];"
            "("
            f'node(around:{radius_m},{lat},{lon})["amenity"~"restaurant|fast_food|cafe|food_court"];'
            f'way(around:{radius_m},{lat},{lon})["amenity"~"restaurant|fast_food|cafe|food_court"];'
            f'relation(around:{radius_m},{lat},{lon})["amenity"~"restaurant|fast_food|cafe|food_court"];'
            ");"
            f"out center tags {limit};"
        )

    def _normalize_element(
        self,
        element: dict[str, Any],
        origin_lat: float,
        origin_lon: float,
    ) -> Optional[dict[str, Any]]:
        tags = element.get("tags") if isinstance(element.get("tags"), dict) else {}
        if not tags:
            return None

        name = str(tags.get("name") or "").strip()
        if not name:
            return None

        lat = self._safe_float(element.get("lat"))
        lon = self._safe_float(element.get("lon"))
        if lat is None or lon is None:
            center = element.get("center") if isinstance(element.get("center"), dict) else {}
            lat = self._safe_float(center.get("lat"))
            lon = self._safe_float(center.get("lon"))
        if lat is None or lon is None:
            return None

        cuisines = self._split_cuisine(tags.get("cuisine"))
        amenity = str(tags.get("amenity") or "").strip().lower() or "restaurant"

        website_url = self._normalize_url(tags.get("website") or tags.get("contact:website") or tags.get("url"))
        explicit_menu = (
            tags.get("menu:url")
            or tags.get("menu")
            or tags.get("contact:menu")
            or tags.get("url:menu")
        )
        menu_url = self._normalize_url(explicit_menu)
        menu_access_note = "none"
        if menu_url:
            menu_access_note = "explicit_osm_menu_tag"
        elif website_url:
            if self._is_menu_platform(website_url):
                menu_url = website_url
                menu_access_note = "known_menu_platform"
            elif self._looks_like_menu_path(website_url):
                menu_url = website_url
                menu_access_note = "website_menu_path"

        has_menu_access = bool(menu_url)
        distance = self._haversine_km(origin_lat, origin_lon, lat, lon)
        diet_hints = self._diet_hints(tags=tags, cuisines=cuisines)
        price_tier = self._estimate_price_tier(tags=tags, cuisines=cuisines, amenity=amenity, name=name)

        element_type = str(element.get("type") or "node")
        element_id = str(element.get("id") or "")
        return {
            "id": f"{element_type}:{element_id}",
            "name": name,
            "amenity": amenity,
            "cuisine_tags": cuisines,
            "cuisine_label": ", ".join(cuisines) if cuisines else "unspecified",
            "lat": lat,
            "lon": lon,
            "distance_km": round(distance, 2),
            "website_url": website_url or None,
            "menu_url": menu_url or None,
            "has_menu_access": has_menu_access,
            "menu_access_note": menu_access_note,
            "price_tier": price_tier,
            "diet_hints": diet_hints,
            "source": self.SOURCE_NAME,
        }

    @staticmethod
    def _split_cuisine(value: Any) -> list[str]:
        raw = str(value or "").strip().lower()
        if not raw:
            return []
        parts = re.split(r"[,;]", raw)
        output: list[str] = []
        for part in parts:
            token = re.sub(r"\s+", "_", part.strip())
            if token and token not in output:
                output.append(token)
        return output

    @staticmethod
    def _normalize_url(value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        if text.startswith("//"):
            return f"https:{text}"
        if text.startswith("http://") or text.startswith("https://"):
            return text
        if "." in text and " " not in text:
            return f"https://{text}"
        return ""

    @classmethod
    def _is_menu_platform(cls, url: str) -> bool:
        lowered = url.lower()
        return any(token in lowered for token in cls._MENU_PLATFORM_HINTS)

    @staticmethod
    def _looks_like_menu_path(url: str) -> bool:
        lowered = url.lower()
        return "/menu" in lowered or "menu." in lowered

    @classmethod
    def _diet_hints(cls, tags: dict[str, Any], cuisines: list[str]) -> list[str]:
        hints: list[str] = []
        for key, label in [
            ("diet:vegetarian", "vegetarian"),
            ("diet:vegan", "vegan"),
            ("diet:halal", "halal"),
            ("diet:gluten_free", "gluten-free"),
        ]:
            if str(tags.get(key, "")).strip().lower() in {"yes", "true", "1"}:
                hints.append(label)

        cuisine_set = set(cuisines)
        if cuisine_set & {"vegan", "vegetarian"} and "vegetarian" not in hints:
            hints.append("vegetarian")
        if "halal" in cuisine_set and "halal" not in hints:
            hints.append("halal")
        if "gluten_free" in cuisine_set and "gluten-free" not in hints:
            hints.append("gluten-free")
        return hints

    @classmethod
    def _estimate_price_tier(
        cls,
        tags: dict[str, Any],
        cuisines: list[str],
        amenity: str,
        name: str,
    ) -> str:
        raw_range = str(tags.get("price:range") or tags.get("price") or "").strip().lower()
        if raw_range:
            if "$$$" in raw_range or raw_range in {"3", "4", "expensive", "high"}:
                return "premium"
            if "$" in raw_range and "$$$" not in raw_range:
                return "budget"
            if raw_range in {"cheap", "low", "1"}:
                return "budget"
            if raw_range in {"2", "moderate", "$$"}:
                return "mainstream"

        if amenity in {"fast_food", "food_court"}:
            return "budget"

        lower_name = name.lower()
        if any(token in lower_name for token in ("steak", "bistro", "fine dining", "omakase")):
            return "premium"
        if any(token in lower_name for token in ("deli", "pizza", "taco", "burger", "express")):
            return "budget"

        cuisine_set = set(cuisines)
        if cuisine_set & cls._PREMIUM_CUISINES:
            return "premium"
        if cuisine_set & cls._BUDGET_CUISINES:
            return "budget"

        return "mainstream"

    @staticmethod
    def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        r = 6371.0
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        a = (
            math.sin(dlat / 2) ** 2
            + math.cos(math.radians(lat1))
            * math.cos(math.radians(lat2))
            * math.sin(dlon / 2) ** 2
        )
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return r * c

    @staticmethod
    def _safe_float(value: Any) -> Optional[float]:
        try:
            if value is None:
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

