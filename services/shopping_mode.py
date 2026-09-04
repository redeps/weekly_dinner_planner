"""
Shopping mode (Milestone 18). Phase 1 only: `mark_shopping_completed()`,
which sets `week_plans.shopping_completed_at` so the Grocery List page
can gate its whole list-and-export section on it, making the list appear
empty until a new week plan is generated — see docs/DATA_MODEL.md and
docs/DECISIONS.md (which also supersedes the original "Grocery list is
not a shopping-mode feature" entry from 2026-08-31).

Phase 2 (not built yet) will add the checked-off-item state
(`grocery_checked_items`) this module is named for; kept as its own
module now rather than folded into `services/plan_generation.py`, since
shopping mode is a cohesive feature of its own even though this phase
only touches a column on `week_plans`.
"""

import psycopg


def mark_shopping_completed(conn: psycopg.Connection, week_plan_id: int) -> None:
    """Mark a week's shopping trip complete. A week plan with this set is
    treated by the Grocery List page as having an empty list — Finish
    Shopping, not a delete — until a new week plan is generated, whose
    `shopping_completed_at` starts unset regardless of any prior week's
    state (see docs/DECISIONS.md)."""
    conn.execute(
        """
        UPDATE week_plans
        SET shopping_completed_at = to_char(now() AT TIME ZONE 'utc', 'YYYY-MM-DD HH24:MI:SS')
        WHERE id = %s
        """,
        (week_plan_id,),
    )
    conn.commit()
