"""
Data models for Meal Planner.

Milestone 1 introduces the `recipes` table and the Recipe model. See
docs/DATA_MODEL.md for the full schema and docs/ROADMAP.md for what belongs
in later milestones (ingredients, plans, history, photos).
"""

import sqlite3
from dataclasses import dataclass
from typing import Optional

SEASONALITIES = ("winter", "spring", "summer", "fall", "all-season")


@dataclass
class Recipe:
    id: int
    name: str
    photo_path: Optional[str]
    cook_time_minutes: int
    family_enjoyment: int
    seasonality: str
    is_quick_fallback: bool
    servings: int
    instructions: Optional[str]
    notes: Optional[str]
    active: bool
    created_at: str
    updated_at: str


def create_recipes_table(conn: sqlite3.Connection) -> None:
    """Create the `recipes` table if it doesn't already exist."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS recipes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    conn.commit()
