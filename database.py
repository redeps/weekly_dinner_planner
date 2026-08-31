"""
Database connection helper for Meal Planner.

Returns a connection with the application schema ready. See
docs/DATA_MODEL.md for the full schema and models.py for table-creation
logic.
"""

import sqlite3
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
    return conn
