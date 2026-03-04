import json
from urllib import error, parse

from app.models import GeneratedPlan, PantryItem


def _search_food_id(client, query: str) -> int:
    response = client.get(f"/api/foods/search?q={query}")
    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] is True
    assert data["result"]
    return data["result"][0]["id"]


def test_bootstrap_shape(client):
    response = client.get("/api/bootstrap")
    assert response.status_code == 200

    data = response.get_json()
    assert data["ok"] is True
    assert "pantry" in data["result"]
    assert "preferences" in data["result"]
    assert "macro_target" in data["result"]


def test_health_endpoint(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.get_json() == {"ok": True, "service": "meal-plan-autopilot"}


def test_food_search_requires_query(client):
    response = client.get("/api/foods/search")
    assert response.status_code == 400
    assert "Missing required query" in response.get_json()["error"]


def test_food_search_returns_seed_results(client):
    response = client.get("/api/foods/search?q=chicken")
    assert response.status_code == 200
    payload = response.get_json()
    rows = payload["result"]
    assert rows
    assert any("chicken" in row["name"] for row in rows)
    assert payload["metadata"]["usda_status"] in {"ok", "disabled"}


def test_food_search_returns_pork_results(client):
    response = client.get("/api/foods/search?q=pork")
    assert response.status_code == 200
    rows = response.get_json()["result"]
    assert rows
    assert any("pork" in row["name"] for row in rows)


def test_food_search_limit_and_clamping(client):
    response = client.get("/api/foods/search?q=chicken&limit=1")
    assert response.status_code == 200
    data = response.get_json()
    assert len(data["result"]) == 1
    assert data["metadata"]["limit"] == 1
    assert data["metadata"]["page"] == 1

    response_max = client.get("/api/foods/search?q=chicken&limit=999&page=999")
    assert response_max.status_code == 200
    assert response_max.get_json()["metadata"]["limit"] == 50
    assert response_max.get_json()["metadata"]["page"] == 50


def test_food_search_rejects_non_integer_limit(client):
    response = client.get("/api/foods/search?q=chicken&limit=abc")
    assert response.status_code == 400
    assert "must be an integer" in response.get_json()["error"].lower()

    response = client.get("/api/foods/search?q=chicken&page=abc")
    assert response.status_code == 400
    assert "must be an integer" in response.get_json()["error"].lower()


def test_location_geocode_requires_query(client):
    response = client.post("/api/location/geocode", json={})
    assert response.status_code == 400
    assert "missing required field" in response.get_json()["error"].lower()


def test_location_geocode_returns_matches(client, monkeypatch):
    payload = [
        {
            "osm_type": "node",
            "osm_id": 123,
            "display_name": "1 Market St, San Francisco, California, United States",
            "lat": "37.7948",
            "lon": "-122.3944",
            "class": "place",
            "type": "house",
            "importance": 0.75,
        }
    ]

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(payload).encode("utf-8")

    monkeypatch.setattr("app.services.geocoding.request.urlopen", lambda *args, **kwargs: FakeResponse())

    response = client.post("/api/location/geocode", json={"query": "1 market st san francisco", "limit": 3})
    assert response.status_code == 200
    result = response.get_json()["result"]
    assert result["matches"]
    first = result["matches"][0]
    assert first["display_name"]
    assert first["id"] == "node:123"
    assert first["lat"] == 37.7948
    assert first["lon"] == -122.3944


def test_interactions_check_validates_input(client):
    response = client.post("/api/interactions/check", json={"items": ["warfarin"]})
    assert response.status_code == 400
    assert "at least two" in response.get_json()["error"].lower()

    response = client.post("/api/interactions/check", json={})
    assert response.status_code == 400
    assert "at least two" in response.get_json()["error"].lower()


def test_interactions_check_returns_pair_signal(client, monkeypatch):
    warfarin_payload = {
        "meta": {"last_updated": "2026-02-07"},
        "results": [
            {
                "set_id": "set-warfarin",
                "effective_time": "20250617",
                "drug_interactions": [
                    "Concomitant use with ibuprofen may increase bleeding risk in some patients."
                ],
                "dosage_and_administration": [
                    "Take with food when needed for stomach upset."
                ],
                "openfda": {
                    "generic_name": ["WARFARIN"],
                    "brand_name": ["Warfarin Sodium"],
                    "product_type": ["HUMAN PRESCRIPTION DRUG"],
                },
            }
        ],
    }
    ibuprofen_payload = {
        "meta": {"last_updated": "2026-02-07"},
        "results": [
            {
                "set_id": "set-ibuprofen",
                "effective_time": "20250401",
                "drug_interactions": [],
                "openfda": {
                    "generic_name": ["IBUPROFEN"],
                    "brand_name": ["Ibuprofen"],
                    "product_type": ["HUMAN OTC DRUG"],
                },
            }
        ],
    }

    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(self.payload).encode("utf-8")

    def fake_urlopen(url, timeout=0):
        parsed = parse.urlparse(url)
        query = parse.parse_qs(parsed.query).get("search", [""])[0].lower()
        if "warfarin" in query:
            return FakeResponse(warfarin_payload)
        if "ibuprofen" in query:
            return FakeResponse(ibuprofen_payload)
        raise error.HTTPError(url=url, code=404, msg="Not Found", hdrs=None, fp=None)

    monkeypatch.setattr("app.services.drug_interactions.request.urlopen", fake_urlopen)

    response = client.post(
        "/api/interactions/check",
        json={"items": ["warfarin", "ibuprofen"]},
    )
    assert response.status_code == 200
    payload = response.get_json()["result"]
    assert payload["source"]["name"] == "FDA openFDA Drug Label API"
    assert payload["pair_signals"]
    assert payload["diet_effects"]
    first = payload["pair_signals"][0]
    assert first["confidence"] == "label_mention"
    assert "warfarin" in " ".join(first["pair"]).lower()
    assert "ibuprofen" in " ".join(first["pair"]).lower()


def test_shopping_recommend_validates_input(client):
    response = client.post("/api/shopping/recommend", json={})
    assert response.status_code == 400
    assert "at least one" in response.get_json()["error"].lower()


def test_shopping_recommend_returns_budget_options(client):
    response = client.post(
        "/api/shopping/recommend",
        json={
            "items": [
                "pork loin 1200 g",
                {"food": "rice cooked", "quantity": 1000, "unit": "g"},
            ],
            "budget_usd": 70,
            "tradeoff": "budget_first",
            "goal": "balanced",
            "diet_tags": ["halal"],
            "allergens": ["peanut"],
            "dislikes": [],
        },
    )
    assert response.status_code == 200
    payload = response.get_json()["result"]

    assert payload["options"]
    assert payload["selected_option"]["strategy"] == "budget_first"
    assert payload["stores"]
    assert payload["stores"][0]["source"] == "estimated"
    assert payload["notes"]

    pork_row = next((row for row in payload["items"] if row["food"] == "pork loin"), None)
    assert pork_row is not None
    assert pork_row["effective_food"] == "chicken breast"
    assert pork_row["constraint_conflict"] is True


def test_restaurants_recommend_requires_location(client):
    response = client.post("/api/restaurants/recommend", json={})
    assert response.status_code == 400
    assert "location is required" in response.get_json()["error"].lower()


def test_restaurants_recommend_returns_ranked_results(client, monkeypatch):
    def fake_search(self, latitude, longitude, radius_km=5.0, limit=80):
        assert latitude == 37.78
        assert longitude == -122.42
        return [
            {
                "id": "node:11",
                "name": "Harbor Green Kitchen",
                "amenity": "restaurant",
                "cuisine_tags": ["salad", "mediterranean"],
                "cuisine_label": "salad, mediterranean",
                "distance_km": 0.9,
                "price_tier": "mainstream",
                "website_url": "https://harborgreen.example",
                "menu_url": "https://harborgreen.example/menu",
                "has_menu_access": True,
                "menu_access_note": "explicit_osm_menu_tag",
                "diet_hints": ["vegetarian"],
                "source": "mock",
            },
            {
                "id": "node:12",
                "name": "Downtown Steak Spot",
                "amenity": "restaurant",
                "cuisine_tags": ["steak_house"],
                "cuisine_label": "steak_house",
                "distance_km": 1.3,
                "price_tier": "premium",
                "website_url": "https://steakspot.example",
                "menu_url": None,
                "has_menu_access": False,
                "menu_access_note": "none",
                "diet_hints": [],
                "source": "mock",
            },
        ]

    monkeypatch.setattr(
        "app.services.restaurant_locator.RestaurantLocatorService.search_restaurants",
        fake_search,
    )

    response = client.post(
        "/api/restaurants/recommend",
        json={
            "location": {"latitude": 37.78, "longitude": -122.42},
            "budget_usd": 34,
            "goal": "fat_loss",
            "tradeoff": "balanced",
            "diet_tags": ["vegetarian"],
        },
    )
    assert response.status_code == 200
    payload = response.get_json()["result"]
    assert payload["restaurants"]
    assert payload["highlights"]
    assert payload["visible_default_count"] == 1
    assert payload["hidden_no_menu_count"] == 1
    assert payload["restaurants"][0]["name"] == "Harbor Green Kitchen"
    assert payload["restaurants"][0]["has_menu_access"] is True


def test_pantry_crud_flow(client, db_session):
    food_id = _search_food_id(client, "chicken breast")

    create = client.post(
        "/api/pantry",
        json={"food_id": food_id, "quantity": 1, "unit": "kg"},
    )
    assert create.status_code == 201
    created = create.get_json()["result"]
    assert created["quantity_grams"] == 1000.0

    create_again = client.post(
        "/api/pantry",
        json={"food_id": food_id, "quantity": 500, "unit": "g"},
    )
    assert create_again.status_code == 201
    updated_same = create_again.get_json()["result"]
    assert updated_same["quantity_grams"] == 1500.0
    assert updated_same["display_unit"] == "g"

    pantry = client.get("/api/pantry")
    assert pantry.status_code == 200
    rows = pantry.get_json()["result"]
    assert len(rows) == 1

    pantry_id = rows[0]["id"]
    update = client.put(
        f"/api/pantry/{pantry_id}",
        json={"quantity": 2, "unit": "lb"},
    )
    assert update.status_code == 200
    after_update = update.get_json()["result"]
    assert after_update["display_quantity"] == 2.0
    assert after_update["display_unit"] == "lb"
    assert after_update["quantity_grams"] == 907.18

    delete = client.delete(f"/api/pantry/{pantry_id}")
    assert delete.status_code == 200
    assert db_session.query(PantryItem).count() == 0


def test_pantry_validations(client):
    response = client.post(
        "/api/pantry",
        json={"food_name": "custom item", "quantity": 0, "unit": "g"},
    )
    assert response.status_code == 400
    assert "greater than zero" in response.get_json()["error"].lower()

    response = client.post(
        "/api/pantry",
        json={"food_name": "custom item", "quantity": 10, "unit": "stone"},
    )
    assert response.status_code == 400
    assert "unsupported unit" in response.get_json()["error"].lower()

    response = client.post(
        "/api/pantry",
        json={"food_id": 999999, "quantity": 10, "unit": "g"},
    )
    assert response.status_code == 400
    assert "not found" in response.get_json()["error"].lower()

    response = client.post(
        "/api/pantry",
        json={"quantity": 10, "unit": "g"},
    )
    assert response.status_code == 400
    assert "provide either food_id or food_name" in response.get_json()["error"].lower()

    response = client.put("/api/pantry/999999", json={"quantity": 10, "unit": "g"})
    assert response.status_code == 404

    response = client.delete("/api/pantry/999999")
    assert response.status_code == 404


def test_manual_food_creation_and_lookup(client):
    create = client.post(
        "/api/pantry",
        json={
            "food_name": "Dragonfruit Powder",
            "quantity": 100,
            "unit": "g",
            "calories": 350,
            "protein": 12,
            "carbs": 64,
            "fat": 4,
        },
    )
    assert create.status_code == 201
    assert create.get_json()["result"]["food"] == "dragonfruit powder"

    lookup = client.get("/api/foods/search?q=dragonfruit")
    assert lookup.status_code == 200
    results = lookup.get_json()["result"]
    assert any(row["name"] == "dragonfruit powder" for row in results)


def test_preferences_get_and_update(client):
    get_before = client.get("/api/preferences")
    assert get_before.status_code == 200
    assert get_before.get_json()["result"] == {
        "diet_tags": [],
        "allergens": [],
        "dislikes": [],
    }

    update = client.put(
        "/api/preferences",
        json={
            "diet_tags": [" Vegetarian ", "halal", "vegetarian"],
            "allergens": "peanut, shellfish, peanut",
            "dislikes": ["mushroom", " celery "],
        },
    )
    assert update.status_code == 200
    assert update.get_json()["result"] == {
        "diet_tags": ["vegetarian", "halal"],
        "allergens": ["peanut", "shellfish"],
        "dislikes": ["mushroom", "celery"],
    }


def test_macro_target_get_update_and_validation(client):
    get_before = client.get("/api/macro-target")
    assert get_before.status_code == 200
    assert get_before.get_json()["result"]["calories"] == 2000.0

    update = client.put(
        "/api/macro-target",
        json={
            "calories": 2300,
            "protein_min": 140,
            "protein_max": 190,
            "carbs_min": 200,
            "carbs_max": 280,
            "fat_min": 55,
            "fat_max": 85,
        },
    )
    assert update.status_code == 200
    result = update.get_json()["result"]
    assert result["calories"] == 2300.0
    assert result["protein_min"] == 140.0
    assert result["fat_max"] == 85.0

    invalid = client.put("/api/macro-target", json={"calories": "abc"})
    assert invalid.status_code == 400
    assert "must be numeric" in invalid.get_json()["error"].lower()


def test_recipes_endpoint_shape(client):
    response = client.get("/api/recipes")
    assert response.status_code == 200
    rows = response.get_json()["result"]
    assert len(rows) >= 8

    sample = rows[0]
    assert "macros_per_serving" in sample
    assert "ingredients" in sample
    assert sample["ingredients"]


def test_generate_plan_happy_path(client, db_session):
    food_id = _search_food_id(client, "rice")
    client.post("/api/pantry", json={"food_id": food_id, "quantity": 1000, "unit": "g"})

    response = client.post("/api/meal-plan/generate", json={"days": 5})
    assert response.status_code == 200

    data = response.get_json()["result"]
    assert len(data["plan"]) == 5
    assert len(data["macro_summary"]) == 5
    assert "shopping_list" in data
    assert data["metadata"]["generated_days"] == 5
    assert data["metadata"]["candidate_count"] >= 1

    first = data["plan"][0]
    assert first["day"] == 1
    assert "Selected" in first["explanation"]
    assert set(first["macros"].keys()) == {"calories", "protein", "carbs", "fat"}

    assert db_session.query(GeneratedPlan).count() == 1


def test_generate_plan_day_bounds_and_invalid_input(client):
    invalid = client.post("/api/meal-plan/generate", json={"days": "bad"})
    assert invalid.status_code == 400

    clamped_min = client.post("/api/meal-plan/generate", json={"days": 0})
    assert clamped_min.status_code == 200
    assert clamped_min.get_json()["result"]["metadata"]["generated_days"] == 1

    clamped_max = client.post("/api/meal-plan/generate", json={"days": 99})
    assert clamped_max.status_code == 200
    assert clamped_max.get_json()["result"]["metadata"]["generated_days"] == 14


def test_generate_plan_returns_400_when_no_candidate_matches(client):
    pref = client.put("/api/preferences", json={"diet_tags": "nonexistent-diet-tag"})
    assert pref.status_code == 200

    response = client.post("/api/meal-plan/generate", json={"days": 3})
    assert response.status_code == 400
    assert "no recipes match" in response.get_json()["error"].lower()


def test_ui_route_contains_core_feature_elements(client):
    response = client.get("/")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    for element_id in [
        'id="foodQuery"',
        'id="foodResults"',
        'id="addPantryBtn"',
        'id="savePrefsBtn"',
        'id="saveMacroBtn"',
        'id="generateBtn"',
        'id="planWrap"',
        'id="insightWrap"',
        'id="macroCompass"',
        'id="visualReel"',
        'id="coachWrap"',
        'id="interactionItems"',
        'id="checkInteractionsBtn"',
        'id="interactionSignals"',
        'id="runSmartShoppingBtn"',
        'id="smartShoppingItems"',
        'id="smartShoppingOptions"',
        'id="smartShoppingSummary"',
        'id="smartAddress"',
        'id="smartUseAddressBtn"',
        'id="runRestaurantSearchBtn"',
        'id="restaurantResultsWrap"',
        'id="restaurantShowNoMenu"',
        'id="restaurantHighlightsWrap"',
        'id="restaurantAddress"',
        'id="restaurantUseAddressBtn"',
        'id="macroTrendWrap"',
        'id="refreshStreamBtn"',
        'id="burnDownWrap"',
        'id="shuffleDayBtn"',
        'id="autoBalanceBtn"',
        'id="themeWrap"',
        'id="shoppingWrap"',
        'id="macroWrap"',
    ]:
        assert element_id in html

    assert "FOOD_IMAGE_WHITELIST" in html
    assert "RECIPE_IMAGE_WHITELIST" in html
    assert 'data-step="4"' in html
    assert 'data-step="5"' in html
    assert 'data-step="6"' in html
    assert 'data-step-panel="4"' in html
    assert 'data-step-panel="5"' in html
    assert 'data-step-panel="6"' in html
    assert "Open Medications & Supplements" in html
    assert "Open Smart Shopping" in html
    assert "Open Restaurant Finder" in html
    assert "Smart Shopping" in html
    assert "Restaurant Finder" in html
    assert "Medications & Supplements" in html
    assert 'id="dietEffects"' in html
    assert "fetchWikipediaThumbnail" not in html
    assert "fetchCommonsThumbnail" not in html
    assert "/api/location/geocode" in html
    assert "informational only" in html.lower()
