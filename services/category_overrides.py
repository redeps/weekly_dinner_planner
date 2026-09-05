"""
Persistent ingredient category overrides (Milestone 17 Phase 2) — a
correction to which store category a *canonical* ingredient belongs to,
keyed on `services.ingredient_canonicalization.canonicalize_ingredient_name()`'s
output, its first persisted consumer (see docs/DECISIONS.md for the
stability discussion).

Consulted inside `services.grocery_list.build_grocery_list()`'s own
aggregation, not by rewriting `recipe_ingredients` rows — the grocery
list is never cached, so resolving the override at aggregation time is
already both retroactive (every existing recipe regroups correctly next
time any list is built) and prospective (so is a brand-new recipe added
later) with no bulk `UPDATE` needed.

`suggest_category_with_override()` also gives the override precedence
over the static `categorization.py` dictionary *and* any AI suggestion
at Add/Edit Recipe's two categorization call sites — the AI 🤖 suggestion
only ever fires for a row still stuck on "other" after the deterministic
pass, so a row the override already resolves to a real category never
reaches it.
"""

from typing import Optional

import psycopg

from models import STORE_CATEGORIES
from services.categorization import suggest_category
from services.ingredient_canonicalization import canonicalize_ingredient_name


def _validate_store_category(store_category: str) -> None:
    if store_category not in STORE_CATEGORIES:
        raise ValueError(f"Invalid store_category: {store_category!r}")


def get_override(conn: psycopg.Connection, canonical_name: str) -> Optional[str]:
    """The overridden store_category for a canonical ingredient name, or
    `None` if none has been set. A single-row lookup — fine for Add/Edit
    Recipe's per-row suggestion (naturally one ingredient at a time as
    the user adds them), but `build_grocery_list()` must use
    `get_all_overrides()` instead: calling this once per ingredient line
    in that loop was confirmed as a real, measurable query-per-row
    bottleneck (65% of aggregation time on a real 71-line week) — see
    docs/DECISIONS.md."""
    row = conn.execute(
        "SELECT store_category FROM ingredient_category_overrides WHERE canonical_name = %s",
        (canonical_name,),
    ).fetchone()
    return row[0] if row else None


def get_all_overrides(conn: psycopg.Connection) -> dict[str, str]:
    """Every persisted override as `{canonical_name: store_category}`,
    fetched in one query. Built specifically for `build_grocery_list()`'s
    aggregation loop, which needs to resolve a potentially large number
    of ingredient lines against the override table in one pass — see
    `get_override()`'s docstring and docs/DECISIONS.md for the profiling
    that motivated this."""
    rows = conn.execute("SELECT canonical_name, store_category FROM ingredient_category_overrides").fetchall()
    return {row[0]: row[1] for row in rows}


def set_override(conn: psycopg.Connection, canonical_name: str, store_category: str) -> None:
    """Set (or replace) the override for a canonical ingredient name."""
    _validate_store_category(store_category)
    conn.execute(
        """
        INSERT INTO ingredient_category_overrides (canonical_name, store_category)
        VALUES (%s, %s)
        ON CONFLICT (canonical_name) DO UPDATE SET
            store_category = EXCLUDED.store_category,
            updated_at = to_char(now() AT TIME ZONE 'utc', 'YYYY-MM-DD HH24:MI:SS')
        """,
        (canonical_name, store_category),
    )
    conn.commit()


def suggest_category_with_override(conn: psycopg.Connection, ingredient_name: str) -> Optional[str]:
    """A category suggestion for a raw ingredient name: the persisted
    override for its canonical name if one exists, else the same
    deterministic dictionary lookup used before overrides existed. Used
    at suggestion time (Add/Edit Recipe's import prefill and its 🤖
    button) so a corrected category also applies to a brand-new
    ingredient row going forward, not only inside the grocery list's own
    aggregation — see module docstring."""
    override = get_override(conn, canonicalize_ingredient_name(ingredient_name))
    if override is not None:
        return override
    return suggest_category(ingredient_name)


def detect_category_edits(
    original_rows: list[dict], edited_rows: list[dict]
) -> list[tuple[str, str]]:
    """Compare the Grocery List page's original table rows against
    `st.data_editor`'s returned (possibly edited) rows and return
    `(canonical_name, store_category)` pairs for every row whose Category
    cell actually changed. Rows are plain dicts with "Category" and
    "Ingredient" keys — the same shape `pages/6_Grocery_List.py` builds
    from `grocery_list_table_rows()`.

    A pure function, deliberately kept in this service module rather than
    inline in the page script: `streamlit.testing.v1`'s `Dataframe` proxy
    (what `st.data_editor` renders as) has no way to simulate a live cell
    edit — confirmed directly against the installed Streamlit version,
    not assumed — so this diff-detection logic needs to be importable and
    testable on its own, with plain dicts, independent of AppTest (see
    docs/DECISIONS.md). The category is lowercased here (the editor
    displays/returns the capitalized form) to match
    `models.STORE_CATEGORIES`'s stored form.
    """
    changes = []
    for original, current in zip(original_rows, edited_rows):
        if current["Category"] != original["Category"]:
            canonical_name = canonicalize_ingredient_name(original["Ingredient"])
            changes.append((canonical_name, current["Category"].lower()))
    return changes
