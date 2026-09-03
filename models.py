"""
Data models for Meal Planner.

Dataclasses and constants only — table creation lives in `database.py`'s
`SCHEMA_MIGRATIONS` as of Milestone 13 Phase 1 (see docs/DECISIONS.md).
See docs/DATA_MODEL.md for the full schema.
"""

import datetime as dt
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
    is_special_occasion: bool
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
    household_size_override: Optional[int] = None
    assigned_recipe_id: Optional[int] = None


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
    household_size_override: Optional[int] = None


@dataclass
class CookHistoryEntry:
    id: int
    recipe_id: int
    recipe_name: str
    plan_day_id: Optional[int]
    cooked_on: str
    created_at: str
