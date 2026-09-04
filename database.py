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
    (
        8,
        # One row per recipient email address, not a JSON list on
        # app_settings — every other table in this schema is a plain
        # relational shape (see docs/DECISIONS.md), and a recipient list
        # is naturally add-one/remove-one, not a single blob to
        # read-modify-write. UNIQUE makes "already added" a DB-level
        # concern instead of app-level dedup logic.
        f"""
        CREATE TABLE IF NOT EXISTS email_recipients (
            id SERIAL PRIMARY KEY,
            email TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL DEFAULT {_NOW_EXPR}
        )
        """,
    ),
    (
        9,
        # Same shape as is_quick_fallback (INTEGER 0/1, default 0) — see
        # docs/DECISIONS.md for why special-occasion recipes are hard-
        # excluded from automatic plan generation but not from swap or
        # browsing.
        "ALTER TABLE recipes ADD COLUMN IF NOT EXISTS is_special_occasion INTEGER NOT NULL DEFAULT 0",
    ),
    (
        10,
        # A discriminator (one of models.COURSES), not an independent 0/1
        # flag like is_quick_fallback/is_special_occasion above — a recipe
        # can't be more than one course at once, so this follows
        # `seasonality`'s shape instead. DEFAULT 'main' backfills every
        # existing recipe the same way DEFAULT 0 backfilled
        # is_special_occasion in migration 9. See docs/DECISIONS.md —
        # Milestone 16.
        "ALTER TABLE recipes ADD COLUMN IF NOT EXISTS course TEXT NOT NULL DEFAULT 'main'",
    ),
    (
        11,
        # Milestone 16 — which non-main recipes are attached to which plan
        # day. One shared table for both sides and desserts, not two
        # separate tables and not a denormalized `course` column here —
        # which course an attached recipe is comes from joining to
        # recipes.course, never duplicated onto this row (see
        # docs/DECISIONS.md for the reasoning). UNIQUE prevents attaching
        # the same recipe to the same day twice.
        """
        CREATE TABLE IF NOT EXISTS plan_day_dishes (
            id SERIAL PRIMARY KEY,
            plan_day_id INTEGER NOT NULL REFERENCES plan_days(id) ON DELETE CASCADE,
            recipe_id INTEGER NOT NULL REFERENCES recipes(id),
            UNIQUE (plan_day_id, recipe_id)
        )
        """,
    ),
    (
        12,
        # Milestone 17 — grocery items not derived from any recipe: a
        # one-off paste-in ("add once, for this week only") and a
        # standing recurring item ("always include, every week") are the
        # same row shape, distinguished only by whether week_plan_id is
        # set — not two separate tables (see docs/DECISIONS.md). NULL =
        # recurring, matched by every week; a set value scopes the row to
        # that one week only, so it naturally stops showing up once a
        # newer week_plan_id exists — no "consumed"/expiry bookkeeping
        # needed. Same name/quantity/unit/store_category shape as
        # recipe_ingredients, since it's aggregated by build_grocery_list()
        # the same way.
        f"""
        CREATE TABLE IF NOT EXISTS manual_grocery_items (
            id SERIAL PRIMARY KEY,
            week_plan_id INTEGER REFERENCES week_plans(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            quantity REAL,
            unit TEXT,
            store_category TEXT NOT NULL DEFAULT 'other',
            created_at TEXT NOT NULL DEFAULT {_NOW_EXPR}
        )
        """,
    ),
    (
        13,
        # Milestone 17 Phase 2 — a persistent correction to which store
        # category a canonical ingredient belongs to, keyed on the same
        # canonical name services/ingredient_canonicalization.py already
        # computes for grouping (its first persisted consumer — see
        # docs/DECISIONS.md). Consulted inside build_grocery_list()'s own
        # aggregation, not by rewriting recipe_ingredients rows — the
        # grocery list is never cached, so resolving the override at
        # aggregation time is already both retroactive and prospective
        # with no bulk UPDATE needed. UNIQUE makes "already overridden"
        # an upsert (ON CONFLICT DO UPDATE), same pattern as
        # app_settings/set_default_household_size.
        f"""
        CREATE TABLE IF NOT EXISTS ingredient_category_overrides (
            id SERIAL PRIMARY KEY,
            canonical_name TEXT NOT NULL UNIQUE,
            store_category TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT {_NOW_EXPR},
            updated_at TEXT NOT NULL DEFAULT {_NOW_EXPR}
        )
        """,
    ),
    (
        14,
        # Milestone 18 Phase 1 — shopping mode's completion flag. NULL
        # (the default for every existing and newly-generated row) means
        # "not completed"; a set timestamp means the Grocery List page
        # treats this week's list as empty until a new week_plan is
        # generated. A fresh generate_week_plan() call never sets this
        # column, so a new week starts unset with zero extra logic — see
        # docs/DECISIONS.md. Nullable, not a boolean 0/1 like this
        # schema's other flags (is_busy, is_quick_fallback): the
        # timestamp itself is useful (when the trip was finished), and
        # "unset" is a real, distinct third state from "false", not just
        # a default value.
        "ALTER TABLE week_plans ADD COLUMN IF NOT EXISTS shopping_completed_at TEXT",
    ),
    (
        15,
        # Milestone 18 Phase 2 — which grocery-list lines are checked off
        # for a week. Keyed on the list's own post-aggregation display
        # identity (canonical name + unit), not a source
        # recipe_ingredients row — a checked "milk" might represent
        # several merged rows (see docs/DECISIONS.md). Row presence =
        # checked, no boolean column, mirroring plan_day_dishes's
        # attach_dish/detach_dish shape. `unit` is NOT NULL DEFAULT '',
        # never NULL: a UNIQUE constraint over a nullable column doesn't
        # reject duplicates in Postgres (NULL is never equal to NULL),
        # which would silently break the upsert this table needs for the
        # common "no unit on this line" case — confirmed directly during
        # the investigation, not assumed.
        f"""
        CREATE TABLE IF NOT EXISTS grocery_checked_items (
            id SERIAL PRIMARY KEY,
            week_plan_id INTEGER NOT NULL REFERENCES week_plans(id) ON DELETE CASCADE,
            canonical_name TEXT NOT NULL,
            unit TEXT NOT NULL DEFAULT '',
            checked_at TEXT NOT NULL DEFAULT {_NOW_EXPR},
            UNIQUE (week_plan_id, canonical_name, unit)
        )
        """,
    ),
]

_EXPORT_TABLES = [
    "recipes",
    "recipe_ingredients",
    "week_plans",
    "plan_days",
    "cook_history",
    "app_settings",
    "email_recipients",
    "plan_day_dishes",
    "manual_grocery_items",
    "ingredient_category_overrides",
    "grocery_checked_items",
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
