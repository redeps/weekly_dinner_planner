"""
Data models for Meal Planner.

Milestone 1 introduces the `recipes` table and the Recipe model. See
docs/DATA_MODEL.md for the full schema and docs/ROADMAP.md for what belongs
in later milestones (ingredients, plans, history, photos).
"""

import datetime as dt
import sqlite3
from dataclasses import dataclass
from typing import Optional

SEASONALITIES = ("winter", "spring", "summer", "fall", "all-season")
STORE_CATEGORIES = ("produce", "dairy", "meat", "pantry", "frozen", "other")
DAYS_OF_WEEK = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)
DEFAULT_DINNER_READY_TIME = dt.time(18, 0)


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


@dataclass
class Ingredient:
    id: int
    recipe_id: int
    name: str
    quantity: Optional[float]
    unit: Optional[str]
    store_category: str


@dataclass
class CalendarDay:
    """A single day's plan-generation input. Not database-backed yet — see
    docs/DECISIONS.md — Milestone 4 carries these into `plan_days`."""

    day_of_week: str
    is_busy: bool
    dinner_ready_time: dt.time


@dataclass
class WeekPlan:
    id: int
    week_start_date: str
    created_at: str


@dataclass
class PlanDay:
    id: int
    week_plan_id: int
    day_of_week: str
    date: str
    is_busy: bool
    dinner_ready_time: str
    recipe_id: Optional[int]


@dataclass
class CookHistoryEntry:
    id: int
    recipe_id: int
    recipe_name: str
    plan_day_id: Optional[int]
    cooked_on: str
    created_at: str


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


def create_recipe_ingredients_table(conn: sqlite3.Connection) -> None:
    """Create the `recipe_ingredients` table if it doesn't already exist.

    Structured rows, not a text blob — see docs/AGENT_INSTRUCTIONS.md — so
    the grocery list (Milestone 6) can aggregate by name/unit rather than
    parse free text.
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS recipe_ingredients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            recipe_id INTEGER NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            quantity REAL,
            unit TEXT,
            store_category TEXT NOT NULL DEFAULT 'other'
        )
        """
    )
    conn.commit()


def create_week_plans_table(conn: sqlite3.Connection) -> None:
    """Create the `week_plans` table if it doesn't already exist."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS week_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            week_start_date TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    conn.commit()


def create_plan_days_table(conn: sqlite3.Connection) -> None:
    """Create the `plan_days` table if it doesn't already exist."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS plan_days (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            week_plan_id INTEGER NOT NULL REFERENCES week_plans(id) ON DELETE CASCADE,
            day_of_week TEXT NOT NULL,
            date TEXT NOT NULL,
            is_busy INTEGER NOT NULL DEFAULT 0,
            dinner_ready_time TEXT NOT NULL DEFAULT '18:00',
            recipe_id INTEGER REFERENCES recipes(id)
        )
        """
    )
    conn.commit()


def create_cook_history_table(conn: sqlite3.Connection) -> None:
    """Create the `cook_history` table if it doesn't already exist.

    Schema created here in Milestone 4 (ahead of Milestone 8's nominal
    scope in docs/DATA_MODEL.md) because rotation-avoidance scoring needs
    to read `last_cooked_at` from it. The write path — a `finalize_plan()`
    / `mark_day_cooked()` service function — stays Milestone 8 work; see
    docs/DECISIONS.md.
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS cook_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            recipe_id INTEGER NOT NULL REFERENCES recipes(id),
            plan_day_id INTEGER REFERENCES plan_days(id),
            cooked_on TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    conn.commit()
