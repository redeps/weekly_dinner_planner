"""
Cook history — records which recipe was cooked on which date. Written only
by explicit business-logic actions (`mark_day_cooked`, `finalize_plan`),
never as a side effect of rendering: Streamlit reruns the whole script on
every interaction, so rendering code that wrote a history row could turn
one user action into duplicate rows — see docs/AGENT_INSTRUCTIONS.md §4.
Feeds the rotation weighting in services/plan_generation.py.
"""

import datetime as dt
import sqlite3
from typing import Optional

from models import CookHistoryEntry
from services.plan_generation import get_plan_day, list_plan_days


def has_been_cooked(conn: sqlite3.Connection, plan_day_id: int) -> bool:
    """Whether this plan day already has a cook_history record."""
    row = conn.execute(
        "SELECT 1 FROM cook_history WHERE plan_day_id = ? LIMIT 1", (plan_day_id,)
    ).fetchone()
    return row is not None


def mark_day_cooked(
    conn: sqlite3.Connection, plan_day_id: int, *, cooked_on: Optional[dt.date] = None
) -> Optional[int]:
    """Record a plan day's recipe as cooked. Returns the new cook_history
    id, or None if this plan day was already marked cooked — idempotent
    per plan day, since a plan day represents one real dinner and
    shouldn't be recorded twice.

    Only ever call this from an explicit user action (a button click),
    never from rendering code — see docs/AGENT_INSTRUCTIONS.md §4.
    """
    plan_day = get_plan_day(conn, plan_day_id)
    if plan_day is None:
        raise ValueError(f"No such plan day: {plan_day_id}")
    if plan_day.recipe_id is None:
        raise ValueError(f"Plan day {plan_day_id} has no recipe assigned.")
    if has_been_cooked(conn, plan_day_id):
        return None

    cooked_on = cooked_on or dt.date.fromisoformat(plan_day.date)
    cursor = conn.execute(
        "INSERT INTO cook_history (recipe_id, plan_day_id, cooked_on) VALUES (?, ?, ?)",
        (plan_day.recipe_id, plan_day_id, cooked_on.isoformat()),
    )
    conn.commit()
    return cursor.lastrowid


def finalize_plan(conn: sqlite3.Connection, week_plan_id: int) -> list[int]:
    """Mark every day of a week plan as cooked. Days with no recipe
    assigned, or already marked cooked, are skipped — safe to call more
    than once. Returns the newly created cook_history ids."""
    ids = []
    for plan_day in list_plan_days(conn, week_plan_id):
        if plan_day.recipe_id is None:
            continue
        new_id = mark_day_cooked(conn, plan_day.id)
        if new_id is not None:
            ids.append(new_id)
    return ids


def _dict_cursor(conn: sqlite3.Connection) -> sqlite3.Cursor:
    cursor = conn.cursor()
    cursor.row_factory = sqlite3.Row
    return cursor


def list_recent_cook_history(
    conn: sqlite3.Connection, *, limit: int = 20
) -> list[CookHistoryEntry]:
    """The most recently cooked recipes, most recent first — powers the
    "what have we cooked lately" view."""
    rows = _dict_cursor(conn).execute(
        """
        SELECT cook_history.id AS id,
               cook_history.recipe_id AS recipe_id,
               recipes.name AS recipe_name,
               cook_history.plan_day_id AS plan_day_id,
               cook_history.cooked_on AS cooked_on,
               cook_history.created_at AS created_at
        FROM cook_history
        JOIN recipes ON recipes.id = cook_history.recipe_id
        ORDER BY cook_history.cooked_on DESC, cook_history.id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [
        CookHistoryEntry(
            id=row["id"],
            recipe_id=row["recipe_id"],
            recipe_name=row["recipe_name"],
            plan_day_id=row["plan_day_id"],
            cooked_on=row["cooked_on"],
            created_at=row["created_at"],
        )
        for row in rows
    ]
