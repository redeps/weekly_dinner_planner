"""
Ingredient service functions — business logic for the `recipe_ingredients`
table. Screens call these; they never write to the database directly (see
docs/AGENT_INSTRUCTIONS.md).
"""

import sqlite3
from typing import Optional, TypedDict

from models import STORE_CATEGORIES, Ingredient


class IngredientInput(TypedDict, total=False):
    name: str
    quantity: Optional[float]
    unit: Optional[str]
    store_category: str


def _row_to_ingredient(row: sqlite3.Row) -> Ingredient:
    return Ingredient(
        id=row["id"],
        recipe_id=row["recipe_id"],
        name=row["name"],
        quantity=row["quantity"],
        unit=row["unit"],
        store_category=row["store_category"],
    )


def _dict_cursor(conn: sqlite3.Connection) -> sqlite3.Cursor:
    cursor = conn.cursor()
    cursor.row_factory = sqlite3.Row
    return cursor


def _validate_store_category(store_category: str) -> None:
    if store_category not in STORE_CATEGORIES:
        raise ValueError(f"Invalid store_category: {store_category!r}")


def list_ingredients(conn: sqlite3.Connection, recipe_id: int) -> list[Ingredient]:
    """List a recipe's ingredients in entry order."""
    rows = _dict_cursor(conn).execute(
        "SELECT * FROM recipe_ingredients WHERE recipe_id = ? ORDER BY id",
        (recipe_id,),
    ).fetchall()
    return [_row_to_ingredient(row) for row in rows]


def replace_recipe_ingredients(
    conn: sqlite3.Connection, recipe_id: int, ingredients: list[IngredientInput]
) -> None:
    """Replace all of a recipe's ingredient lines with the given set.

    The Add/Edit Recipe form always submits its full current row list, so a
    delete-all-then-reinsert keeps the save path simple — see
    docs/DECISIONS.md.
    """
    for ingredient in ingredients:
        _validate_store_category(ingredient.get("store_category", "other"))
    conn.execute("DELETE FROM recipe_ingredients WHERE recipe_id = ?", (recipe_id,))
    for ingredient in ingredients:
        conn.execute(
            """
            INSERT INTO recipe_ingredients (recipe_id, name, quantity, unit, store_category)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                recipe_id,
                ingredient["name"],
                ingredient.get("quantity"),
                ingredient.get("unit"),
                ingredient.get("store_category", "other"),
            ),
        )
    conn.commit()
