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

import collections
import datetime as dt
import random
from typing import Callable, Optional

import psycopg
from psycopg.rows import dict_row

from models import DAYS_OF_WEEK, CalendarDay, PlanDay, Recipe, WeekPlan
from services.ingredient_canonicalization import canonicalize_ingredient_name
from services.ingredients import list_ingredients
from services.recipes import get_recipe, list_recipes

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
BUSY_DAY_QUICK_FALLBACK_BONUS = 7.5  # see docs/DECISIONS.md
NON_BUSY_DAY_QUICK_FALLBACK_PENALTY = 0.1  # see docs/DECISIONS.md
ENJOYMENT_WEIGHT_PER_STAR = 0.1
INGREDIENT_OVERLAP_BONUS = 1.0  # see docs/DECISIONS.md
STAPLE_FREQUENCY_THRESHOLD = 0.5  # see docs/DECISIONS.md


def current_season(for_date: dt.date) -> str:
    """The season a given date falls in (Northern-hemisphere mapping)."""
    return SEASON_BY_MONTH[for_date.month]


def last_cooked_dates(conn: psycopg.Connection) -> dict[int, dt.date]:
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
    overlap_count: int = 0,
) -> float:
    """Weighted score for how well a recipe fits a given day. Higher means
    more likely to be picked — candidates are drawn by weighted random
    choice, not by taking the top score outright.

    `overlap_count` — how many *distinctive* (non-staple) canonical
    ingredients this recipe shares with recipes already committed to
    elsewhere in the same week — is precomputed by the caller
    (`choose_recipe`), not looked up here, same as `last_cooked`. See
    docs/DECISIONS.md for why this needed a genuinely new mechanism
    (a running cross-day accumulator) rather than another static
    per-recipe weight like everything else in this function.
    """
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
        if recipe.is_quick_fallback:
            weight *= BUSY_DAY_QUICK_FALLBACK_BONUS
    else:
        if recipe.is_quick_fallback:
            weight *= NON_BUSY_DAY_QUICK_FALLBACK_PENALTY

    weight *= 1 + (recipe.family_enjoyment * ENJOYMENT_WEIGHT_PER_STAR)

    if overlap_count:
        weight *= (1 + INGREDIENT_OVERLAP_BONUS) ** overlap_count

    return weight


def choose_recipe(
    candidates: list[Recipe],
    *,
    season: str,
    is_busy: bool,
    last_cooked_by_recipe: dict[int, dt.date],
    today: dt.date,
    rng: random.Random,
    canonical_ingredients_by_recipe: Optional[dict[int, frozenset[str]]] = None,
    committed_canonical_ingredients: frozenset[str] = frozenset(),
) -> Recipe:
    """Weighted-random pick of one recipe from `candidates` for a day.

    `canonical_ingredients_by_recipe` / `committed_canonical_ingredients`
    are optional and default to "no overlap bonus for anyone" — the shape
    `swap_day_recipe` relies on to stay completely unaffected by this
    feature (see docs/DECISIONS.md: swap deliberately doesn't get
    cross-day overlap awareness). `committed_canonical_ingredients` is
    assumed to already exclude staple ingredients (see
    `_staple_canonical_ingredients`), so no staple-filtering happens here
    on the candidate side either.
    """
    canonical_ingredients_by_recipe = canonical_ingredients_by_recipe or {}
    weights = [
        score_recipe(
            recipe,
            season=season,
            is_busy=is_busy,
            last_cooked=last_cooked_by_recipe.get(recipe.id),
            today=today,
            overlap_count=len(
                canonical_ingredients_by_recipe.get(recipe.id, frozenset())
                & committed_canonical_ingredients
            ),
        )
        for recipe in candidates
    ]
    return rng.choices(candidates, weights=weights, k=1)[0]


def _staple_canonical_ingredients(
    canonical_ingredients_by_recipe: dict[int, frozenset[str]]
) -> frozenset[str]:
    """Canonical ingredients present in >= STAPLE_FREQUENCY_THRESHOLD of
    recipes that actually have at least one ingredient — recipes with
    none (e.g. Takeout) don't inform commonality and are excluded from
    the denominator, though they remain full candidates for selection as
    always. Dynamic, recomputed fresh from the current candidate pool
    every generation run, not a hardcoded word list — so it naturally
    adapts as more recipes get added over time instead of going stale.
    See docs/DECISIONS.md."""
    non_empty = [
        ingredients for ingredients in canonical_ingredients_by_recipe.values() if ingredients
    ]
    if not non_empty:
        return frozenset()
    frequency: collections.Counter = collections.Counter()
    for ingredients in non_empty:
        frequency.update(ingredients)
    threshold_count = STAPLE_FREQUENCY_THRESHOLD * len(non_empty)
    return frozenset(
        ingredient for ingredient, count in frequency.items() if count >= threshold_count
    )


def generate_week_plan(
    conn: psycopg.Connection,
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

    `is_special_occasion` recipes are hard-excluded from this automatic
    pool entirely (including the small-pool repeat fallback above) — they
    only ever get assigned to a day deliberately, via swap or the Weekly
    Calendar screen's direct-assignment picker, never picked for you.

    A day whose `CalendarDay.assigned_recipe_id` is set (the direct-
    assignment picker) skips scoring entirely — the assigned recipe is
    placed directly, no candidate pool involved. Since that recipe is
    always `is_special_occasion` (the picker only offers those) and is
    therefore never a member of `recipes` above, it's structurally
    impossible for a pre-assignment to consume a slot from the normal
    pool or affect the no-repeat guarantee for the week's other,
    auto-generated days (see docs/DECISIONS.md). If the assigned recipe
    no longer exists or was deactivated by generation time, this falls
    back to normal scoring for that day rather than failing the whole
    plan.

    Ingredient-overlap bonus (see docs/DECISIONS.md): auto-generated days
    favor recipes that share *distinctive* (non-staple) canonical
    ingredients with recipes already chosen earlier in this same
    generation run — `canonical_ingredients_by_recipe` is precomputed
    once up front, same shape as `last_cooked_by_recipe` below, and
    `committed_canonical_ingredients` accumulates as the day loop runs.
    Pre-assigned special-occasion days are deliberately never added to
    that accumulator — their ingredients don't influence the rest of the
    week's overlap scoring, by construction, not by filtering them out
    afterward. `swap_day_recipe` does not get this treatment at all —
    see its own docstring.
    """
    rng = rng or random.Random()
    recipes = [r for r in list_recipes(conn) if not r.is_special_occasion]
    if not recipes:
        raise ValueError(
            "No active, non-special-occasion recipes to build a plan from."
        )

    canonical_ingredients_by_recipe: dict[int, frozenset[str]] = {}
    for recipe in recipes:
        ingredients = list_ingredients(conn, recipe.id)
        canonical_ingredients_by_recipe[recipe.id] = frozenset(
            canonicalize_ingredient_name(ingredient.name)
            for ingredient in ingredients
            if ingredient.name.strip()
        )
    staple_canonical_ingredients = _staple_canonical_ingredients(canonical_ingredients_by_recipe)

    last_cooked_by_recipe = last_cooked_dates(conn)
    today = dt.date.today()
    calendar_by_day = {day.day_of_week: day for day in calendar}

    # autocommit=True (see docs/DECISIONS.md) means each statement lands on
    # its own by default — this week_plans + 7x plan_days sequence needs an
    # explicit transaction so a failure partway through the week can't leave
    # an orphan week_plans row with only some of its days created.
    with conn.transaction():
        week_plan_id = conn.execute(
            "INSERT INTO week_plans (week_start_date) VALUES (%s) RETURNING id",
            (week_start_date.isoformat(),),
        ).fetchone()[0]

        used_recipe_ids: set[int] = set()
        committed_canonical_ingredients: set[str] = set()
        for offset, day_name in enumerate(DAYS_OF_WEEK):
            cal_day = calendar_by_day[day_name]
            plan_date = week_start_date + dt.timedelta(days=offset)

            chosen_id = None
            if cal_day.assigned_recipe_id is not None:
                assigned = get_recipe(conn, cal_day.assigned_recipe_id)
                if assigned is not None and assigned.active:
                    chosen_id = assigned.id

            if chosen_id is None:
                season = current_season(plan_date)
                available = [r for r in recipes if r.id not in used_recipe_ids] or recipes
                chosen = choose_recipe(
                    available,
                    season=season,
                    is_busy=cal_day.is_busy,
                    last_cooked_by_recipe=last_cooked_by_recipe,
                    today=today,
                    rng=rng,
                    canonical_ingredients_by_recipe=canonical_ingredients_by_recipe,
                    committed_canonical_ingredients=frozenset(committed_canonical_ingredients),
                )
                chosen_id = chosen.id
                used_recipe_ids.add(chosen_id)
                committed_canonical_ingredients |= (
                    canonical_ingredients_by_recipe.get(chosen_id, frozenset())
                    - staple_canonical_ingredients
                )

            conn.execute(
                """
                INSERT INTO plan_days (
                    week_plan_id, day_of_week, date, is_busy, dinner_ready_time, recipe_id,
                    household_size_override
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    week_plan_id,
                    day_name,
                    plan_date.isoformat(),
                    int(cal_day.is_busy),
                    cal_day.dinner_ready_time.strftime("%H:%M"),
                    chosen_id,
                    cal_day.household_size_override,
                ),
            )

    return week_plan_id


def _dict_cursor(conn: psycopg.Connection) -> psycopg.Cursor:
    return conn.cursor(row_factory=dict_row)


def _row_to_week_plan(row: dict) -> WeekPlan:
    return WeekPlan(id=row["id"], week_start_date=row["week_start_date"], created_at=row["created_at"])


def _row_to_plan_day(row: dict) -> PlanDay:
    return PlanDay(
        id=row["id"],
        week_plan_id=row["week_plan_id"],
        day_of_week=row["day_of_week"],
        date=row["date"],
        is_busy=bool(row["is_busy"]),
        dinner_ready_time=row["dinner_ready_time"],
        recipe_id=row["recipe_id"],
        household_size_override=row["household_size_override"],
    )


def get_week_plan(conn: psycopg.Connection, week_plan_id: int) -> Optional[WeekPlan]:
    row = _dict_cursor(conn).execute(
        "SELECT * FROM week_plans WHERE id = %s", (week_plan_id,)
    ).fetchone()
    return _row_to_week_plan(row) if row else None


def get_latest_week_plan(conn: psycopg.Connection) -> Optional[WeekPlan]:
    """The most recently generated week plan, if any."""
    row = _dict_cursor(conn).execute(
        "SELECT * FROM week_plans ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return _row_to_week_plan(row) if row else None


def list_plan_days(conn: psycopg.Connection, week_plan_id: int) -> list[PlanDay]:
    """A week plan's 7 days, in date order."""
    rows = _dict_cursor(conn).execute(
        "SELECT * FROM plan_days WHERE week_plan_id = %s ORDER BY date", (week_plan_id,)
    ).fetchall()
    return [_row_to_plan_day(row) for row in rows]


def get_plan_day(conn: psycopg.Connection, plan_day_id: int) -> Optional[PlanDay]:
    row = _dict_cursor(conn).execute(
        "SELECT * FROM plan_days WHERE id = %s", (plan_day_id,)
    ).fetchone()
    return _row_to_plan_day(row) if row else None


def swap_day_recipe(
    conn: psycopg.Connection,
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

    Deliberately does NOT get `generate_week_plan()`'s ingredient-overlap
    bonus — a swap is a single, isolated day change with no visibility
    into what the rest of the week already committed to, and giving it
    that context was a real design question this project chose not to
    take on yet, not an oversight. See docs/DECISIONS.md.
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

    conn.execute("UPDATE plan_days SET recipe_id = %s WHERE id = %s", (chosen.id, plan_day_id))
    conn.commit()
    return chosen
