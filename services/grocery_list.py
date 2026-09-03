"""
Grocery list generation — aggregates recipe_ingredients across the current
week plan's 7 days, grouped by store category (see docs/PRODUCT_SPEC.md
§11). Nothing here is persisted: the list is computed fresh from the
current `plan_days` + `recipe_ingredients` every time it's built, so a
swapped day is reflected automatically the next time it's viewed — no
check-off state or shopping-mode UI, per docs/DECISIONS.md.

Household-size scaling (Milestone 14): each day's ingredient quantities
are scaled by that day's effective household size (its own
`household_size_override` if set, else the global default) relative to
the recipe's own `servings`, before being summed across days — via
`services.settings.effective_ingredient_quantity()`, the same shared
helper Cook Mode and Recipe Detail use, so all three can't drift from
each other (see docs/DECISIONS.md). An ingredient with no quantity (e.g.
"salt to taste") can't be scaled and is passed through unchanged; a
special-occasion recipe (`is_special_occasion`) with no explicit
per-day override is left at its own unscaled quantities too — see
`effective_ingredient_quantity()`'s docstring. Simple 2-decimal rounding
is applied both per day and to the aggregated total — see
docs/DECISIONS.md for why, confirmed against real scaled data.

Ingredient name canonicalization (see
services/ingredient_canonicalization.py and docs/DECISIONS.md): lines are
grouped by *canonical* name, not the raw stored name, so "garlic cloves
crushed" and "garlic clove finely grated" land under one "Garlic" heading
instead of two separate lines. Quantities are still only summed within a
matching *unit* — deliberately not attempted across units (e.g. "2 tbsp"
is never combined with "112 ml"), since that would need real unit
conversion this app doesn't do. The unit itself is normalized first
(`normalize_unit()` — "tbsp" and "tablespoons" are the same unit written
two ways, not two different units) so equivalent spellings group and sum
together instead of showing as separate lines; genuinely different units
(tbsp vs. tsp) still never merge. A canonical group with more than one
distinct unit (or a mix of quantified and unscaled lines) is returned
with multiple `GroceryUnitLine`s; a group with exactly one keeps the
simple single-line shape.

`grocery_list_table_rows()` flattens the above into one row per
(category, ingredient, quantity, unit) — the shared data source for both
the on-page table and the CSV export (`grocery_list_csv()`), so there's
one row shape, not two independently-formatted presentations that could
drift. Both `quantity` and `unit` are display-ready strings, with a "—"
placeholder for "not scaled" and "no unit on this line" respectively —
deliberately explicit rather than a bare number or an empty cell, which
read as confusing/broken rather than as "nothing to show here."
"""

import csv
import io
import psycopg
from dataclasses import dataclass, field
from typing import Optional

from models import STORE_CATEGORIES
from services.ingredient_canonicalization import canonicalize_ingredient_name, normalize_unit
from services.ingredients import list_ingredients
from services.plan_generation import list_plan_days
from services.recipes import get_recipe
from services.settings import effective_ingredient_quantity, get_default_household_size

NO_VALUE_DISPLAY = "—"


@dataclass
class GroceryUnitLine:
    quantity: Optional[float]
    unit: Optional[str]


@dataclass
class GroceryTableRow:
    category: str
    ingredient: str
    quantity: str
    unit: str


@dataclass
class GroceryItem:
    name: str
    store_category: str
    lines: list[GroceryUnitLine] = field(default_factory=list)


def build_grocery_list(
    conn: psycopg.Connection, week_plan_id: int
) -> dict[str, list[GroceryItem]]:
    """Aggregate ingredients across a week plan's 7 assigned recipes.

    Counted once per day, so a recipe repeated within the week contributes
    its ingredients twice. Grouped by canonical ingredient name (see
    module docstring); within a group, quantities are summed where unit
    matches (case/whitespace-insensitively) — a differing unit becomes a
    separate line within the same group rather than being combined.
    Grouped by store category, empty categories omitted, items sorted
    alphabetically by canonical name within each category.
    """
    aggregated: dict[tuple, dict] = {}
    default_household_size = get_default_household_size(conn)

    for plan_day in list_plan_days(conn, week_plan_id):
        if plan_day.recipe_id is None:
            continue
        recipe = get_recipe(conn, plan_day.recipe_id)
        if recipe is None:
            continue

        for ingredient in list_ingredients(conn, plan_day.recipe_id):
            canonical = canonicalize_ingredient_name(ingredient.name)
            unit = normalize_unit(ingredient.unit) or None
            key = (canonical, unit, ingredient.store_category)
            entry = aggregated.setdefault(
                key,
                {
                    "canonical": canonical,
                    "unit": unit,
                    "store_category": ingredient.store_category,
                    "quantity": None,
                },
            )
            scaled_quantity = effective_ingredient_quantity(
                ingredient.quantity,
                recipe_servings=recipe.servings,
                is_special_occasion=recipe.is_special_occasion,
                household_size_override=plan_day.household_size_override,
                default_household_size=default_household_size,
            )
            if scaled_quantity is not None:
                entry["quantity"] = round((entry["quantity"] or 0) + scaled_quantity, 2)

    items_by_group: dict[tuple, GroceryItem] = {}
    for entry in aggregated.values():
        group_key = (entry["canonical"], entry["store_category"])
        item = items_by_group.setdefault(
            group_key,
            GroceryItem(
                name=entry["canonical"][:1].upper() + entry["canonical"][1:],
                store_category=entry["store_category"],
            ),
        )
        item.lines.append(GroceryUnitLine(quantity=entry["quantity"], unit=entry["unit"]))

    grouped: dict[str, list[GroceryItem]] = {category: [] for category in STORE_CATEGORIES}
    for item in items_by_group.values():
        grouped[item.store_category].append(item)

    for items in grouped.values():
        items.sort(key=lambda item: item.name.lower())
        for item in items:
            item.lines.sort(key=lambda line: line.unit or "")

    return {category: items for category, items in grouped.items() if items}


def grocery_list_table_rows(
    grocery_list: dict[str, list[GroceryItem]]
) -> list[GroceryTableRow]:
    """Flatten `build_grocery_list()`'s output into one row per
    (category, ingredient, quantity, unit) — the shared data source for
    both the on-page table and `grocery_list_csv()`. Category order
    follows `STORE_CATEGORIES`; within a category, `grocery_list`'s
    existing item order (alphabetical by name) is preserved, and a
    multi-line item contributes one row per line, in that item's
    existing line order."""
    rows: list[GroceryTableRow] = []
    for category in STORE_CATEGORIES:
        items = grocery_list.get(category)
        if not items:
            continue
        for item in items:
            for line in item.lines:
                quantity_display = (
                    NO_VALUE_DISPLAY if line.quantity is None else f"{line.quantity:g}"
                )
                unit_display = line.unit or NO_VALUE_DISPLAY
                rows.append(
                    GroceryTableRow(
                        category=category.capitalize(),
                        ingredient=item.name,
                        quantity=quantity_display,
                        unit=unit_display,
                    )
                )
    return rows


def grocery_list_csv(grocery_list: dict[str, list[GroceryItem]]) -> str:
    """The same rows as `grocery_list_table_rows()`, as CSV text — plain
    CSV, not a `.xlsx` file: it opens correctly in Excel with zero added
    dependency, and this is a flat ingredient list with no multi-sheet or
    cell-formatting need that would justify one (e.g. `openpyxl`) — see
    docs/DECISIONS.md."""
    rows = grocery_list_table_rows(grocery_list)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["Category", "Ingredient", "Quantity", "Unit"])
    for row in rows:
        writer.writerow([row.category, row.ingredient, row.quantity, row.unit])
    return buffer.getvalue()
