import json
from urllib import error

import pytest

from app.models import FoodItem, MacroTarget, Recipe, RecipeIngredient, UserPreferences
from app.services.drug_interactions import DrugInteractionService
from app.services.food_lookup import FoodLookupService
from app.services.geocoding import GeocodingService
from app.services.demo_data import ensure_demo_pantry
from app.services.recipe_filter import (
    coverage_score,
    filter_recipes,
    macro_fit_error,
    pantry_usage_percent,
    score_recipe,
)
from app.services.restaurant_finder import RestaurantFinderService
from app.services.seed_data import ensure_seed_data
from app.services.shopping_list import build_shopping_list
from app.services.smart_shopping import SmartShoppingService
from app.services.unit_conversion import to_grams


def test_to_grams_valid_units():
    assert to_grams(1, "kg") == 1000.0
    assert to_grams(2, "lb") == 907.18
    assert to_grams(1.5, "cup") == 360.0
    assert to_grams(3, "TBSP") == 45.0


@pytest.mark.parametrize(
    "quantity,unit",
    [
        (0, "g"),
        (-1, "g"),
        (10, "stone"),
    ],
)
def test_to_grams_rejects_invalid_input(quantity, unit):
    with pytest.raises(ValueError):
        to_grams(quantity, unit)


def test_seed_data_idempotent(db_session):
    ensure_seed_data(db_session)

    first_counts = {
        "foods": db_session.query(FoodItem).count(),
        "recipes": db_session.query(Recipe).count(),
        "recipe_ingredients": db_session.query(RecipeIngredient).count(),
    }

    ensure_seed_data(db_session)

    second_counts = {
        "foods": db_session.query(FoodItem).count(),
        "recipes": db_session.query(Recipe).count(),
        "recipe_ingredients": db_session.query(RecipeIngredient).count(),
    }

    assert second_counts == first_counts


def test_ensure_demo_pantry_seeds_once(db_session):
    seeded = ensure_demo_pantry(db_session)
    assert seeded["demo_pantry_seeded"] >= 1

    seeded_again = ensure_demo_pantry(db_session)
    assert seeded_again["demo_pantry_seeded"] == 0


def test_recipe_filter_and_scoring(db_session):
    recipes = db_session.query(Recipe).all()
    prefs = db_session.get(UserPreferences, 1)

    prefs.diet_tags_csv = "vegetarian"
    prefs.allergens_csv = "shrimp"
    prefs.dislikes_csv = ""
    db_session.commit()

    filtered = filter_recipes(recipes, prefs)
    assert filtered
    assert all("vegetarian" in recipe.diet_tags for recipe in filtered)
    assert all("shrimp" not in " ".join(link.food.name for link in recipe.ingredients).lower() for recipe in filtered)

    recipe = filtered[0]
    pantry_map = {link.food_id: link.grams for link in recipe.ingredients}
    coverage = coverage_score(recipe, pantry_map)
    usage = pantry_usage_percent(recipe, pantry_map)
    target = db_session.get(MacroTarget, 1)
    error_value = macro_fit_error(recipe, target)
    score, scored_coverage, scored_error = score_recipe(
        recipe,
        pantry_map,
        target,
        variety_bonus=1.0,
    )

    assert coverage == 1.0
    assert usage == 100.0
    assert error_value >= 0
    assert scored_coverage == 1.0
    assert scored_error >= 0
    assert isinstance(score, float)


def test_shopping_list_aggregates_duplicate_ingredients(db_session):
    recipe_a = db_session.query(Recipe).filter_by(name="Lemon Chicken Rice Bowl").first()
    recipe_b = db_session.query(Recipe).filter_by(name="Beef Fajita Bowl").first()
    assert recipe_a is not None
    assert recipe_b is not None

    shopping = build_shopping_list([recipe_a, recipe_b], pantry_items=[])
    names = [row["food"] for row in shopping]
    assert "rice cooked" in names

    rice_row = next(row for row in shopping if row["food"] == "rice cooked")
    rice_required = 0.0
    for recipe in [recipe_a, recipe_b]:
        for link in recipe.ingredients:
            if link.food.name == "rice cooked":
                rice_required += link.grams

    assert rice_row["required_grams"] == round(rice_required, 2)
    assert rice_row["missing_grams"] == round(rice_required, 2)


def test_food_lookup_local_search(db_session):
    service = FoodLookupService(db_session, api_key=None)
    results = service.search_foods("chicken", limit=5)
    assert results
    assert any("chicken" in row["name"] for row in results)


def test_food_lookup_tokenized_local_search(db_session):
    service = FoodLookupService(db_session, api_key=None)
    results = service.search_foods("pork raw", limit=10)
    assert results
    assert any("pork" in row["name"] for row in results)


def test_food_lookup_network_error_returns_local(monkeypatch, db_session):
    def boom(*args, **kwargs):
        raise error.URLError("network down")

    monkeypatch.setattr("app.services.food_lookup.request.urlopen", boom)

    service = FoodLookupService(db_session, api_key="demo")
    results = service.search_foods("chicken", limit=5)
    assert results
    assert all("id" in row for row in results)
    assert service.last_remote_error == "unavailable"


def test_food_lookup_rate_limit_error_sets_status(monkeypatch, db_session):
    def boom(*args, **kwargs):
        raise error.HTTPError(
            url="https://api.nal.usda.gov/fdc/v1/foods/search",
            code=429,
            msg="Too Many Requests",
            hdrs=None,
            fp=None,
        )

    monkeypatch.setattr("app.services.food_lookup.request.urlopen", boom)

    service = FoodLookupService(db_session, api_key="demo")
    results = service.search_foods("sardine", limit=5)
    assert isinstance(results, list)
    assert service.last_remote_error == "rate_limited"


def test_food_lookup_usda_parse_and_upsert(monkeypatch, db_session):
    payload = {
        "foods": [
            {
                "description": "Cod Fillet Raw",
                "fdcId": 999123,
                "foodNutrients": [
                    {"nutrientName": "Energy", "value": 82},
                    {"nutrientName": "Protein", "value": 17.8},
                    {"nutrientName": "Carbohydrate, by difference", "value": 0.0},
                    {"nutrientName": "Total lipid (fat)", "value": 0.7},
                ],
            }
        ]
    }

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(payload).encode("utf-8")

    monkeypatch.setattr(
        "app.services.food_lookup.request.urlopen",
        lambda *args, **kwargs: FakeResponse(),
    )

    service = FoodLookupService(db_session, api_key="demo")
    results = service.search_foods("cod fillet", limit=5)

    assert results
    match = next((row for row in results if row["fdc_id"] == "999123"), None)
    assert match is not None
    assert match["source"] == "usda"

    db_row = db_session.query(FoodItem).filter_by(fdc_id="999123").first()
    assert db_row is not None
    assert db_row.name == "cod fillet raw"
    assert db_row.protein_per_100g == 17.8


def test_food_lookup_usda_label_nutrients_fallback(monkeypatch, db_session):
    payload = {
        "foods": [
            {
                "description": "Protein Snack Bar",
                "fdcId": 778899,
                "foodNutrients": [],
                "labelNutrients": {
                    "calories": {"value": 210},
                    "protein": {"value": 20},
                    "carbohydrates": {"value": 23},
                    "fat": {"value": 7},
                },
            }
        ]
    }

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(payload).encode("utf-8")

    monkeypatch.setattr(
        "app.services.food_lookup.request.urlopen",
        lambda *args, **kwargs: FakeResponse(),
    )

    service = FoodLookupService(db_session, api_key="demo")
    results = service.search_foods("protein bar", limit=10)

    match = next((row for row in results if row["fdc_id"] == "778899"), None)
    assert match is not None
    assert match["nutrients_per_100g"]["protein"] == 20.0
    assert match["nutrients_per_100g"]["carbs"] == 23.0
    assert match["nutrients_per_100g"]["fat"] == 7.0


def test_drug_interaction_service_detects_pair_mentions(monkeypatch):
    payloads = {
        "warfarin": {
            "meta": {"last_updated": "2026-02-07"},
            "results": [
                {
                    "set_id": "set-warfarin",
                    "effective_time": "20250617",
                    "drug_interactions": [
                        "Concomitant ibuprofen use may increase bleeding risk."
                    ],
                    "dosage_and_administration": [
                        "Administer with food if gastrointestinal upset occurs."
                    ],
                    "warnings_and_precautions": [
                        "Alcohol may increase bleeding risk."
                    ],
                    "openfda": {
                        "generic_name": ["WARFARIN"],
                        "brand_name": ["Warfarin Sodium"],
                        "product_type": ["HUMAN PRESCRIPTION DRUG"],
                    },
                }
            ],
        },
        "ibuprofen": {
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
        },
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
        lowered = str(url).lower()
        if "warfarin" in lowered:
            return FakeResponse(payloads["warfarin"])
        if "ibuprofen" in lowered:
            return FakeResponse(payloads["ibuprofen"])
        raise error.HTTPError(url=url, code=404, msg="Not Found", hdrs=None, fp=None)

    monkeypatch.setattr("app.services.drug_interactions.request.urlopen", fake_urlopen)

    service = DrugInteractionService()
    result = service.check_interactions(["warfarin", "ibuprofen"])
    assert result["pair_signals"]
    assert result["diet_effects"]
    assert result["source"]["status"] == "ok"
    assert result["source"]["last_updated"] == "2026-02-07"
    warfarin_effects = next(row for row in result["diet_effects"] if row["item"] == "warfarin")
    topics = {signal["topic"] for signal in warfarin_effects["signals"]}
    assert "meal timing" in topics
    assert "alcohol" in topics


def test_drug_interaction_service_handles_unresolved_and_supplements(monkeypatch):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps({"meta": {"last_updated": "2026-02-07"}, "results": []}).encode("utf-8")

    monkeypatch.setattr("app.services.drug_interactions.request.urlopen", lambda *args, **kwargs: FakeResponse())

    service = DrugInteractionService()
    result = service.check_interactions(["vitamin d", "ashwagandha"])
    assert not result["pair_signals"]
    assert set(result["unresolved_items"]) == {"vitamin d", "ashwagandha"}
    assert any("supplement evidence can be limited" in note.lower() for note in result["notes"])


def test_smart_shopping_rejects_missing_items():
    service = SmartShoppingService()
    with pytest.raises(ValueError):
        service.recommend(payload={}, preferences=None)


def test_smart_shopping_applies_constraints_and_builds_options(db_session):
    service = SmartShoppingService()
    prefs = db_session.get(UserPreferences, 1)
    prefs.diet_tags_csv = "halal,gluten-free"
    db_session.commit()

    result = service.recommend(
        payload={
            "items": [
                "pork loin 1200 g",
                {"food": "whole wheat pasta", "quantity": 1.1, "unit": "kg"},
                {"food": "rice cooked", "quantity": 900, "unit": "g"},
            ],
            "budget_usd": 95,
            "goal": "high_protein",
            "tradeoff": "budget_first",
        },
        preferences=prefs,
    )

    assert result["options"]
    assert result["selected_option"]["strategy"] == "budget_first"
    assert result["stores"]
    assert result["stores"][0]["source"] == "estimated"

    pork_row = next((row for row in result["items"] if row["food"] == "pork loin"), None)
    assert pork_row is not None
    assert pork_row["effective_food"] == "chicken breast"
    assert pork_row["constraint_conflict"] is True

    pasta_row = next((row for row in result["items"] if row["food"] == "whole wheat pasta"), None)
    assert pasta_row is not None
    assert pasta_row["effective_food"] == "rice cooked"
    assert pasta_row["constraint_conflict"] is True


def test_smart_shopping_uses_locator_when_location_is_provided():
    class FakeLocator:
        SOURCE_NAME = "Fake locator"
        SOURCE_URL = "https://example.test/locator"

        def search_stores(self, latitude, longitude, radius_km=5.0, limit=20):
            assert latitude == 37.78
            assert longitude == -122.41
            assert radius_km == 6.0
            return [
                {
                    "id": "fake:1",
                    "name": "Corner Market",
                    "display_name": "Corner Market",
                    "type": "supermarket",
                    "category": "shop",
                    "lat": 37.781,
                    "lon": -122.409,
                    "distance_km": 0.4,
                    "price_tier": "mainstream",
                    "price_multiplier": 1.0,
                    "diet_fit_score": 0.8,
                    "source": "Fake locator",
                }
            ]

    service = SmartShoppingService(locator=FakeLocator())
    result = service.recommend(
        payload={
            "items": ["chicken breast 900 g", "broccoli 500 g"],
            "budget_usd": 45,
            "radius_km": 6.0,
            "location": {"latitude": 37.78, "longitude": -122.41},
        },
        preferences=None,
    )

    assert result["stores"]
    assert result["stores"][0]["name"] == "Corner Market"
    assert result["source"]["store_locator"] == "Fake locator"


def test_restaurant_finder_requires_location():
    service = RestaurantFinderService()
    with pytest.raises(ValueError):
        service.recommend(payload={"budget_usd": 30}, preferences=None)


def test_restaurant_finder_ranks_and_tracks_menu_visibility(db_session):
    class FakeLocator:
        SOURCE_NAME = "Fake restaurant locator"
        SOURCE_URL = "https://example.test/restaurants"

        def search_restaurants(self, latitude, longitude, radius_km=5.0, limit=80):
            assert latitude == 37.78
            assert longitude == -122.42
            return [
                {
                    "id": "node:1",
                    "name": "Green Bowl Kitchen",
                    "amenity": "restaurant",
                    "cuisine_tags": ["salad", "mediterranean"],
                    "cuisine_label": "salad, mediterranean",
                    "distance_km": 0.7,
                    "price_tier": "mainstream",
                    "website_url": "https://greenbowl.example",
                    "menu_url": "https://greenbowl.example/menu",
                    "has_menu_access": True,
                    "menu_access_note": "explicit_osm_menu_tag",
                    "diet_hints": ["vegetarian"],
                    "source": "Fake restaurant locator",
                },
                {
                    "id": "node:2",
                    "name": "Downtown Grill House",
                    "amenity": "restaurant",
                    "cuisine_tags": ["steak_house"],
                    "cuisine_label": "steak_house",
                    "distance_km": 1.2,
                    "price_tier": "premium",
                    "website_url": "https://grillhouse.example",
                    "menu_url": None,
                    "has_menu_access": False,
                    "menu_access_note": "none",
                    "diet_hints": [],
                    "source": "Fake restaurant locator",
                },
            ]

    prefs = db_session.get(UserPreferences, 1)
    prefs.diet_tags_csv = "vegetarian"
    db_session.commit()

    service = RestaurantFinderService(locator=FakeLocator())
    result = service.recommend(
        payload={
            "location": {"latitude": 37.78, "longitude": -122.42},
            "budget_usd": 32,
            "tradeoff": "balanced",
            "goal": "fat_loss",
        },
        preferences=prefs,
    )

    assert result["restaurants"]
    assert result["visible_default_count"] == 1
    assert result["hidden_no_menu_count"] == 1
    assert result["source"]["locator_name"] == "Fake restaurant locator"
    assert result["highlights"]

    top = result["restaurants"][0]
    assert top["name"] == "Green Bowl Kitchen"
    assert top["has_menu_access"] is True


def test_geocoding_service_parses_nominatim_payload(monkeypatch):
    payload = [
        {
            "osm_type": "way",
            "osm_id": 888,
            "display_name": "1600 Amphitheatre Parkway, Mountain View, California, United States",
            "lat": "37.4220",
            "lon": "-122.0841",
            "class": "building",
            "type": "commercial",
            "importance": 0.82,
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

    service = GeocodingService()
    rows = service.search("1600 amphitheatre parkway", limit=5)
    assert rows
    assert rows[0]["id"] == "way:888"
    assert rows[0]["lat"] == 37.422
    assert rows[0]["lon"] == -122.0841


def test_geocoding_service_handles_network_error(monkeypatch):
    monkeypatch.setattr("app.services.geocoding.request.urlopen", lambda *args, **kwargs: (_ for _ in ()).throw(error.URLError("offline")))
    service = GeocodingService()
    rows = service.search("new york, ny", limit=3)
    assert rows == []
