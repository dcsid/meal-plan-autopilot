from sqlalchemy import func

from ..models import FoodItem, PantryItem


DEMO_PANTRY_ITEMS = [
    {"food": "chicken breast", "grams": 900.0},
    {"food": "rice cooked", "grams": 1200.0},
    {"food": "broccoli", "grams": 600.0},
    {"food": "olive oil", "grams": 120.0},
    {"food": "greek yogurt", "grams": 500.0},
]


def ensure_demo_pantry(session) -> dict:
    if session.query(PantryItem).count() > 0:
        return {"demo_pantry_seeded": 0}

    created = 0
    for row in DEMO_PANTRY_ITEMS:
        food_name = row["food"].strip().lower()
        food = session.query(FoodItem).filter(func.lower(FoodItem.name) == food_name).first()
        if not food:
            continue

        pantry_item = PantryItem(
            food_id=food.id,
            quantity_grams=float(row["grams"]),
            display_quantity=float(row["grams"]),
            display_unit="g",
        )
        session.add(pantry_item)
        created += 1

    if created:
        session.commit()

    return {"demo_pantry_seeded": created}
