"""
App-wide settings — a single row (id=1) in `app_settings`, mirroring the
one-row pattern `database.py` already uses for `schema_version`. Currently
holds only the global default household size (see docs/DATA_MODEL.md and
Milestone 14 in docs/ROADMAP.md); add further settings here only when a
milestone actually needs them, not speculatively (docs/AGENT_INSTRUCTIONS.md
§7).

Also holds the household-size ingredient-scaling helpers
(`scale_ingredient_quantity` / `effective_ingredient_quantity`) — small
pure functions, not `app_settings` reads, but the natural next step after
`effective_household_size` and shared by every screen that scales
ingredient amounts (grocery list, Cook Mode, Recipe Detail) so they can't
drift from each other. See docs/DECISIONS.md.
"""

from typing import Optional

import psycopg

DEFAULT_HOUSEHOLD_SIZE = 4


def get_default_household_size(conn: psycopg.Connection) -> int:
    """The global default household size, lazily seeding the single
    settings row on first read rather than requiring a separate migration
    step to populate it."""
    row = conn.execute(
        "SELECT default_household_size FROM app_settings WHERE id = 1"
    ).fetchone()
    if row is not None:
        return row[0]
    conn.execute(
        "INSERT INTO app_settings (id, default_household_size) VALUES (1, %s)",
        (DEFAULT_HOUSEHOLD_SIZE,),
    )
    conn.commit()
    return DEFAULT_HOUSEHOLD_SIZE


def set_default_household_size(conn: psycopg.Connection, size: int) -> None:
    if size < 1:
        raise ValueError("default_household_size must be at least 1")
    conn.execute(
        """
        INSERT INTO app_settings (id, default_household_size) VALUES (1, %s)
        ON CONFLICT (id) DO UPDATE SET default_household_size = EXCLUDED.default_household_size
        """,
        (size,),
    )
    conn.commit()


def effective_household_size(household_size_override, default_size: int) -> int:
    """The size to scale a day's recipe to: its own override if set, else
    the global default (see docs/DATA_MODEL.md)."""
    return household_size_override if household_size_override is not None else default_size


def scale_ingredient_quantity(
    quantity: Optional[float], *, recipe_servings: int, household_size: int
) -> Optional[float]:
    """Scale one ingredient quantity from the recipe's own `servings` to a
    given household size, rounded to 2 decimal places. `None` (no quantity
    on the recipe, e.g. "salt to taste") passes through unchanged — there's
    nothing to scale. Shared by every screen that displays or aggregates
    ingredient amounts (grocery list, Cook Mode, Recipe Detail) so they
    can't drift from each other — see docs/DECISIONS.md."""
    if quantity is None:
        return None
    return round(quantity * (household_size / recipe_servings), 2)


def effective_ingredient_quantity(
    quantity: Optional[float],
    *,
    recipe_servings: int,
    is_special_occasion: bool,
    household_size_override: Optional[int],
    default_household_size: int,
) -> Optional[float]:
    """The quantity to actually show for one ingredient on one day: scaled
    to that day's effective household size, except a special-occasion
    recipe (`is_special_occasion`) with no explicit `household_size_override`
    for that day — there, the recipe's own author-set quantities are
    trusted as-is rather than silently stretched or shrunk to the app-wide
    default, since a special-occasion recipe's serving count was
    deliberately chosen for a specific event, not for routine household
    size. An explicit override for that specific day still takes
    precedence — someone deliberately said how many people that day is
    actually for, which is a stronger signal than the recipe's own default.
    See docs/DECISIONS.md."""
    if is_special_occasion and household_size_override is None:
        return quantity
    household_size = effective_household_size(household_size_override, default_household_size)
    return scale_ingredient_quantity(
        quantity, recipe_servings=recipe_servings, household_size=household_size
    )
