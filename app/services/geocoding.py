from __future__ import annotations

import json
import time
from typing import Any
from urllib import error, parse, request


class GeocodingService:
    NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
    SOURCE_NAME = "OpenStreetMap Nominatim"
    SOURCE_URL = "https://nominatim.openstreetmap.org/"
    CACHE_TTL_SECONDS = 60 * 30

    def __init__(self, timeout: int = 10):
        self.timeout = timeout
        self._cache: dict[tuple[str, int], tuple[float, list[dict[str, Any]]]] = {}

    def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        text = str(query or "").strip()
        if not text:
            return []

        max_rows = max(1, min(10, int(limit)))
        cache_key = (text.lower(), max_rows)
        now = time.time()
        cached = self._cache.get(cache_key)
        if cached and (now - cached[0]) < self.CACHE_TTL_SECONDS:
            return cached[1]

        params = {
            "q": text,
            "format": "jsonv2",
            "limit": str(max_rows),
            "addressdetails": "1",
        }
        endpoint = f"{self.NOMINATIM_URL}?{parse.urlencode(params)}"
        req = request.Request(
            endpoint,
            headers={
                "User-Agent": "MealPlanAutopilot/1.0 (geocode)",
                "Accept": "application/json",
            },
        )
        try:
            with request.urlopen(req, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (error.HTTPError, error.URLError, TimeoutError, ValueError):
            payload = []

        rows = payload if isinstance(payload, list) else []
        normalized: list[dict[str, Any]] = []
        for row in rows:
            try:
                lat = float(row.get("lat"))
                lon = float(row.get("lon"))
            except (TypeError, ValueError):
                continue
            normalized.append(
                {
                    "id": f"{row.get('osm_type', 'node')}:{row.get('osm_id', '')}",
                    "display_name": row.get("display_name") or "",
                    "lat": lat,
                    "lon": lon,
                    "class": row.get("class") or "",
                    "type": row.get("type") or "",
                    "importance": float(row.get("importance") or 0.0),
                }
            )

        normalized.sort(key=lambda item: item.get("importance", 0.0), reverse=True)
        self._cache[cache_key] = (now, normalized)
        return normalized

