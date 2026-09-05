"""
Grocery list generation — aggregates recipe_ingredients across the current
week plan's 7 days (each day's main recipe *and* every attached side/
dessert, Milestone 16 Phase 3) plus manual grocery items (Milestone 17 —
this week's one-off paste-ins and every standing recurring item), grouped
by store category (see docs/PRODUCT_SPEC.md §11). Nothing here is
persisted beyond the manual items themselves: the list is computed fresh
from the current `plan_days` + `plan_day_dishes` + `recipe_ingredients` +
`manual_grocery_items` every time it's built, so a swapped day, a changed
attachment, or an added/removed manual item is reflected automatically
the next time it's viewed — no check-off state or shopping-mode UI, per
docs/DECISIONS.md.

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
from services.category_overrides import get_all_overrides
from services.grocery_items import list_manual_items
from services.ingredient_canonicalization import canonicalize_ingredient_name, normalize_unit
from services.ingredients import list_ingredients
from services.plan_generation import list_dishes, list_plan_days
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


def _accumulate(
    aggregated: dict[tuple, dict],
    overrides: dict[str, str],
    *,
    name: str,
    quantity: Optional[float],
    unit: Optional[str],
    store_category: str,
) -> None:
    """Fold one already-scaled (or unscaled, for a manual item) quantity
    line into `aggregated`, keyed by (canonical name, normalized unit,
    *effective* store category) — the one grouping/summing rule shared by
    every ingredient source `build_grocery_list()` reads from,
    recipe-derived or manual.

    The effective category resolves any persisted override
    (Milestone 17 Phase 2, `services.category_overrides`) for this
    canonical name *before* the grouping key is formed, not as a later
    relabel — otherwise the same canonical ingredient could still split
    into two groups if different recipes happen to have stored different
    raw `store_category` values for it. This is also the only place an
    override is consulted: the grocery list is never cached, so
    resolving it here is already both retroactive and prospective with
    no need to rewrite any `recipe_ingredients` row (see docs/DECISIONS.md).

    `overrides` is the whole override table, fetched once by the caller
    (`get_all_overrides()`) — not a `conn` this function queries itself.
    Confirmed by real profiling against a 71-line real week plan that
    calling `get_override()` here, once per line, was a genuine
    query-per-row bottleneck (65% of this function's total time); a
    single dict lookup instead is effectively free (see docs/DECISIONS.md
    for the before/after numbers).
    """
    canonical = canonicalize_ingredient_name(name)
    effective_category = overrides.get(canonical, store_category)
    normalized_unit = normalize_unit(unit) or None
    key = (canonical, normalized_unit, effective_category)
    entry = aggregated.setdefault(
        key,
        {
            "canonical": canonical,
            "unit": normalized_unit,
            "store_category": effective_category,
            "quantity": None,
        },
    )
    if quantity is not None:
        entry["quantity"] = round((entry["quantity"] or 0) + quantity, 2)


def build_grocery_list(
    conn: psycopg.Connection, week_plan_id: int
) -> dict[str, list[GroceryItem]]:
    """Aggregate ingredients across a week plan's 7 days — each day's main
    recipe *and* every side/dessert attached to it (Milestone 16 Phase 3,
    `services.plan_generation.list_dishes`), not just the main — plus
    every manual grocery item for the week (Milestone 17,
    `services.grocery_items.list_manual_items`): this week's own one-off
    paste-ins and every standing recurring item.

    Counted once per day per dish, so a recipe repeated within the week
    (as a main, or attached to more than one day) contributes its
    ingredients each time. Grouped by canonical ingredient name (see
    module docstring); within a group, quantities are summed where unit
    matches (case/whitespace-insensitively) — a differing unit becomes a
    separate line within the same group rather than being combined.
    Grouped by store category, empty categories omitted, items sorted
    alphabetically by canonical name within each category. A manual item
    sharing a canonical name with a recipe-derived ingredient (e.g. a
    recurring "Milk" and a recipe that also needs milk) merges into the
    same group via this same key — no separate dedup logic needed.

    An attached side/dessert scales exactly like a main — same
    `effective_ingredient_quantity()` call, keyed off its own `servings`
    and the day's household size/override, since scaling is a per-recipe
    concept with no course-awareness needed (confirmed during the
    Milestone 16 Phase 1 investigation, see docs/DECISIONS.md). A manual
    item is used exactly as entered, with no scaling attempt — it has no
    `servings` to scale from, since it isn't derived from any recipe.

    A persisted category override (Milestone 17 Phase 2, see `_accumulate()`)
    is resolved for every line here, recipe-derived or manual — a
    corrected category always wins over whatever `store_category` was
    actually stored, for every recipe that uses that ingredient, every
    week, with no `recipe_ingredients` row ever rewritten.
    """
    aggregated: dict[tuple, dict] = {}
    default_household_size = get_default_household_size(conn)
    # Fetched once, not once per ingredient line -- see _accumulate()'s
    # docstring and docs/DECISIONS.md for the profiling behind this.
    overrides = get_all_overrides(conn)

    for plan_day in list_plan_days(conn, week_plan_id):
        day_recipes = []
        if plan_day.recipe_id is not None:
            main_recipe = get_recipe(conn, plan_day.recipe_id)
            if main_recipe is not None:
                day_recipes.append(main_recipe)
        day_recipes.extend(list_dishes(conn, plan_day.id))

        for recipe in day_recipes:
            for ingredient in list_ingredients(conn, recipe.id):
                scaled_quantity = effective_ingredient_quantity(
                    ingredient.quantity,
                    recipe_servings=recipe.servings,
                    is_special_occasion=recipe.is_special_occasion,
                    household_size_override=plan_day.household_size_override,
                    default_household_size=default_household_size,
                )
                _accumulate(
                    aggregated,
                    overrides,
                    name=ingredient.name,
                    quantity=scaled_quantity,
                    unit=ingredient.unit,
                    store_category=ingredient.store_category,
                )

    for item in list_manual_items(conn, week_plan_id):
        _accumulate(
            aggregated,
            overrides,
            name=item.name,
            quantity=item.quantity,
            unit=item.unit,
            store_category=item.store_category,
        )

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
