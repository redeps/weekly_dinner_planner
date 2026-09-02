"""
App-wide settings — a single row (id=1) in `app_settings`, mirroring the
one-row pattern `database.py` already uses for `schema_version`. Currently
holds only the global default household size (see docs/DATA_MODEL.md and
Milestone 14 in docs/ROADMAP.md); add further settings here only when a
milestone actually needs them, not speculatively (docs/AGENT_INSTRUCTIONS.md
§7).
"""

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
