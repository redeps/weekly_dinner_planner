"""
Plan generation — a weighted scoring pass, not a constraint solver (see
docs/PRODUCT_SPEC.md §9 and docs/AGENT_INSTRUCTIONS.md §5). For each day,
every active recipe gets a weight from seasonality fit, rotation avoidance,
busy-day cook-time preference, and family enjoyment as a tie-breaker; the
day's recipe is then drawn by weighted random choice, not by taking the
highest-scoring candidate outright.

Design choices (rotation window, season mapping, busy-day scope, and why
`cook_history` exists already in this milestone) are recorded in
docs/DECISIONS.md.
"""

import datetime as dt
import random
import sqlite3
from typing import Callable, Optional

from models import DAYS_OF_WEEK, CalendarDay, PlanDay, Recipe, WeekPlan
from services.recipes import list_recipes

ROTATION_WINDOW_DAYS = 21  # 3 weeks — see docs/DECISIONS.md

SEASON_BY_MONTH = {
    12: "winter", 1: "winter", 2: "winter",
    3: "spring", 4: "spring", 5: "spring",
    6: "summer", 7: "summer", 8: "summer",
    9: "fall", 10: "fall", 11: "fall",
}

SEASONAL_MATCH_WEIGHT = 2.0
SEASONAL_OFFSEASON_WEIGHT = 0.5
ROTATION_PENALTY_WEIGHT = 0.2
BUSY_DAY_QUICK_WEIGHT = 2.0
BUSY_DAY_SLOW_WEIGHT = 0.4
BUSY_DAY_QUICK_THRESHOLD_MINUTES = 20
ENJOYMENT_WEIGHT_PER_STAR = 0.1


def current_season(for_date: dt.date) -> str:
    """The season a given date falls in (Northern-hemisphere mapping)."""
    return SEASON_BY_MONTH[for_date.month]


def last_cooked_dates(conn: sqlite3.Connection) -> dict[int, dt.date]:
    """Map recipe_id -> most recent cooked_on date, from cook_history.
    A recipe with no rows is simply absent (never penalized for rotation)."""
    rows = conn.execute(
        "SELECT recipe_id, MAX(cooked_on) AS last_cooked FROM cook_history GROUP BY recipe_id"
    ).fetchall()
    return {row[0]: dt.date.fromisoformat(row[1]) for row in rows}


def score_recipe(
    recipe: Recipe,
    *,
    season: str,
    is_busy: bool,
    last_cooked: Optional[dt.date],
    today: dt.date,
    rotation_window_days: int = ROTATION_WINDOW_DAYS,
) -> float:
    """Weighted score for how well a recipe fits a given day. Higher means
    more likely to be picked — candidates are drawn by weighted random
    choice, not by taking the top score outright."""
    weight = 1.0

    if recipe.seasonality == season:
        weight *= SEASONAL_MATCH_WEIGHT
    elif recipe.seasonality != "all-season":
        weight *= SEASONAL_OFFSEASON_WEIGHT

    if last_cooked is not None and (today - last_cooked).days < rotation_window_days:
        weight *= ROTATION_PENALTY_WEIGHT

    if is_busy:
        if recipe.cook_time_minutes <= BUSY_DAY_QUICK_THRESHOLD_MINUTES:
            weight *= BUSY_DAY_QUICK_WEIGHT
        else:
            weight *= BUSY_DAY_SLOW_WEIGHT

    weight *= 1 + (recipe.family_enjoyment * ENJOYMENT_WEIGHT_PER_STAR)

    return weight


def choose_recipe(
    candidates: list[Recipe],
    *,
    season: str,
    is_busy: bool,
    last_cooked_by_recipe: dict[int, dt.date],
    today: dt.date,
    rng: random.Random,
) -> Recipe:
    """Weighted-random pick of one recipe from `candidates` for a day."""
    weights = [
        score_recipe(
            recipe,
            season=season,
            is_busy=is_busy,
            last_cooked=last_cooked_by_recipe.get(recipe.id),
            today=today,
        )
        for recipe in candidates
    ]
    return rng.choices(candidates, weights=weights, k=1)[0]


def generate_week_plan(
    conn: sqlite3.Connection,
    *,
    week_start_date: dt.date,
    calendar: list[CalendarDay],
    rng: Optional[random.Random] = None,
) -> int:
    """Generate a new week plan — one recipe per day — and persist it as
    `week_plans` + `plan_days` rows. Returns the new week_plan_id.

    Avoids repeating a recipe within the same week when enough distinct
    active recipes exist to do so; falls back to allowing a repeat only if
    the active recipe pool is smaller than 7 (see docs/DECISIONS.md).
    """
    rng = rng or random.Random()
    recipes = list_recipes(conn)
    if not recipes:
        raise ValueError("No active recipes to build a plan from.")

    last_cooked_by_recipe = last_cooked_dates(conn)
    today = dt.date.today()
    calendar_by_day = {day.day_of_week: day for day in calendar}

    week_plan_id = conn.execute(
        "INSERT INTO week_plans (week_start_date) VALUES (?)",
        (week_start_date.isoformat(),),
    ).lastrowid

    used_recipe_ids: set[int] = set()
    for offset, day_name in enumerate(DAYS_OF_WEEK):
        cal_day = calendar_by_day[day_name]
        plan_date = week_start_date + dt.timedelta(days=offset)
        season = current_season(plan_date)

        available = [r for r in recipes if r.id not in used_recipe_ids] or recipes
        chosen = choose_recipe(
            available,
            season=season,
            is_busy=cal_day.is_busy,
            last_cooked_by_recipe=last_cooked_by_recipe,
            today=today,
            rng=rng,
        )
        used_recipe_ids.add(chosen.id)

        conn.execute(
            """
            INSERT INTO plan_days (
                week_plan_id, day_of_week, date, is_busy, dinner_ready_time, recipe_id
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                week_plan_id,
                day_name,
                plan_date.isoformat(),
                int(cal_day.is_busy),
                cal_day.dinner_ready_time.strftime("%H:%M"),
                chosen.id,
            ),
        )

    conn.commit()
    return week_plan_id


def _dict_cursor(conn: sqlite3.Connection) -> sqlite3.Cursor:
    cursor = conn.cursor()
    cursor.row_factory = sqlite3.Row
    return cursor


def _row_to_week_plan(row: sqlite3.Row) -> WeekPlan:
    return WeekPlan(id=row["id"], week_start_date=row["week_start_date"], created_at=row["created_at"])


def _row_to_plan_day(row: sqlite3.Row) -> PlanDay:
    return PlanDay(
        id=row["id"],
        week_plan_id=row["week_plan_id"],
        day_of_week=row["day_of_week"],
        date=row["date"],
        is_busy=bool(row["is_busy"]),
        dinner_ready_time=row["dinner_ready_time"],
        recipe_id=row["recipe_id"],
    )


def get_week_plan(conn: sqlite3.Connection, week_plan_id: int) -> Optional[WeekPlan]:
    row = _dict_cursor(conn).execute(
        "SELECT * FROM week_plans WHERE id = ?", (week_plan_id,)
    ).fetchone()
    return _row_to_week_plan(row) if row else None


def get_latest_week_plan(conn: sqlite3.Connection) -> Optional[WeekPlan]:
    """The most recently generated week plan, if any."""
    row = _dict_cursor(conn).execute(
        "SELECT * FROM week_plans ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return _row_to_week_plan(row) if row else None


def list_plan_days(conn: sqlite3.Connection, week_plan_id: int) -> list[PlanDay]:
    """A week plan's 7 days, in date order."""
    rows = _dict_cursor(conn).execute(
        "SELECT * FROM plan_days WHERE week_plan_id = ? ORDER BY date", (week_plan_id,)
    ).fetchall()
    return [_row_to_plan_day(row) for row in rows]


def get_plan_day(conn: sqlite3.Connection, plan_day_id: int) -> Optional[PlanDay]:
    row = _dict_cursor(conn).execute(
        "SELECT * FROM plan_days WHERE id = ?", (plan_day_id,)
    ).fetchone()
    return _row_to_plan_day(row) if row else None


def swap_day_recipe(
    conn: sqlite3.Connection,
    plan_day_id: int,
    *,
    rng: Optional[random.Random] = None,
    candidate_filter: Optional[Callable[[list[Recipe]], Optional[list[Recipe]]]] = None,
) -> Recipe:
    """Replace a single day's recipe, excluding the one being swapped out,
    using the same scoring as plan generation. Only this day's `plan_days`
    row changes — the rest of the week is untouched (see docs/DATA_MODEL.md).

    `candidate_filter`, if given, is applied to the candidate list before
    scoring — e.g. AI Assist's swap-intent narrowing (see
    services/ai_assist.py). This function has no knowledge of what the
    filter is or does; a filter that raises, or returns something falsy,
    is simply ignored and the unfiltered candidates are used, so a broken
    or unavailable filter can never break a swap (docs/AGENT_INSTRUCTIONS.md
    §6 — no core service may depend on AI assist being available).
    """
    rng = rng or random.Random()
    plan_day = get_plan_day(conn, plan_day_id)
    if plan_day is None:
        raise ValueError(f"No such plan day: {plan_day_id}")

    recipes = list_recipes(conn)
    if not recipes:
        raise ValueError("No active recipes to swap in.")

    candidates = [r for r in recipes if r.id != plan_day.recipe_id] or recipes
    if candidate_filter is not None:
        try:
            filtered = candidate_filter(candidates)
        except Exception:
            filtered = None
        if filtered:
            candidates = filtered
    season = current_season(dt.date.fromisoformat(plan_day.date))
    last_cooked_by_recipe = last_cooked_dates(conn)

    chosen = choose_recipe(
        candidates,
        season=season,
        is_busy=plan_day.is_busy,
        last_cooked_by_recipe=last_cooked_by_recipe,
        today=dt.date.today(),
        rng=rng,
    )

    conn.execute("UPDATE plan_days SET recipe_id = ? WHERE id = ?", (chosen.id, plan_day_id))
    conn.commit()
    return chosen
