"""
Database connection helper for Meal Planner.

Returns a connection with the application schema ready. See
docs/DATA_MODEL.md for the full schema and models.py for table-creation
logic.
"""

import sqlite3
import tempfile
from pathlib import Path

import models

DATA_DIR = Path(__file__).parent / "data"
DB_PATH = DATA_DIR / "meal_planner.db"


def get_connection() -> sqlite3.Connection:
    """Return a SQLite connection, creating the data/ directory and schema."""
    DATA_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    models.create_recipes_table(conn)
    models.create_recipe_ingredients_table(conn)
    models.create_week_plans_table(conn)
    models.create_plan_days_table(conn)
    models.create_cook_history_table(conn)
    return conn


def export_database_bytes() -> bytes:
    """A consistent backup snapshot of the whole database, as bytes, for
    download (see docs/PRODUCT_SPEC.md / Milestone 12 backup-export).

    Uses sqlite3's own backup API rather than reading DB_PATH's raw bytes,
    so a concurrent write in progress can't yield a corrupt snapshot."""
    source_conn = get_connection()
    try:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir) / "backup.db"
            dest_conn = sqlite3.connect(tmp_path)
            try:
                source_conn.backup(dest_conn)
            finally:
                dest_conn.close()
            return tmp_path.read_bytes()
    finally:
        source_conn.close()
