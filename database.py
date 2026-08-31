"""
Database connection helper for Meal Planner.

Milestone 0 (Foundation): only proves SQLite is reachable from the app.
No application schema (recipes, plans, etc.) is created here yet — that
starts in Milestone 1. See docs/DATA_MODEL.md for the full schema.
"""

import sqlite3
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
DB_PATH = DATA_DIR / "meal_planner.db"


def get_connection() -> sqlite3.Connection:
    """Return a SQLite connection, creating the data/ directory if needed."""
    DATA_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn
