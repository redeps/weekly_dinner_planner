"""
Grocery list generation — aggregates recipe_ingredients across the current
week plan's 7 days, grouped by store category (see docs/PRODUCT_SPEC.md
§11). Nothing here is persisted: the list is computed fresh from the
current `plan_days` + `recipe_ingredients` every time it's built, so a
swapped day is reflected automatically the next time it's viewed — no
check-off state or shopping-mode UI, per docs/DECISIONS.md.
"""

import sqlite3
from dataclasses import dataclass
from typing import Optional

from models import STORE_CATEGORIES
from services.ingredients import list_ingredients
from services.plan_generation import list_plan_days


@dataclass
class GroceryItem:
    name: str
    quantity: Optional[float]
    unit: Optional[str]
    store_category: str


def build_grocery_list(
    conn: sqlite3.Connection, week_plan_id: int
) -> dict[str, list[GroceryItem]]:
    """Aggregate ingredients across a week plan's 7 assigned recipes.

    Counted once per day, so a recipe repeated within the week contributes
    its ingredients twice. Quantities are summed where name and unit match
    (case/whitespace-insensitively); a differing unit is kept as a separate
    line rather than summed. Grouped by store category, empty categories
    omitted, items sorted alphabetically within each category.
    """
    aggregated: dict[tuple, dict] = {}

    for plan_day in list_plan_days(conn, week_plan_id):
        if plan_day.recipe_id is None:
            continue
        for ingredient in list_ingredients(conn, plan_day.recipe_id):
            name_key = ingredient.name.strip().lower()
            unit_key = ingredient.unit.strip().lower() if ingredient.unit else None
            key = (name_key, unit_key, ingredient.store_category)
            entry = aggregated.setdefault(
                key,
                {
                    "name": ingredient.name.strip(),
                    "unit": ingredient.unit.strip() if ingredient.unit else None,
                    "store_category": ingredient.store_category,
                    "quantity": None,
                },
            )
            if ingredient.quantity is not None:
                entry["quantity"] = (entry["quantity"] or 0) + ingredient.quantity

    grouped: dict[str, list[GroceryItem]] = {category: [] for category in STORE_CATEGORIES}
    for entry in aggregated.values():
        grouped[entry["store_category"]].append(GroceryItem(**entry))

    for items in grouped.values():
        items.sort(key=lambda item: item.name.lower())

    return {category: items for category, items in grouped.items() if items}
