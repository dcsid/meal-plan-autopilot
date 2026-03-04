UNIT_TO_GRAMS = {
    "g": 1.0,
    "gram": 1.0,
    "grams": 1.0,
    "kg": 1000.0,
    "oz": 28.3495,
    "ounce": 28.3495,
    "ounces": 28.3495,
    "lb": 453.592,
    "lbs": 453.592,
    "pound": 453.592,
    "pounds": 453.592,
    "ml": 1.0,
    "l": 1000.0,
    "cup": 240.0,
    "cups": 240.0,
    "tbsp": 15.0,
    "tsp": 5.0,
}


def to_grams(quantity: float, unit: str) -> float:
    normalized = (unit or "g").strip().lower()
    if normalized not in UNIT_TO_GRAMS:
        raise ValueError(f"Unsupported unit '{unit}'. Supported: {', '.join(sorted(UNIT_TO_GRAMS))}")

    grams = float(quantity) * UNIT_TO_GRAMS[normalized]
    if grams <= 0:
        raise ValueError("Quantity must be greater than zero.")
    return round(grams, 2)
