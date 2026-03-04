from datetime import datetime

from .extensions import db


class FoodItem(db.Model):
    __tablename__ = "food_items"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False, unique=True, index=True)
    fdc_id = db.Column(db.String(32), nullable=True, unique=True, index=True)
    calories_per_100g = db.Column(db.Float, nullable=False, default=0.0)
    protein_per_100g = db.Column(db.Float, nullable=False, default=0.0)
    carbs_per_100g = db.Column(db.Float, nullable=False, default=0.0)
    fat_per_100g = db.Column(db.Float, nullable=False, default=0.0)
    source = db.Column(db.String(32), nullable=False, default="manual")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    pantry_items = db.relationship("PantryItem", back_populates="food", cascade="all, delete-orphan")
    recipe_links = db.relationship("RecipeIngredient", back_populates="food", cascade="all, delete-orphan")


class PantryItem(db.Model):
    __tablename__ = "pantry_items"

    id = db.Column(db.Integer, primary_key=True)
    food_id = db.Column(db.Integer, db.ForeignKey("food_items.id"), nullable=False, index=True)
    quantity_grams = db.Column(db.Float, nullable=False)
    display_quantity = db.Column(db.Float, nullable=False)
    display_unit = db.Column(db.String(16), nullable=False, default="g")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    food = db.relationship("FoodItem", back_populates="pantry_items")


class Recipe(db.Model):
    __tablename__ = "recipes"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False, unique=True)
    servings = db.Column(db.Integer, nullable=False, default=1)
    diet_tags_csv = db.Column(db.Text, nullable=False, default="")
    main_protein = db.Column(db.String(64), nullable=True)
    instructions = db.Column(db.Text, nullable=True)

    calories_per_serving = db.Column(db.Float, nullable=False, default=0.0)
    protein_per_serving = db.Column(db.Float, nullable=False, default=0.0)
    carbs_per_serving = db.Column(db.Float, nullable=False, default=0.0)
    fat_per_serving = db.Column(db.Float, nullable=False, default=0.0)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    ingredients = db.relationship(
        "RecipeIngredient",
        back_populates="recipe",
        cascade="all, delete-orphan",
        lazy="joined",
    )

    @property
    def diet_tags(self) -> list[str]:
        return [tag.strip().lower() for tag in self.diet_tags_csv.split(",") if tag.strip()]


class RecipeIngredient(db.Model):
    __tablename__ = "recipe_ingredients"

    id = db.Column(db.Integer, primary_key=True)
    recipe_id = db.Column(db.Integer, db.ForeignKey("recipes.id"), nullable=False, index=True)
    food_id = db.Column(db.Integer, db.ForeignKey("food_items.id"), nullable=False, index=True)
    grams = db.Column(db.Float, nullable=False)

    recipe = db.relationship("Recipe", back_populates="ingredients")
    food = db.relationship("FoodItem", back_populates="recipe_links")


class UserPreferences(db.Model):
    __tablename__ = "user_preferences"

    id = db.Column(db.Integer, primary_key=True)
    diet_tags_csv = db.Column(db.Text, nullable=False, default="")
    allergens_csv = db.Column(db.Text, nullable=False, default="")
    dislikes_csv = db.Column(db.Text, nullable=False, default="")

    @property
    def diet_tags(self) -> list[str]:
        return _csv_to_list(self.diet_tags_csv)

    @property
    def allergens(self) -> list[str]:
        return _csv_to_list(self.allergens_csv)

    @property
    def dislikes(self) -> list[str]:
        return _csv_to_list(self.dislikes_csv)


class MacroTarget(db.Model):
    __tablename__ = "macro_targets"

    id = db.Column(db.Integer, primary_key=True)
    calories = db.Column(db.Float, nullable=False, default=2000.0)
    protein_min = db.Column(db.Float, nullable=False, default=120.0)
    protein_max = db.Column(db.Float, nullable=False, default=160.0)
    carbs_min = db.Column(db.Float, nullable=False, default=180.0)
    carbs_max = db.Column(db.Float, nullable=False, default=260.0)
    fat_min = db.Column(db.Float, nullable=False, default=50.0)
    fat_max = db.Column(db.Float, nullable=False, default=80.0)

    @property
    def protein_target(self) -> float:
        return (self.protein_min + self.protein_max) / 2.0

    @property
    def carbs_target(self) -> float:
        return (self.carbs_min + self.carbs_max) / 2.0

    @property
    def fat_target(self) -> float:
        return (self.fat_min + self.fat_max) / 2.0


class GeneratedPlan(db.Model):
    __tablename__ = "generated_plans"

    id = db.Column(db.Integer, primary_key=True)
    generated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    days = db.Column(db.Integer, nullable=False, default=7)


def _csv_to_list(value: str) -> list[str]:
    return [part.strip().lower() for part in value.split(",") if part.strip()]
