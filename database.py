"""
Database connection helper for Meal Planner.

Milestone 13 Phase 1: ported from a SQLite file connection to Postgres,
matching the sibling "home-inventory" app's pattern (see docs/DECISIONS.md
— Milestone 13 hosting architecture). `SCHEMA_MIGRATIONS` replaces
models.py's old per-table `create_*_table()` functions; `get_connection()`
applies any migration newer than the version recorded in the one-row
`schema_version` table.

Test isolation: `schema_name_for(identity)` derives a per-test Postgres
*schema* (not a separate database) from a hash of an arbitrary identity
(e.g. pytest's `tmp_path`), created on first use via `CREATE SCHEMA IF NOT
EXISTS`. `get_connection()` defaults to the `public` schema (real data)
when no identity is given.
"""

import csv
import hashlib
import io
import zipfile

import psycopg
import streamlit as st

# Monkeypatched by AppTest-driven UI tests so that database.get_connection()
# calls made with no explicit identity — as app.py and pages/*.py always
# make them — transparently resolve to an isolated per-test schema instead
# of the real `public` schema. Direct unit tests should prefer passing
# `identity=` explicitly instead of touching this.
TEST_SCHEMA_IDENTITY = None

_NOW_EXPR = "to_char(now() AT TIME ZONE 'utc', 'YYYY-MM-DD HH24:MI:SS')"

# Versioned, additive SQL blocks — one per table, in the order they were
# first introduced. Never edit a block once shipped; add a new (version, sql)
# entry instead. See docs/DECISIONS.md — Milestone 13 hosting architecture —
# for the column-type conventions used here (booleans as INTEGER 0/1, all
# date/timestamp columns as TEXT, primary keys as SERIAL).
SCHEMA_MIGRATIONS: list[tuple[int, str]] = [
    (
        1,
        f"""
        CREATE TABLE IF NOT EXISTS recipes (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            photo_path TEXT,
            cook_time_minutes INTEGER NOT NULL,
            family_enjoyment INTEGER NOT NULL,
            seasonality TEXT NOT NULL,
            is_quick_fallback INTEGER NOT NULL DEFAULT 0,
            servings INTEGER NOT NULL,
            instructions TEXT,
            notes TEXT,
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT {_NOW_EXPR},
            updated_at TEXT NOT NULL DEFAULT {_NOW_EXPR}
        )
        """,
    ),
    (
        2,
        """
        CREATE TABLE IF NOT EXISTS recipe_ingredients (
            id SERIAL PRIMARY KEY,
            recipe_id INTEGER NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            quantity REAL,
            unit TEXT,
            store_category TEXT NOT NULL DEFAULT 'other'
        )
        """,
    ),
    (
        3,
        f"""
        CREATE TABLE IF NOT EXISTS week_plans (
            id SERIAL PRIMARY KEY,
            week_start_date TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT {_NOW_EXPR}
        )
        """,
    ),
    (
        4,
        """
        CREATE TABLE IF NOT EXISTS plan_days (
            id SERIAL PRIMARY KEY,
            week_plan_id INTEGER NOT NULL REFERENCES week_plans(id) ON DELETE CASCADE,
            day_of_week TEXT NOT NULL,
            date TEXT NOT NULL,
            is_busy INTEGER NOT NULL DEFAULT 0,
            dinner_ready_time TEXT NOT NULL DEFAULT '18:00',
            recipe_id INTEGER REFERENCES recipes(id)
        )
        """,
    ),
    (
        5,
        f"""
        CREATE TABLE IF NOT EXISTS cook_history (
            id SERIAL PRIMARY KEY,
            recipe_id INTEGER NOT NULL REFERENCES recipes(id),
            plan_day_id INTEGER REFERENCES plan_days(id),
            cooked_on TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT {_NOW_EXPR}
        )
        """,
    ),
    (
        6,
        # Single-row settings table (id=1), same one-row pattern as
        # schema_version above. Holds only the global default household
        # size — see docs/DATA_MODEL.md and services/settings.py for the
        # lazy-seed-on-read approach that keeps this migration a bare
        # CREATE TABLE. Add new settings columns here only when a
        # milestone actually needs them, not speculatively.
        """
        CREATE TABLE IF NOT EXISTS app_settings (
            id INTEGER PRIMARY KEY,
            default_household_size INTEGER NOT NULL DEFAULT 4
        )
        """,
    ),
    (
        7,
        "ALTER TABLE plan_days ADD COLUMN IF NOT EXISTS household_size_override INTEGER",
    ),
]

_EXPORT_TABLES = [
    "recipes",
    "recipe_ingredients",
    "week_plans",
    "plan_days",
    "cook_history",
    "app_settings",
]


def schema_name_for(identity: object) -> str:
    """A stable, valid Postgres schema name derived from an arbitrary
    identity (e.g. pytest's `tmp_path`)."""
    digest = hashlib.sha256(str(identity).encode()).hexdigest()[:16]
    return f"test_{digest}"


def _apply_migrations(conn: psycopg.Connection) -> None:
    conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
    row = conn.execute("SELECT version FROM schema_version").fetchone()
    current_version = row[0] if row else 0
    for version, sql in SCHEMA_MIGRATIONS:
        if version > current_version:
            conn.execute(sql)
            current_version = version
    if row is None:
        conn.execute("INSERT INTO schema_version (version) VALUES (%s)", (current_version,))
    else:
        conn.execute("UPDATE schema_version SET version = %s", (current_version,))


def get_connection(identity: object = None) -> psycopg.Connection:
    """Return a Postgres connection with the application schema ready.

    With no `identity`, connects to the real `public` schema. With one,
    connects to (creating if needed) an isolated per-test schema — see
    `schema_name_for`.
    """
    dsn = st.secrets["postgres"]["dsn"]
    # autocommit: every statement lands immediately, with no idle-in-
    # transaction connection left holding locks — important here because,
    # unlike a SQLite file, Streamlit's page scripts open a fresh Postgres
    # connection on every rerun and never explicitly close or commit it (see
    # docs/DECISIONS.md). Existing services' explicit conn.commit() calls
    # are harmless no-ops under autocommit, so they didn't need to change.
    conn = psycopg.connect(dsn, autocommit=True)
    identity = identity if identity is not None else TEST_SCHEMA_IDENTITY
    schema = schema_name_for(identity) if identity is not None else "public"
    conn.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
    conn.execute(f'SET search_path TO "{schema}"')
    _apply_migrations(conn)
    return conn


def export_database_bytes() -> bytes:
    """A consistent snapshot of the whole database, as a zip of one CSV per
    table, for download (see docs/PRODUCT_SPEC.md / Milestone 12 backup-
    export). A single REPEATABLE READ transaction keeps all five tables'
    snapshots consistent with each other even if a write happens mid-export.

    This is a minimal stand-in for Milestone 13 Phase 6's eventual backup
    design (pure-Python per-table CSV/zip export, no `pg_dump`) — the old
    sqlite3-backup-file approach couldn't survive the Postgres connection
    switch, so this pass had to land something working now rather than
    leave the Home page's backup button broken until Phase 6. See
    docs/DECISIONS.md.
    """
    conn = get_connection()
    try:
        buffer = io.BytesIO()
        with conn.transaction():
            conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                for table in _EXPORT_TABLES:
                    cursor = conn.execute(f"SELECT * FROM {table}")
                    columns = [desc.name for desc in cursor.description]
                    text_buffer = io.StringIO()
                    writer = csv.writer(text_buffer)
                    writer.writerow(columns)
                    writer.writerows(cursor.fetchall())
                    zf.writestr(f"{table}.csv", text_buffer.getvalue())
        return buffer.getvalue()
    finally:
        conn.close()
