"""
Recipe service functions — business logic for the `recipes` table.

Screens call these; they never write to the database directly (see
docs/AGENT_INSTRUCTIONS.md). Each function takes an explicit connection so
it can be tested against an isolated database.
"""

from typing import Optional

import psycopg
from psycopg.rows import dict_row

from models import SEASONALITIES, Recipe

_NOW_EXPR = "to_char(now() AT TIME ZONE 'utc', 'YYYY-MM-DD HH24:MI:SS')"

QUICK_FALLBACK_SEEDS = [
    {
        "name": "Fish Fingers",
        "cook_time_minutes": 15,
        "family_enjoyment": 3,
        "seasonality": "all-season",
        "is_quick_fallback": True,
        "servings": 4,
        "instructions": "Bake according to packet instructions.",
        "notes": "Freezer staple for busy nights.",
    },
    {
        "name": "Frozen Pizza",
        "cook_time_minutes": 20,
        "family_enjoyment": 3,
        "seasonality": "all-season",
        "is_quick_fallback": True,
        "servings": 4,
        "instructions": "Bake according to packet instructions.",
        "notes": "Keep a couple in the freezer for emergencies.",
    },
    {
        "name": "Takeout",
        "cook_time_minutes": 0,
        "family_enjoyment": 4,
        "seasonality": "all-season",
        "is_quick_fallback": True,
        "servings": 4,
        "instructions": "Order from a favorite local place.",
        "notes": "No cooking required.",
    },
]


def _row_to_recipe(row: dict) -> Recipe:
    return Recipe(
        id=row["id"],
        name=row["name"],
        photo_path=row["photo_path"],
        cook_time_minutes=row["cook_time_minutes"],
        family_enjoyment=row["family_enjoyment"],
        seasonality=row["seasonality"],
        is_quick_fallback=bool(row["is_quick_fallback"]),
        is_special_occasion=bool(row["is_special_occasion"]),
        servings=row["servings"],
        instructions=row["instructions"],
        notes=row["notes"],
        active=bool(row["active"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _dict_cursor(conn: psycopg.Connection) -> psycopg.Cursor:
    return conn.cursor(row_factory=dict_row)


def _validate_seasonality(seasonality: str) -> None:
    if seasonality not in SEASONALITIES:
        raise ValueError(f"Invalid seasonality: {seasonality!r}")


def create_recipe(
    conn: psycopg.Connection,
    *,
    name: str,
    cook_time_minutes: int,
    family_enjoyment: int,
    seasonality: str,
    servings: int,
    is_quick_fallback: bool = False,
    is_special_occasion: bool = False,
    instructions: Optional[str] = None,
    notes: Optional[str] = None,
    photo_path: Optional[str] = None,
) -> int:
    """Insert a new recipe and return its id."""
    _validate_seasonality(seasonality)
    cursor = conn.execute(
        """
        INSERT INTO recipes (
            name, photo_path, cook_time_minutes, family_enjoyment,
            seasonality, is_quick_fallback, is_special_occasion, servings,
            instructions, notes
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (
            name,
            photo_path,
            cook_time_minutes,
            family_enjoyment,
            seasonality,
            int(is_quick_fallback),
            int(is_special_occasion),
            servings,
            instructions,
            notes,
        ),
    )
    recipe_id = cursor.fetchone()[0]
    conn.commit()
    return recipe_id


def update_recipe(conn: psycopg.Connection, recipe_id: int, **fields) -> None:
    """Update the given fields on a recipe. No-op if `fields` is empty."""
    if not fields:
        return
    if "seasonality" in fields:
        _validate_seasonality(fields["seasonality"])
    if "is_quick_fallback" in fields:
        fields["is_quick_fallback"] = int(fields["is_quick_fallback"])
    if "is_special_occasion" in fields:
        fields["is_special_occasion"] = int(fields["is_special_occasion"])
    columns = ", ".join(f"{key} = %s" for key in fields)
    values = list(fields.values()) + [recipe_id]
    conn.execute(
        f"UPDATE recipes SET {columns}, updated_at = {_NOW_EXPR} WHERE id = %s",
        values,
    )
    conn.commit()


def get_recipe(conn: psycopg.Connection, recipe_id: int) -> Optional[Recipe]:
    row = _dict_cursor(conn).execute(
        "SELECT * FROM recipes WHERE id = %s", (recipe_id,)
    ).fetchone()
    return _row_to_recipe(row) if row else None


def list_recipes(
    conn: psycopg.Connection,
    *,
    search: Optional[str] = None,
    season: Optional[str] = None,
    quick_fallback_only: bool = False,
    special_occasion_only: bool = False,
    include_inactive: bool = False,
) -> list[Recipe]:
    """List recipes, optionally filtered by name search, season,
    quick-fallback, or special-occasion status. Inactive (soft-deleted)
    recipes are excluded by default."""
    query = "SELECT * FROM recipes WHERE 1=1"
    params: list = []
    if not include_inactive:
        query += " AND active = 1"
    if search:
        query += " AND name ILIKE %s"
        params.append(f"%{search}%")
    if season:
        query += " AND seasonality = %s"
        params.append(season)
    if quick_fallback_only:
        query += " AND is_quick_fallback = 1"
    if special_occasion_only:
        query += " AND is_special_occasion = 1"
    query += " ORDER BY LOWER(name)"
    rows = _dict_cursor(conn).execute(query, params).fetchall()
    return [_row_to_recipe(row) for row in rows]


def deactivate_recipe(conn: psycopg.Connection, recipe_id: int) -> None:
    """Soft-delete a recipe by marking it inactive."""
    conn.execute(
        f"UPDATE recipes SET active = 0, updated_at = {_NOW_EXPR} WHERE id = %s",
        (recipe_id,),
    )
    conn.commit()


def seed_quick_fallback_recipes(conn: psycopg.Connection) -> None:
    """Insert the default quick-fallback recipes if none exist yet."""
    existing = conn.execute(
        "SELECT COUNT(*) FROM recipes WHERE is_quick_fallback = 1"
    ).fetchone()[0]
    if existing:
        return
    for seed in QUICK_FALLBACK_SEEDS:
        create_recipe(conn, **seed)
