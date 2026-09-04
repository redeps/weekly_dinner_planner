"""
Manual grocery item service functions — business logic for the
`manual_grocery_items` table (Milestone 17): items not derived from any
recipe, either a one-off paste-in for a specific week (`week_plan_id`
set) or a standing recurring item (`week_plan_id` `NULL`, included in
every week). One table, one flag — see docs/DATA_MODEL.md and
docs/DECISIONS.md for why this isn't two separate tables.

Mirrors `services/ingredients.py`'s role for `recipe_ingredients`: pure
CRUD here, aggregation stays in `services/grocery_list.py`. Screens call
these; they never write to the database directly (see
docs/AGENT_INSTRUCTIONS.md).
"""

import re
from typing import Optional

import psycopg
from psycopg.rows import dict_row

from models import STORE_CATEGORIES, ManualGroceryItem

# A leading plain number (no fractions, no unicode vulgar fractions —
# unlike services/ingredient_canonicalization.py's recipe-import-tuned
# regex, there's no measured real-world need for that here yet; see
# docs/DECISIONS.md) followed by at least one space, so "24oz peanut
# butter" (no space between the digits and the letters) is correctly left
# alone rather than wrongly split into quantity=24/name="oz peanut
# butter". Requiring the trailing space is what fixes the data-loss bug
# this mechanism exists for: a pasted line like "6 eggs" must not lose
# its "6" to canonicalize_ingredient_name()'s own leading-number stripping
# once it's stored as a bare `name` with no separate `quantity`.
_LEADING_NUMBER_RE = re.compile(r"^(\d+(?:\.\d+)?)\s+(.+)$")


def parse_leading_quantity(line: str) -> tuple[Optional[float], str]:
    """Split a pasted grocery-item line into `(quantity, name)`. Only a
    *leading* plain number is recognized ("6 eggs" -> `(6.0, "eggs")`);
    anything else — no leading number, or a number with no following
    space ("24oz milk") — passes through unchanged as `(None, line)`.
    Never raises."""
    stripped = line.strip()
    match = _LEADING_NUMBER_RE.match(stripped)
    if match:
        return float(match.group(1)), match.group(2).strip()
    return None, stripped


def _validate_store_category(store_category: str) -> None:
    if store_category not in STORE_CATEGORIES:
        raise ValueError(f"Invalid store_category: {store_category!r}")


def _dict_cursor(conn: psycopg.Connection) -> psycopg.Cursor:
    return conn.cursor(row_factory=dict_row)


def _row_to_item(row: dict) -> ManualGroceryItem:
    return ManualGroceryItem(
        id=row["id"],
        week_plan_id=row["week_plan_id"],
        name=row["name"],
        quantity=row["quantity"],
        unit=row["unit"],
        store_category=row["store_category"],
        created_at=row["created_at"],
    )


def add_item(
    conn: psycopg.Connection,
    *,
    week_plan_id: Optional[int],
    name: str,
    quantity: Optional[float] = None,
    unit: Optional[str] = None,
    store_category: str = "other",
) -> int:
    """Add a manual grocery item and return its id. `week_plan_id=None`
    makes it recurring (included in every week); a specific id scopes it
    to that one week only."""
    _validate_store_category(store_category)
    cursor = conn.execute(
        """
        INSERT INTO manual_grocery_items (week_plan_id, name, quantity, unit, store_category)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING id
        """,
        (week_plan_id, name, quantity, unit, store_category),
    )
    item_id = cursor.fetchone()[0]
    conn.commit()
    return item_id


def remove_item(conn: psycopg.Connection, item_id: int) -> None:
    """Remove a manual grocery item. A no-op if it doesn't exist."""
    conn.execute("DELETE FROM manual_grocery_items WHERE id = %s", (item_id,))
    conn.commit()


def list_manual_items(
    conn: psycopg.Connection, week_plan_id: Optional[int] = None
) -> list[ManualGroceryItem]:
    """Manual grocery items, in entry order.

    `week_plan_id=None` (the default) lists only recurring items — the
    shape the recurring-items management screen needs. Passing a real
    week_plan_id lists that week's own one-off items *plus* every
    recurring item — the shape `build_grocery_list()` needs, since a
    week's shopping list must include both. There's no way to list "only
    this week's one-off items, excluding recurring" and "only recurring"
    with the same call — callers that need the former (e.g. an "added
    this week" management list) pass a week_plan_id and filter for
    `item.week_plan_id is not None` themselves, since that's a rarer need
    than either of the two cases above.
    """
    if week_plan_id is None:
        rows = _dict_cursor(conn).execute(
            "SELECT * FROM manual_grocery_items WHERE week_plan_id IS NULL ORDER BY id"
        ).fetchall()
    else:
        rows = _dict_cursor(conn).execute(
            """
            SELECT * FROM manual_grocery_items
            WHERE week_plan_id = %s OR week_plan_id IS NULL
            ORDER BY id
            """,
            (week_plan_id,),
        ).fetchall()
    return [_row_to_item(row) for row in rows]
