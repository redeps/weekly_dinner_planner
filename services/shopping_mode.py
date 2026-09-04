"""
Shopping mode (Milestone 18).

Phase 1: `mark_shopping_completed()`, which sets
`week_plans.shopping_completed_at` so the Grocery List page can gate its
whole list-and-export section on it, making the list appear empty until
a new week plan is generated — see docs/DATA_MODEL.md and
docs/DECISIONS.md (which also supersedes the original "Grocery list is
not a shopping-mode feature" entry from 2026-08-31).

Phase 2: checked-off-item state (`grocery_checked_items`), the table this
module is named for. Kept as its own module rather than folded into
`services/plan_generation.py` (where `week_plans` itself is otherwise
managed) or `services/grocery_list.py` (pure aggregation, deliberately
kept unaware of checked/completion state) — shopping mode is a cohesive
feature of its own spanning both a `week_plans` column and its own table,
the same "one module, several tables, one feature" shape
`plan_generation.py` already has for `week_plans`/`plan_days`/
`plan_day_dishes`.

`check_item`/`uncheck_item` mirror `plan_generation.py`'s
`attach_dish`/`detach_dish` shape exactly: row presence = checked, no
boolean column, `ON CONFLICT DO NOTHING` on check rather than a
pre-check-then-insert. `grocery_checked_items` keys on
`(week_plan_id, canonical_name, unit)` — the grocery list's own
post-aggregation display identity, since a single checked line can
represent several merged `recipe_ingredients` rows, not one. `unit` is
stored as `''`, never `NULL`, specifically because a `UNIQUE` constraint
over a nullable column doesn't reject duplicates in Postgres (`NULL` is
never equal to `NULL`) — confirmed directly during the Phase 2
investigation, not assumed — which would have silently broken the
`ON CONFLICT` upsert for the common "no unit on this line" case.
"""

import psycopg

from services.grocery_list import NO_VALUE_DISPLAY
from services.ingredient_canonicalization import canonicalize_ingredient_name


def mark_shopping_completed(conn: psycopg.Connection, week_plan_id: int) -> None:
    """Mark a week's shopping trip complete. A week plan with this set is
    treated by the Grocery List page as having an empty list — Finish
    Shopping, not a delete — until a new week plan is generated, whose
    `shopping_completed_at` starts unset regardless of any prior week's
    state (see docs/DECISIONS.md). Existing `grocery_checked_items` rows
    for this week are left alone — they're already scoped to this
    `week_plan_id` and simply won't match a future week's query, same
    "never hard-delete, scope by week_plan_id" convention as every other
    table in this schema; no cleanup needed."""
    conn.execute(
        """
        UPDATE week_plans
        SET shopping_completed_at = to_char(now() AT TIME ZONE 'utc', 'YYYY-MM-DD HH24:MI:SS')
        WHERE id = %s
        """,
        (week_plan_id,),
    )
    conn.commit()


def check_item(
    conn: psycopg.Connection, week_plan_id: int, canonical_name: str, unit: str = ""
) -> None:
    """Check off one grocery-list line for a week. A no-op, not a raised
    constraint violation, if it's already checked
    (`UNIQUE(week_plan_id, canonical_name, unit)`)."""
    conn.execute(
        """
        INSERT INTO grocery_checked_items (week_plan_id, canonical_name, unit)
        VALUES (%s, %s, %s)
        ON CONFLICT (week_plan_id, canonical_name, unit) DO NOTHING
        """,
        (week_plan_id, canonical_name, unit),
    )
    conn.commit()


def uncheck_item(
    conn: psycopg.Connection, week_plan_id: int, canonical_name: str, unit: str = ""
) -> None:
    """Restore (un-check) one grocery-list line for a week. A no-op if it
    wasn't checked."""
    conn.execute(
        "DELETE FROM grocery_checked_items WHERE week_plan_id = %s AND canonical_name = %s AND unit = %s",
        (week_plan_id, canonical_name, unit),
    )
    conn.commit()


def list_checked_items(conn: psycopg.Connection, week_plan_id: int) -> list[tuple[str, str]]:
    """`(canonical_name, unit)` pairs currently checked off for a week."""
    rows = conn.execute(
        "SELECT canonical_name, unit FROM grocery_checked_items WHERE week_plan_id = %s",
        (week_plan_id,),
    ).fetchall()
    return [(row[0], row[1]) for row in rows]


def row_key(ingredient: str, unit: str) -> tuple[str, str]:
    """The `(canonical_name, unit)` identity for one grocery-table row —
    shared by the page's active/checked filtering and the write calls
    above, so they can never derive it inconsistently. `unit` is
    normalized from the table's "—" placeholder (`NO_VALUE_DISPLAY`) back
    to `""` to match `grocery_checked_items`' own storage convention."""
    return (canonicalize_ingredient_name(ingredient), "" if unit == NO_VALUE_DISPLAY else unit)


def detect_checked_edits(
    original_rows: list[dict], edited_rows: list[dict]
) -> list[tuple[str, str]]:
    """Compare the Grocery List page's original (active-only, in
    shopping mode) rows against `st.data_editor`'s returned rows and
    return `(canonical_name, unit)` pairs for every row newly checked
    this run.

    Only detects False -> True: a row already checked is filtered out of
    the active view before it's ever shown to this function again, so
    there's no True -> False transition to detect here — unchecking only
    ever happens via the "Restore" action in the checked-off section, a
    plain button, not a data_editor edit. A pure function, kept in this
    service module for the same testability reason as
    `services.category_overrides.detect_category_edits` — see its
    docstring and docs/DECISIONS.md.
    """
    changes = []
    for original, current in zip(original_rows, edited_rows):
        if current["Checked"] and not original["Checked"]:
            changes.append(row_key(original["Ingredient"], original["Unit"]))
    return changes
